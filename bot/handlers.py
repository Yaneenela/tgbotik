import logging
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import Config, Plan
from bot.db import Database
from bot.xui import XUIManager
from bot.payments import YooKassa, CryptoBot
from bot.keyboards import main_menu, back_button, plans_keyboard, payment_methods_keyboard, admin_menu, admin_subs_list_keyboard, admin_sub_actions_keyboard

logger = logging.getLogger(__name__)


async def _process_payment(
    cfg: Config, db: Database, xui: XUIManager, bot: Bot,
    tg_id: int, plan: Plan, payment_id: str,
):
    user = await db.get_user(tg_id)
    if not user:
        return

    existing = await db.get_active_sub_by_user_and_plan(user["id"], plan.name)

    if existing:
        try:
            await xui.update_client_expiry(existing["uuid"], plan.days, cfg.xui_inbound_ids)
        except Exception as e:
            logger.error(f"3x-UI extend error: {e}")
            await bot.send_message(tg_id, f"\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u043e\u0434\u043b\u0435\u043d\u0438\u044f: {e}")
            return
        await db.extend_expiry(existing["id"], plan.days)
        client_uuid = existing["uuid"]
        is_renewal = True
    else:
        try:
            client_uuid, client = await xui.create_client(
                inbound_ids=cfg.xui_inbound_ids,
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
            inbound_id=cfg.xui_inbound_ids[0],
            days=plan.days,
            traffic_gb=plan.traffic_gb,
        )
        is_renewal = False

    sub_url = cfg.make_sub_url(client_uuid)
    if is_renewal:
        msg = (
            f"\u2705 \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043f\u0440\u043e\u0434\u043b\u0435\u043d\u0430!\n\n"
            f"\U0001f4a1 \u0422\u0430\u0440\u0438\u0444: {plan.name}\n"
            f"\U0001f4c5 \u0421\u0440\u043e\u043a: +{plan.days} \u0434\u043d\u0435\u0439\n\n"
            f"\U0001f517 \u0421\u0441\u044b\u043b\u043a\u0430 \u043d\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443:\n"
            f"<code>{sub_url}</code>"
        )
    else:
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

    label = "\u041d\u043e\u0432\u0430\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430" if not is_renewal else "\u041f\u0440\u043e\u0434\u043b\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438"
    for admin_id in cfg.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"\U0001f514 {label}!\n"
                f"\U0001f464 {user['username'] or tg_id}\n"
                f"\U0001f4a1 {plan.name} | {plan.price} \u0440\u0443\u0431\n"
                f"\U0001f517 {sub_url}",
                disable_notification=True,
            )
        except Exception:
            pass


async def check_pending_payments(cfg: Config, db: Database, xui: XUIManager, bot: Bot):
    await asyncio.sleep(10)
    yoo = YooKassa(cfg.yookassa_shop_id, cfg.yookassa_secret_key) if cfg.yookassa_shop_id and cfg.yookassa_secret_key else None
    crypto = CryptoBot(cfg.crypto_bot_token) if cfg.crypto_bot_token else None
    while True:
        try:
            cursor = await db.conn.execute(
                "SELECT t.*, u.telegram_id FROM transactions t JOIN users u ON t.user_id = u.id "
                "WHERE t.status = 'pending'"
            )
            rows = await cursor.fetchall()
            for row in rows:
                created = datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None
                if created and datetime.now() - created > timedelta(minutes=5):
                    await db.update_transaction(row["payment_id"], "failed")
                    continue

                plan = next((p for p in cfg.plans if p.name == row["plan_name"]), None)
                if not plan:
                    continue

                paid = False
                if row["payment_system"] == "yookassa" and yoo:
                    payment = await yoo.check_payment(row["payment_id"])
                    if payment and payment.status == "succeeded":
                        paid = True
                elif row["payment_system"] == "cryptobot" and crypto:
                    invoice = await crypto.check_invoice(int(row["payment_id"]))
                    if invoice and invoice.status == "paid":
                        paid = True

                if paid:
                    await db.conn.execute(
                        "UPDATE transactions SET status = 'processing' WHERE payment_id = ? AND status = 'pending'",
                        (row["payment_id"],),
                    )
                    await db.conn.commit()
                    cursor2 = await db.conn.execute(
                        "SELECT changes()"
                    )
                    rowcount = (await cursor2.fetchone())[0]
                    if rowcount == 0:
                        continue
                    await _process_payment(cfg, db, xui, bot, row["telegram_id"], plan, row["payment_id"])
                    await db.update_transaction(row["payment_id"], "completed")
                    try:
                        await bot.send_message(
                            row["telegram_id"],
                            "\u2705 \u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430! \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d\u0430.",
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Payment checker error: {e}")
        await asyncio.sleep(30)


async def scheduler(cfg: Config, db: Database, xui: XUIManager, bot: Bot):
    await asyncio.sleep(30)
    while True:
        try:
            now = datetime.now()
            expired = await db.get_expired_subs()
            for sub in expired:
                try:
                    await xui.delete_client(sub["uuid"], cfg.xui_inbound_ids)
                except Exception as e:
                    logger.error(f"Failed to delete expired client: {e}")
                await db.deactivate_sub(sub["id"])
                logger.info(f"Deactivated expired sub #{sub['id']}")
                try:
                    await bot.send_message(
                        sub["telegram_id"],
                        "\u0412\u0430\u0448\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0438\u0441\u0442\u0435\u043a\u043b\u0430. "
                        "\u0427\u0442\u043e\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c\u0441\u044f VPN, "
                        "\u043f\u0440\u0438\u043e\u0431\u0440\u0435\u0442\u0438\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u0442\u0430\u0440\u0438\u0444.",
                        reply_markup=main_menu(cfg.has_payment, sub["telegram_id"] in cfg.admin_ids),
                    )
                except Exception:
                    pass

            expiring = await db.get_expiring_subs(within_days=3)
            for sub in expiring:
                expired_dt = datetime.fromisoformat(sub["expired_at"])
                days_left = (expired_dt - now).days
                text = (
                    f"\u0412\u0430\u0448\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 {sub['plan_name']} "
                    f"\u0438\u0441\u0442\u0435\u043a\u0430\u0435\u0442 \u0447\u0435\u0440\u0435\u0437 {days_left} \u0434\u043d.\n"
                    f"\u0425\u043e\u0442\u0438\u0442\u0435 \u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c?"
                )
                plan_idx = next((i for i, p in enumerate(cfg.plans) if p.name == sub["plan_name"]), None)
                if plan_idx is not None:
                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="\U0001f504 \u041f\u0440\u043e\u0434\u043b\u0438\u0442\u044c", callback_data=f"renew:{sub['id']}:{plan_idx}")],
                        [InlineKeyboardButton(text="\u274c \u041d\u0435 \u0441\u0435\u0439\u0447\u0430\u0441", callback_data="menu")],
                    ])
                else:
                    markup = main_menu(cfg.has_payment, sub["telegram_id"] in cfg.admin_ids)
                try:
                    await bot.send_message(sub["telegram_id"], text, reply_markup=markup)
                    await db.mark_reminded(sub["id"])
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        await asyncio.sleep(3600)


class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_days = State()


def create_router(cfg: Config, db: Database, xui: XUIManager):
    router = Router()

    yoo = YooKassa(cfg.yookassa_shop_id, cfg.yookassa_secret_key) if cfg.yookassa_shop_id and cfg.yookassa_secret_key else None
    crypto = CryptoBot(cfg.crypto_bot_token) if cfg.crypto_bot_token else None

    @router.message(Command("start"))
    async def cmd_start(message: Message):
        tg_id = message.from_user.id
        user = await db.create_user(tg_id, message.from_user.username)

        welcome = (
            f"\u0414\u043e\u0431\u0440\u043e \u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c, {message.from_user.full_name}!\n\n"
            f"\u042f \u043f\u043e\u043c\u043e\u0433\u0443 \u043f\u0440\u0438\u043e\u0431\u0440\u0435\u0441\u0442\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443 VPN.\n"
            f"\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 \u043d\u0438\u0436\u0435 \u0434\u043b\u044f \u043d\u0430\u0432\u0438\u0433\u0430\u0446\u0438\u0438."
        )
        await message.answer(welcome, reply_markup=main_menu(cfg.has_payment, tg_id in cfg.admin_ids))

        if tg_id in cfg.admin_ids and not user.get("is_admin"):
            await db.conn.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (tg_id,))
            await db.conn.commit()

    @router.callback_query(F.data == "menu")
    async def cb_menu(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text(
            "\u0413\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e:", reply_markup=main_menu(cfg.has_payment, callback.from_user.id in cfg.admin_ids)
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

        text = (
            f"\U0001f4a1 \u0422\u0430\u0440\u0438\u0444: {plan.name}\n"
            f"\U0001f4b5 \u0426\u0435\u043d\u0430: {plan.price} \u0440\u0443\u0431\n"
            f"\U0001f4c5 \u0421\u0440\u043e\u043a: {plan.days} \u0434\u043d\u0435\u0439\n\n"
            f"\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b:"
        )
        await callback.message.edit_text(
            text,
            reply_markup=payment_methods_keyboard(bool(yoo), bool(crypto)),
        )

    @router.callback_query(F.data == "pay:yookassa")
    async def cb_pay_yookassa(callback: CallbackQuery, state: FSMContext, bot: Bot):
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

        if not yoo:
            await callback.message.edit_text(
                "\u041e\u043f\u043b\u0430\u0442\u0430 \u0447\u0435\u0440\u0435\u0437 \u042eKassa \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430.",
                reply_markup=back_button(),
            )
            return

        await callback.message.edit_text("\U000023f3 \u0421\u043e\u0437\u0434\u0430\u0451\u043c \u043f\u043b\u0430\u0442\u0451\u0436...")

        bot_username = cfg.bot_username or "bot"
        payment = await yoo.create_payment(
            amount=plan.price,
            description=plan.name,
            return_url=f"https://t.me/{bot_username}",
        )

        if not payment:
            await callback.message.edit_text(
                "\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u043f\u043b\u0430\u0442\u0435\u0436\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.",
                reply_markup=back_button(),
            )
            return

        user = await db.get_user(tg_id)
        await db.add_transaction(
            user_id=user["id"],
            amount=plan.price,
            currency=cfg.currency,
            payment_system="yookassa",
            payment_id=payment.payment_id,
            plan_name=plan.name,
        )

        await state.update_data(payment_id=payment.payment_id, plan_index=idx, payment_method="yookassa")
        await callback.message.edit_text(
            f"\U0001f4b3 \u0421\u0447\u0451\u0442 \u0441\u043e\u0437\u0434\u0430\u043d!\n\n"
            f"\u0421\u0443\u043c\u043c\u0430: {plan.price} \u0440\u0443\u0431\n"
            f"\u0417\u0430: {plan.name}\n\n"
            f"\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435 \u0434\u043b\u044f \u043e\u043f\u043b\u0430\u0442\u044b:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="\U0001f4b3 \u041e\u043f\u043b\u0430\u0442\u0438\u0442\u044c", url=payment.confirmation_url)],
                    [InlineKeyboardButton(text="\u2705 \u042f \u043e\u043f\u043b\u0430\u0442\u0438\u043b", callback_data=f"check_pay:yoo:{payment.payment_id}:{idx}")],
                    [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="buy")],
                ]
            ),
        )

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
            plan_name=plan.name,
        )

        await state.update_data(payment_id=str(invoice.invoice_id), plan_index=idx, payment_method="crypto")
        await callback.message.edit_text(
            f"\U0001f4b1 \u0421\u0447\u0451\u0442 \u0441\u043e\u0437\u0434\u0430\u043d!\n\n"
            f"\u0421\u0443\u043c\u043c\u0430: {plan.price} \u0440\u0443\u0431\n"
            f"\u0417\u0430: {plan.name}\n\n"
            f"\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435 \u0434\u043b\u044f \u043e\u043f\u043b\u0430\u0442\u044b:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="\U0001f4b1 \u041e\u043f\u043b\u0430\u0442\u0438\u0442\u044c", url=invoice.pay_url)],
                    [InlineKeyboardButton(text="\u2705 \u042f \u043e\u043f\u043b\u0430\u0442\u0438\u043b", callback_data=f"check_pay:crypto:{invoice.invoice_id}:{idx}")],
                    [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="buy")],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("check_pay:"))
    async def cb_check_payment(callback: CallbackQuery, state: FSMContext, bot: Bot):
        parts = callback.data.split(":")
        _, method, pay_id, idx_str = parts
        idx = int(idx_str)
        plan = cfg.plans[idx]
        tg_id = callback.from_user.id

        paid = False
        if method == "yoo" and yoo:
            payment = await yoo.check_payment(pay_id)
            if payment and payment.status == "succeeded":
                paid = True
        elif method == "crypto" and crypto:
            invoice = await crypto.check_invoice(int(pay_id))
            if invoice and invoice.status == "paid":
                paid = True

        if paid:
            await db.conn.execute(
                "UPDATE transactions SET status = 'processing' WHERE payment_id = ? AND status = 'pending'",
                (pay_id,),
            )
            await db.conn.commit()
            cursor2 = await db.conn.execute("SELECT changes()")
            rowcount = (await cursor2.fetchone())[0]
            if rowcount == 0:
                await callback.answer("\u041f\u043b\u0430\u0442\u0435\u0436 \u0443\u0436\u0435 \u043e\u0431\u0440\u0430\u0431\u0430\u0442\u044b\u0432\u0430\u0435\u0442\u0441\u044f", show_alert=True)
                return
            await _process_payment(cfg, db, xui, bot, tg_id, plan, pay_id)
            await db.update_transaction(pay_id, "completed")
            await callback.message.edit_text(
                f"\u2705 \u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430!\n\n"
                f"\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d\u0430.",
                reply_markup=main_menu(cfg.has_payment, callback.from_user.id in cfg.admin_ids),
            )
            await state.clear()
        else:
            await callback.answer(
                "\U000023f3 \u041e\u043f\u043b\u0430\u0442\u0430 \u0435\u0449\u0451 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.",
                show_alert=True,
            )

    @router.callback_query(F.data.startswith("renew:"))
    async def cb_renew(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split(":")
        _, sub_id, plan_idx = parts
        plan = cfg.plans[int(plan_idx)]
        await state.update_data(plan_index=int(plan_idx))
        text = (
            f"\U0001f4a1 \u0422\u0430\u0440\u0438\u0444: {plan.name}\n"
            f"\U0001f4b5 \u0426\u0435\u043d\u0430: {plan.price} \u0440\u0443\u0431\n"
            f"\U0001f4c5 \u0421\u0440\u043e\u043a: {plan.days} \u0434\u043d\u0435\u0439\n\n"
            f"\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b:"
        )
        await callback.message.edit_text(text, reply_markup=payment_methods_keyboard(bool(yoo), bool(crypto)))

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
            sub_url = cfg.make_sub_url(s["uuid"])
            text_parts.append(
                f"\n\u25b6 {s['plan_name']}\n"
                f"\U0001f4c5 \u0414\u043e: {expired_str}\n"
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
            status = "\u2705" if r["is_active"] else "\u274c"
            text += f"\u25b6 {r['username'] or r['telegram_id']} \u2014 {r['plan_name']} \u2014 {status}\n"
        await callback.message.edit_text(text, reply_markup=admin_menu())

    @router.callback_query(F.data == "admin:broadcast")
    async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in cfg.admin_ids:
            return
        await state.set_state(AdminStates.broadcast_text)
        await callback.message.edit_text(
            "\U0001f4e8 \u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0442\u0435\u043a\u0441\u0442 \u0434\u043b\u044f \u0440\u0430\u0441\u0441\u044b\u043b\u043a\u0438:",
            reply_markup=back_button(),
        )

    @router.message(AdminStates.broadcast_text)
    async def msg_admin_broadcast(message: Message, bot: Bot, state: FSMContext):
        if message.from_user.id not in cfg.admin_ids:
            return
        text = message.text.strip()
        if not text:
            await message.answer("\u0422\u0435\u043a\u0441\u0442 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u043c.")
            return
        users = await db.get_all_users()
        sent = 0
        for u in users:
            try:
                await bot.send_message(u["telegram_id"], text)
                sent += 1
            except Exception:
                pass
        await state.clear()
        await message.answer(
            f"\u2705 \u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430. \u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e: {sent}/{len(users)}",
            reply_markup=admin_menu(),
        )

    @router.callback_query(F.data == "admin:manage")
    async def cb_admin_manage(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        subs = await db.get_all_active_subs()
        if not subs:
            await callback.message.edit_text(
                "\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u0434\u043f\u0438\u0441\u043e\u043a.",
                reply_markup=admin_menu(),
            )
            return
        text = "\U0001f4dd \u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438:\n\n"
        for s in subs:
            expired = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else None
            expired_str = expired.strftime("%d.%m.%Y") if expired else "?"
            label = s["username"] or str(s["telegram_id"])
            text += f"\u25b6 {label} \u2014 {s['plan_name']} \u2014 \u0434\u043e {expired_str}\n"
        await callback.message.edit_text(text, reply_markup=admin_subs_list_keyboard(subs))

    @router.callback_query(F.data.startswith("admin_sub:"))
    async def cb_admin_sub_select(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text(
                "\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430.",
                reply_markup=admin_menu(),
            )
            return
        cursor = await db.conn.execute("SELECT telegram_id, username FROM users WHERE id = ?", (sub["user_id"],))
        user_row = await cursor.fetchone()
        user_name = user_row["username"] if user_row else str(sub["user_id"])
        user_tg_id = user_row["telegram_id"] if user_row else sub["user_id"]
        expired = datetime.fromisoformat(sub["expired_at"]) if sub.get("expired_at") else None
        expired_str = expired.strftime("%d.%m.%Y %H:%M") if expired else "?"
        sub_url = cfg.make_sub_url(sub["uuid"])
        text = (
            f"\U0001f464 {user_name} (ID: {user_tg_id})\n"
            f"\U0001f4a1 {sub['plan_name']}\n"
            f"\U0001f4c5 \u0414\u043e: {expired_str}\n"
            f"\U0001f517 <code>{sub_url}</code>"
        )
        await callback.message.edit_text(text, reply_markup=admin_sub_actions_keyboard(sub_id))

    @router.callback_query(F.data.startswith("sub_extend:"))
    async def cb_admin_sub_extend(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        await state.update_data(extend_sub_id=sub_id)
        await state.set_state(AdminStates.extend_days)
        await callback.message.edit_text(
            "\U0001f4c5 \u041d\u0430 \u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0434\u043d\u0435\u0439 \u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c?\n"
            "\u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e:"
        )

    @router.message(AdminStates.extend_days)
    async def msg_admin_extend(message: Message, state: FSMContext):
        if message.from_user.id not in cfg.admin_ids:
            return
        try:
            days = int(message.text.strip())
            if days <= 0:
                raise ValueError
        except ValueError:
            await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043f\u043e\u043b\u043e\u0436\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0435 \u0447\u0438\u0441\u043b\u043e.")
            return

        data = await state.get_data()
        sub_id = data.get("extend_sub_id")
        sub = await db.get_subscription(sub_id)
        if not sub:
            await message.answer("\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430.")
            await state.clear()
            return

        try:
            await xui.update_client_expiry(sub["uuid"], days, cfg.xui_inbound_ids)
        except Exception as e:
            await message.answer(f"\u041e\u0448\u0438\u0431\u043a\u0430 3x-UI: {e}")
            await state.clear()
            return

        await db.update_sub_expiry(sub_id, days)
        await state.clear()
        await message.answer(
            f"\u2705 \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 #{sub_id} \u043f\u0440\u043e\u0434\u043b\u0435\u043d\u0430 \u043d\u0430 {days} \u0434\u043d\u0435\u0439.",
            reply_markup=admin_menu(),
        )

    @router.callback_query(F.data.startswith("sub_delete:"))
    async def cb_admin_sub_delete(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        await callback.message.edit_text(
            "\u274c \u0422\u043e\u0447\u043d\u043e \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443?\n"
            "\u041a\u043b\u0438\u0435\u043d\u0442 \u0431\u0443\u0434\u0435\u0442 \u0443\u0434\u0430\u043b\u0435\u043d \u0438\u0437 3x-UI \u0438 \u0431\u0430\u0437\u044b \u0434\u0430\u043d\u043d\u044b\u0445.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="\u2705 \u0414\u0430, \u0443\u0434\u0430\u043b\u0438\u0442\u044c", callback_data=f"sub_delete_confirm:{sub_id}")],
                [InlineKeyboardButton(text="\u25c0 \u041d\u0435\u0442", callback_data=f"admin_sub:{sub_id}")],
            ]),
        )

    @router.callback_query(F.data.startswith("sub_delete_confirm:"))
    async def cb_admin_sub_delete_confirm(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430.", reply_markup=admin_menu())
            return

        try:
            await xui.delete_client(sub["uuid"], cfg.xui_inbound_ids)
        except Exception as e:
            await callback.message.edit_text(
                f"\u041e\u0448\u0438\u0431\u043a\u0430 3x-UI: {e}",
                reply_markup=admin_menu(),
            )
            return

        await db.deactivate_sub(sub_id)
        await callback.message.edit_text(
            f"\u2705 \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 #{sub_id} \u0443\u0434\u0430\u043b\u0435\u043d\u0430.",
            reply_markup=admin_menu(),
        )

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
            text += f"{i+1}. {p.name} \u2014 {p.price} \u0440\u0443\u0431 \u2014 {p.days} \u0434\u043d.\n"
        text += "\n\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u00ab\u041a\u0443\u043f\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443\u00bb \u0434\u043b\u044f \u043f\u043e\u043a\u0443\u043f\u043a\u0438."
        await message.answer(text, reply_markup=main_menu(cfg.has_payment, message.from_user.id in cfg.admin_ids))

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

    @router.message(StateFilter(None))
    async def fallback(message: Message):
        await message.answer(
            "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 \u043c\u0435\u043d\u044e \u0438\u043b\u0438 /start",
            reply_markup=main_menu(cfg.has_payment, message.from_user.id in cfg.admin_ids),
        )

    return router
