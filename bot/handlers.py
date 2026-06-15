import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import Config, Plan
from bot.db import Database
from bot.xui import XUIManager
from bot.payments import CryptoBot
from bot.keyboards import main_menu, back_button, plans_keyboard, payment_methods_keyboard, admin_menu

logger = logging.getLogger(__name__)


def create_router(cfg: Config, db: Database, xui: XUIManager):
    router = Router()
    crypto = CryptoBot(cfg.crypto_bot_token) if cfg.crypto_bot_token else None

    async def notify_admin(bot: Bot, text: str):
        for admin_id in cfg.admin_ids:
            try:
                await bot.send_message(admin_id, text, disable_notification=True)
            except Exception:
                pass

    async def process_payment(
        tg_id: int,
        plan: Plan,
        payment_id: int,
        payment_system: str,
        bot: Bot,
    ):
        user = await db.get_user(tg_id)
        if not user:
            return

        try:
            client_uuid, client = await xui.create_client(
                inbound_id=cfg.xui_inbound_id,
                email=f"tg_{tg_id}",
                days=plan.days,
                traffic_gb=plan.traffic_gb,
            )
        except Exception as e:
            logger.error(f"3x-UI create client error: {e}")
            await bot.send_message(tg_id, f"\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u043a\u043b\u0438\u0435\u043d\u0442\u0430: {e}")
            return

        await db.add_subscription(
            user_id=user["id"],
            plan_name=plan.name,
            uuid_str=client_uuid,
            inbound_id=cfg.xui_inbound_id,
            days=plan.days,
            traffic_gb=plan.traffic_gb,
        )
        await db.update_transaction(str(payment_id), "completed")

        sub_url = cfg.make_sub_url(client_uuid)
        msg = (
            f"\u2705 \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d\u0430!\n\n"
            f"\U0001f4a1 \u0422\u0430\u0440\u0438\u0444: {plan.name}\n"
            f"\U0001f4c5 \u0421\u0440\u043e\u043a: {plan.days} \u0434\u043d\u0435\u0439\n\n"
            f"\U0001f517 \u0421\u0441\u044b\u043b\u043a\u0430 \u043d\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443:\n"
            f"<code>{sub_url}</code>\n\n"
            f"\u0418\u043c\u043f\u043e\u0440\u0442\u0438\u0440\u0443\u0439\u0442\u0435 \u044d\u0442\u0443 \u0441\u0441\u044b\u043b\u043a\u0443 \u0432 \u0432\u0430\u0448\u0435\u043c VPN-\u043a\u043b\u0438\u0435\u043d\u0442\u0435."
        )
        try:
            await bot.send_message(tg_id, msg)
        except Exception as e:
            logger.error(f"Failed to send sub URL to {tg_id}: {e}")

        await notify_admin(
            bot,
            f"\U0001f514 \u041d\u043e\u0432\u0430\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430!\n"
            f"\U0001f464 {user['username'] or tg_id}\n"
            f"\U0001f4a1 {plan.name} | ${plan.price}\n"
            f"\U0001f517 {sub_url}",
        )

    @router.message(Command("start"))
    async def cmd_start(message: Message):
        tg_id = message.from_user.id
        user = await db.create_user(tg_id, message.from_user.username)

        welcome = (
            f"\u0414\u043e\u0431\u0440\u043e \u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c, {message.from_user.full_name}!\n\n"
            f"\u042f \u043f\u043e\u043c\u043e\u0433\u0443 \u043f\u0440\u0438\u043e\u0431\u0440\u0435\u0441\u0442\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443 VPN.\n"
            f"\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 \u043d\u0438\u0436\u0435 \u0434\u043b\u044f \u043d\u0430\u0432\u0438\u0433\u0430\u0446\u0438\u0438."
        )
        await message.answer(welcome, reply_markup=main_menu())

        if tg_id in cfg.admin_ids and not user.get("is_admin"):
            await db.conn.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (tg_id,))
            await db.conn.commit()

    @router.callback_query(F.data == "menu")
    async def cb_menu(callback: CallbackQuery):
        await callback.message.edit_text(
            "\u0413\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e:", reply_markup=main_menu()
        )

    @router.callback_query(F.data == "help")
    async def cb_help(callback: CallbackQuery):
        text = (
            "\U0001f4ac \u041f\u043e\u043c\u043e\u0449\u044c\n\n"
            "\U0001f48e \u041a\u0443\u043f\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443 \u2014 \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0438 \u043e\u043f\u043b\u0430\u0442\u0438\u0442\u0435\n"
            "\U0001f4cb \u041c\u043e\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438 \u2014 \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u0434\u043f\u0438\u0441\u043e\u043a\n\n"
            "\u041f\u043e\u0441\u043b\u0435 \u043e\u043f\u043b\u0430\u0442\u044b \u0432\u044b \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 \u0441\u0441\u044b\u043b\u043a\u0443 \u043d\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443."
        )
        await callback.message.edit_text(text, reply_markup=back_button())

    @router.callback_query(F.data == "buy")
    async def cb_buy(callback: CallbackQuery):
        if not cfg.plans:
            await callback.message.edit_text(
                "\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0445 \u0442\u0430\u0440\u0438\u0444\u043e\u0432.", reply_markup=back_button()
            )
            return
        await callback.message.edit_text(
            "\U0001f48e \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444:",
            reply_markup=plans_keyboard(cfg.plans, "plan"),
        )

    @router.callback_query(F.data.startswith("plan:"))
    async def cb_select_plan(callback: CallbackQuery, state: FSMContext):
        idx = int(callback.data.split(":")[1])
        plan = cfg.plans[idx]
        await state.update_data(plan_index=idx)

        traffic = f"{plan.traffic_gb} \u0413\u0411" if plan.traffic_gb > 0 else "\u0411\u0435\u0437\u043b\u0438\u043c\u0438\u0442"
        text = (
            f"\U0001f4a1 \u0422\u0430\u0440\u0438\u0444: {plan.name}\n"
            f"\U0001f4b5 \u0426\u0435\u043d\u0430: ${plan.price}\n"
            f"\U0001f4be \u0422\u0440\u0430\u0444\u0438\u043a: {traffic}\n"
            f"\U0001f4c5 \u0421\u0440\u043e\u043a: {plan.days} \u0434\u043d\u0435\u0439\n\n"
            f"\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b:"
        )
        has_crypto = bool(cfg.crypto_bot_token)
        has_usdt = bool(cfg.usdt_address)
        await callback.message.edit_text(text, reply_markup=payment_methods_keyboard(has_crypto, has_usdt))

    @router.callback_query(F.data == "pay:usdt")
    async def cb_pay_usdt(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        idx = data.get("plan_index")
        if idx is None:
            await callback.message.edit_text(
                "\u041e\u0448\u0438\u0431\u043a\u0430: \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0437\u0430\u043d\u043e\u0432\u043e.",
                reply_markup=back_button(),
            )
            return
        plan = cfg.plans[idx]
        text = (
            f"\U0001f4b0 \u041e\u043f\u043b\u0430\u0442\u0430 USDT {cfg.usdt_network}\n\n"
            f"\u0421\u0443\u043c\u043c\u0430: ${plan.price} (\u2248 {plan.price} USDT)\n\n"
            f"\u0410\u0434\u0440\u0435\u0441 \u0434\u043b\u044f \u043e\u043f\u043b\u0430\u0442\u044b:\n"
            f"<code>{cfg.usdt_address}</code>\n\n"
            f"\u0421\u0435\u0442\u044c: {cfg.usdt_network}\n\n"
            f"\u041f\u043e\u0441\u043b\u0435 \u043e\u043f\u043b\u0430\u0442\u044b \u043e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0447\u0435\u043a \u0430\u0434\u043c\u0438\u043d\u0443 \u0438\u043b\u0438 \u043e\u0436\u0438\u0434\u0430\u0439\u0442\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f."
        )
        await callback.message.edit_text(text, reply_markup=back_button())

    @router.callback_query(F.data == "pay:crypto")
    async def cb_pay_crypto(callback: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        idx = data.get("plan_index")
        if idx is None:
            await callback.message.edit_text(
                "\u041e\u0448\u0438\u0431\u043a\u0430: \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0430\u0440\u0438\u0444 \u0437\u0430\u043d\u043e\u0432\u043e.",
                reply_markup=back_button(),
            )
            return
        plan = cfg.plans[idx]
        tg_id = callback.from_user.id

        if not crypto:
            await callback.message.edit_text(
                "\u041e\u043f\u043b\u0430\u0442\u0430 \u0447\u0435\u0440\u0435\u0437 CryptoBot \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430.",
                reply_markup=back_button(),
            )
            return

        await callback.message.edit_text("\U000023f3 \u0421\u043e\u0437\u0434\u0430\u0451\u043c \u0441\u0447\u0451\u0442...")

        invoice = await crypto.create_invoice(
            amount=plan.price,
            currency=cfg.currency,
            description=f"{plan.name} | @{callback.from_user.username or tg_id}",
        )

        if not invoice:
            await callback.message.edit_text(
                "\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0441\u0447\u0451\u0442\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.",
                reply_markup=back_button(),
            )
            return

        user = await db.get_user(tg_id)
        await db.add_transaction(
            user_id=user["id"],
            amount=plan.price,
            currency=cfg.currency,
            payment_system="cryptobot",
            payment_id=str(invoice.invoice_id),
        )

        await state.update_data(payment_id=invoice.invoice_id, plan_index=idx)
        await callback.message.edit_text(
            f"\U0001f4b1 \u0421\u0447\u0451\u0442 \u0441\u043e\u0437\u0434\u0430\u043d!\n\n"
            f"\u0421\u0443\u043c\u043c\u0430: ${plan.price}\n"
            f"\u0417\u0430: {plan.name}\n\n"
            f"\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435 \u0434\u043b\u044f \u043e\u043f\u043b\u0430\u0442\u044b:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="\U0001f4b1 \u041e\u043f\u043b\u0430\u0442\u0438\u0442\u044c", url=invoice.pay_url)],
                    [InlineKeyboardButton(text="\u2705 \u042f \u043e\u043f\u043b\u0430\u0442\u0438\u043b", callback_data=f"check_pay:{invoice.invoice_id}:{idx}")],
                    [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="buy")],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("check_pay:"))
    async def cb_check_payment(callback: CallbackQuery, state: FSMContext, bot: Bot):
        parts = callback.data.split(":")
        _, pay_id_str, idx_str = parts
        pay_id = int(pay_id_str)
        idx = int(idx_str)
        plan = cfg.plans[idx]
        tg_id = callback.from_user.id

        if not crypto:
            await callback.answer("\u041f\u043b\u0430\u0442\u0435\u0436\u043d\u0430\u044f \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430", show_alert=True)
            return

        invoice = await crypto.check_invoice(pay_id)
        if invoice and invoice.status == "paid":
            await process_payment(tg_id, plan, pay_id, "cryptobot", bot)
            await callback.message.edit_text(
                f"\u2705 \u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430!\n\n"
                f"\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d\u0430.",
                reply_markup=main_menu(),
            )
        else:
            await callback.answer(
                "\U000023f3 \u041e\u043f\u043b\u0430\u0442\u0430 \u0435\u0449\u0451 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.",
                show_alert=True,
            )

    @router.callback_query(F.data == "my_subs")
    async def cb_my_subs(callback: CallbackQuery):
        tg_id = callback.from_user.id
        user = await db.get_user(tg_id)
        if not user:
            await callback.message.edit_text("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 /start", reply_markup=back_button())
            return

        subs = await db.get_user_subscriptions(user["id"])
        if not subs:
            await callback.message.edit_text(
                "\u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u0434\u043f\u0438\u0441\u043e\u043a.",
                reply_markup=plans_keyboard(cfg.plans, "plan"),
            )
            return

        text_parts = ["\U0001f4cb \u0412\u0430\u0448\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438:\n"]
        for s in subs:
            expired = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else None
            expired_str = expired.strftime("%d.%m.%Y %H:%M") if expired else "\u0431\u0435\u0441\u0441\u0440\u043e\u0447\u043d\u043e"
            total_gb = s["traffic_total"] / 1024**3 if s["traffic_total"] else 0
            traffic_str = f"{total_gb:.1f} \u0413\u0411" if total_gb > 0 else "\u0411\u0435\u0437\u043b\u0438\u043c\u0438\u0442"
            sub_url = cfg.make_sub_url(s["uuid"])
            text_parts.append(
                f"\n\u25b6 {s['plan_name']}\n"
                f"\U0001f4c5 \u0414\u043e: {expired_str}\n"
                f"\U0001f4be \u0422\u0440\u0430\u0444\u0438\u043a: {traffic_str}\n"
                f"\U0001f517 <code>{sub_url}</code>\n"
            )
        await callback.message.edit_text("\n".join(text_parts), reply_markup=back_button())

    @router.callback_query(F.data == "admin")
    async def cb_admin(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
            return
        await callback.message.edit_text("\U0001f6e1 \u0410\u0434\u043c\u0438\u043d-\u043f\u0430\u043d\u0435\u043b\u044c:", reply_markup=admin_menu())

    @router.callback_query(F.data == "admin:users")
    async def cb_admin_users(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        users = await db.get_all_users()
        text = f"\U0001f465 \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438 ({len(users)}):\n\n"
        for u in users[:50]:
            text += f"\u25b6 {u['username'] or 'no username'} (ID: {u['telegram_id']})\n"
        await callback.message.edit_text(text, reply_markup=admin_menu())

    @router.callback_query(F.data == "admin:subs")
    async def cb_admin_subs(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        cursor = await db.conn.execute(
            "SELECT s.*, u.telegram_id, u.username FROM subscriptions s JOIN users u ON s.user_id = u.id ORDER BY s.created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        if not rows:
            await callback.message.edit_text("\u041d\u0435\u0442 \u043f\u043e\u0434\u043f\u0438\u0441\u043e\u043a.", reply_markup=admin_menu())
            return
        text = "\U0001f4cb \u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438:\n\n"
        for r in rows:
            text += f"\u25b6 {r['username'] or r['telegram_id']} \u2014 {r['plan_name']} \u2014 {'\u2705' if r['is_active'] else '\u274c'}\n"
        await callback.message.edit_text(text, reply_markup=admin_menu())

    @router.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id not in cfg.admin_ids:
            await message.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430")
            return
        await message.answer("\U0001f6e1 \u0410\u0434\u043c\u0438\u043d-\u043f\u0430\u043d\u0435\u043b\u044c:", reply_markup=admin_menu())

    @router.message(Command("my"))
    async def cmd_my(message: Message):
        tg_id = message.from_user.id
        user = await db.get_user(tg_id)
        if not user:
            await message.answer("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 /start")
            return
        subs = await db.get_user_subscriptions(user["id"])
        if not subs:
            await message.answer(
                "\u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u0434\u043f\u0438\u0441\u043e\u043a.",
                reply_markup=plans_keyboard(cfg.plans, "plan"),
            )
            return
        for s in subs:
            expired = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else None
            expired_str = expired.strftime("%d.%m.%Y %H:%M") if expired else "\u0431\u0435\u0441\u0441\u0440\u043e\u0447\u043d\u043e"
            sub_url = cfg.make_sub_url(s["uuid"])
            await message.answer(
                f"\u25b6 {s['plan_name']}\n"
                f"\U0001f4c5 \u0414\u043e: {expired_str}\n"
                f"\U0001f517 <code>{sub_url}</code>"
            )

    @router.message(Command("plans"))
    async def cmd_plans(message: Message):
        if not cfg.plans:
            await message.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0445 \u0442\u0430\u0440\u0438\u0444\u043e\u0432.")
            return
        text = "\U0001f48e \u0414\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0435 \u0442\u0430\u0440\u0438\u0444\u044b:\n\n"
        for i, p in enumerate(cfg.plans):
            traffic = f"{p.traffic_gb} \u0413\u0411" if p.traffic_gb > 0 else "\u0411\u0435\u0437\u043b\u0438\u043c\u0438\u0442"
            text += f"{i+1}. {p.name} \u2014 ${p.price} \u2014 {traffic} \u2014 {p.days} \u0434\u043d.\n"
        text += "\n\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u00ab\u041a\u0443\u043f\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443\u00bb \u0434\u043b\u044f \u043f\u043e\u043a\u0443\u043f\u043a\u0438."
        await message.answer(text, reply_markup=main_menu())

    @router.message(Command("broadcast"))
    async def cmd_broadcast(message: Message, bot: Bot):
        if message.from_user.id not in cfg.admin_ids:
            return
        text = message.text.replace("/broadcast", "", 1).strip()
        if not text:
            await message.answer("\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0442\u0435\u043a\u0441\u0442: /broadcast \u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435")
            return
        users = await db.get_all_users()
        sent = 0
        for u in users:
            try:
                await bot.send_message(u["telegram_id"], text)
                sent += 1
            except Exception:
                pass
        await message.answer(f"\u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430. \u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e: {sent}/{len(users)}")

    @router.message()
    async def fallback(message: Message):
        await message.answer(
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 \u043c\u0435\u043d\u044e \u0438\u043b\u0438 /start",
            reply_markup=main_menu(),
        )

    return router
