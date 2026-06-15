import logging
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import Config, Plan
from bot.db import Database
from bot.xui import XUIManager
from bot.payments import YooKassa, CryptoBot
from bot.keyboards import main_menu, back_button, plans_keyboard, payment_methods_keyboard, admin_menu, admin_subs_list_keyboard, admin_sub_actions_keyboard, device_count_keyboard, edit_device_keyboard, device_mgmt_keyboard, help_keyboard

logger = logging.getLogger(__name__)


async def _nav(callback: CallbackQuery, text: str, markup=None):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.bot.send_message(callback.from_user.id, text, reply_markup=markup)


def calc_total_price(plan: Plan, device_count: int) -> float:
    return plan.price + max(0, device_count - plan.base_devices) * plan.extra_device_price


async def _process_payment(
    cfg: Config, db: Database, xui: XUIManager, bot: Bot,
    tg_id: int, plan: Plan, payment_id: str, device_count: int = 3,
):
    user = await db.get_user(tg_id)
    if not user:
        return

    existing = await db.get_active_sub_by_user_and_plan(user["id"], plan.name)
    total_price = calc_total_price(plan, device_count)

    if existing:
        try:
            await xui.update_client_expiry(existing["uuid"], f"tg_{tg_id}", plan.days, device_count)
        except Exception as e:
            logger.error(f"3x-UI extend error: {e}")
            await bot.send_message(tg_id, f"Ошибка продления: {e}")
            return
        await db.extend_expiry(existing["id"], plan.days)
        await db.update_sub_device_count(existing["id"], device_count)
        client_uuid = existing["uuid"]
        is_renewal = True
    else:
        try:
            client_uuid, client = await xui.create_client(
                inbound_ids=cfg.xui_inbound_ids,
                email=f"tg_{tg_id}",
                days=plan.days,
                traffic_gb=plan.traffic_gb,
                device_count=device_count,
            )
        except Exception as e:
            logger.error(f"3x-UI create client error: {e}")
            await bot.send_message(tg_id, f"Ошибка создания клиента: {e}")
            return
        await db.add_subscription(
            user_id=user["id"],
            plan_name=plan.name,
            uuid_str=client_uuid,
            inbound_id=cfg.xui_inbound_ids[0],
            days=plan.days,
            traffic_gb=plan.traffic_gb,
            device_count=device_count,
        )
        is_renewal = False

    sub_url = cfg.make_sub_url(client_uuid)
    if is_renewal:
        msg = (
            f"✅ Подписка продлена!\n\n"
            f"💡 Тариф: {plan.days} дней | Безлимит ♾\n"
            f"📱 Устройств: {device_count}\n"
            f"💵 Сумма: {total_price} руб\n"
            f"📅 Срок: +{plan.days} дней\n\n"
            f"🔗 Ссылка на подписку:\n"
            f"<code>{sub_url}</code>"
        )
    else:
        msg = (
            f"✅ Подписка активирована!\n\n"
            f"💡 Тариф: {plan.days} дней | Безлимит ♾\n"
            f"📱 Устройств: {device_count}\n"
            f"💵 Сумма: {total_price} руб\n"
            f"📅 Срок: {plan.days} дней\n\n"
            f"🔗 Ссылка на подписку:\n"
            f"<code>{sub_url}</code>\n\n"
            f"Импортируйте эту ссылку в вашем VPN-клиенте."
        )
    try:
        await bot.send_message(tg_id, msg)
    except Exception as e:
        logger.error(f"Failed to send sub URL to {tg_id}: {e}")

    label = "Новая подписка" if not is_renewal else "Продление подписки"
    for admin_id in cfg.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 {label}!\n"
                f"👤 {user['username'] or tg_id}\n"
                f"💡 {plan.days} дней | Безлимит ♾ | {total_price} руб\n"
                f"📱 Устройств: {device_count}\n"
                f"🔗 {sub_url}",
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
                            "✅ Оплата подтверждена! Подписка активирована.",
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
            await sync_subscriptions(cfg, db, xui)
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
                        "Ваша подписка истекла. "
                        "Чтобы продолжить пользоваться VPN, "
                        "приобретите новый тариф.",
                        reply_markup=main_menu(cfg.has_payment, sub["telegram_id"] in cfg.admin_ids),
                    )
                except Exception:
                    pass

            expiring = await db.get_expiring_subs(within_days=3)
            for sub in expiring:
                expired_dt = datetime.fromisoformat(sub["expired_at"])
                days_left = (expired_dt - now).days
                text = (
                    f"Ваша подписка {sub['plan_name']} "
                    f"истекает через {days_left} дн.\n"
                    f"Хотите продлить?"
                )
                plan_idx = next((i for i, p in enumerate(cfg.plans) if p.name == sub["plan_name"]), None)
                if plan_idx is not None:
                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Продлить", callback_data=f"renew:{sub['id']}:{plan_idx}")],
                        [InlineKeyboardButton(text="❌ Не сейчас", callback_data="menu")],
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


async def sync_subscriptions(cfg: Config, db: Database, xui: XUIManager):
    """Deactivate subs in DB whose clients no longer exist in 3x-ui."""
    try:
        subs = await db.get_all_active_subs()
        if not subs:
            return

        inbounds = await xui.get_inbounds()
        uuids_in_3xui = set()
        for ib in inbounds:
            for c in (ib.settings.clients or []):
                if c.id:
                    uuids_in_3xui.add(str(c.id))

        deactivated = 0
        for sub in subs:
            if sub["uuid"] not in uuids_in_3xui:
                await db.deactivate_sub(sub["id"])
                deactivated += 1
                logger.info(f"Synced: deactivated sub #{sub['id']} (not found in 3x-ui)")

        if deactivated:
            logger.info(f"Sync complete: {deactivated} subscriptions deactivated")
    except Exception as e:
        logger.error(f"Sync error: {e}")


class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_days = State()
    grant_user_id = State()
    grant_plan = State()


def create_router(cfg: Config, db: Database, xui: XUIManager):
    router = Router()

    yoo = YooKassa(cfg.yookassa_shop_id, cfg.yookassa_secret_key) if cfg.yookassa_shop_id and cfg.yookassa_secret_key else None
    crypto = CryptoBot(cfg.crypto_bot_token) if cfg.crypto_bot_token else None

    @router.message(Command("start"))
    async def cmd_start(message: Message):
        tg_id = message.from_user.id
        user = await db.create_user(tg_id, message.from_user.username)

        welcome = (
            f"Добро пожаловать, {message.from_user.full_name}!\n\n"
            f"Я помогу приобрести подписку VPN.\n"
            f"Используйте кнопки ниже для навигации."
        )
        await message.answer(welcome, reply_markup=main_menu(cfg.has_payment, tg_id in cfg.admin_ids))

        if tg_id in cfg.admin_ids and not user.get("is_admin"):
            await db.conn.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (tg_id,))
            await db.conn.commit()

    @router.callback_query(F.data == "menu")
    async def cb_menu(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await _nav(callback, "Главное меню:", main_menu(cfg.has_payment, callback.from_user.id in cfg.admin_ids))

    @router.callback_query(F.data == "help")
    async def cb_help(callback: CallbackQuery):
        text = (
            "💬 Помощь\n\n"
            "Выберите ваше устройство для инструкции по установке Happ (Hiddify):"
        )
        await _nav(callback, text, help_keyboard())

    @router.callback_query(F.data.startswith("help_platform:"))
    async def cb_help_platform(callback: CallbackQuery):
        platform = callback.data.split(":")[1]
        guides = {
            "android": (
                "📱 **Android — Hiddify (Happ)**\n\n"
                "1. Скачайте Hiddify из Google Play или с оф. сайта hiddify.com\n"
                "2. Откройте приложение\n"
                "3. Нажмите **+** → **Добавить из буфера**\n"
                "4. Скопируйте ссылку подписки из профиля бота\n"
                "5. Приложение само подставит ссылку — нажмите **Добавить**\n"
                "6. Выберите профиль и нажмите **Подключиться**"
            ),
            "ios": (
                "🍎 **iOS / iPadOS — Hiddify (Happ)**\n\n"
                "1. Скачайте Hiddify из App Store\n"
                "2. Откройте приложение\n"
                "3. Нажмите **+** → **Импортировать из буфера**\n"
                "4. Скопируйте ссылку подписки из профиля бота\n"
                "5. Приложение подставит данные — нажмите **Добавить**\n"
                "6. Включите тумблер для подключения"
            ),
            "windows": (
                "💻 **Windows — Hiddify (Happ)**\n\n"
                "1. Скачайте Hiddify с hiddify.com (Windows версия)\n"
                "2. Установите и запустите\n"
                "3. Нажмите **+** → **Добавить из буфера обмена**\n"
                "4. Скопируйте ссылку подписки из профиля бота\n"
                "5. Нажмите **Добавить**\n"
                "6. Включите переключатель для подключения"
            ),
            "macos": (
                "🍏 **MacOS — Hiddify (Happ)**\n\n"
                "1. Скачайте Hiddify для MacOS с hiddify.com\n"
                "2. Установите и запустите\n"
                "3. Нажмите **+** → **Добавить из буфера обмена**\n"
                "4. Скопируйте ссылку подписки из профиля бота\n"
                "5. Нажмите **Добавить**\n"
                "6. Включите переключатель для подключения"
            ),
        }
        text = guides.get(platform, "Инструкция для этой платформы пока не добавлена.")
        await _nav(callback, text, back_button("help"))

    @router.callback_query(F.data == "buy")
    async def cb_buy(callback: CallbackQuery):
        if not cfg.plans:
            await _nav(callback, "Нет доступных тарифов.", back_button())
            return
        await _nav(callback, "💎 Выберите тариф:", plans_keyboard(cfg.plans, "plan"))

    @router.callback_query(F.data.startswith("plan:"))
    async def cb_select_plan(callback: CallbackQuery, state: FSMContext):
        idx = int(callback.data.split(":")[1])
        plan = cfg.plans[idx]
        await state.update_data(plan_index=idx)

        text = (
            f"💡 Тариф: {plan.days} дней | Безлимит ♾\n"
            f"💰 Базовая цена: {plan.price} руб (до {plan.base_devices} устройств)\n"
            f"➕ Доп. устройство: +{plan.extra_device_price} руб/шт\n\n"
            f"Выберите количество устройств:"
        )
        await callback.message.edit_text(
            text,
            reply_markup=device_count_keyboard(),
        )

    @router.callback_query(F.data.startswith("device:"))
    async def cb_select_device(callback: CallbackQuery, state: FSMContext):
        device_count = int(callback.data.split(":")[1])
        data = await state.get_data()
        idx = data.get("plan_index")
        if idx is None:
            await callback.message.edit_text(
                "Ошибка: выберите тариф заново.",
                reply_markup=back_button(),
            )
            return
        plan = cfg.plans[idx]
        total = calc_total_price(plan, device_count)
        await state.update_data(device_count=device_count, total_price=total)

        text = (
            f"💡 Тариф: {plan.days} дней | Безлимит ♾\n"
            f"📱 Устройств: {device_count}\n"
            f"💵 Сумма: {total} руб\n\n"
            f"Выберите способ оплаты:"
        )
        await callback.message.edit_text(
            text,
            reply_markup=payment_methods_keyboard(bool(yoo), bool(crypto)),
        )

    @router.callback_query(F.data == "pay:yookassa")
    async def cb_pay_yookassa(callback: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        idx = data.get("plan_index")
        device_count = data.get("device_count", 3)
        if idx is None:
            await callback.message.edit_text(
                "Ошибка: выберите тариф заново.",
                reply_markup=back_button(),
            )
            return
        plan = cfg.plans[idx]
        total_price = calc_total_price(plan, device_count)
        tg_id = callback.from_user.id

        if not yoo:
            await callback.message.edit_text(
                "Оплата через ЮKassa недоступна.",
                reply_markup=back_button(),
            )
            return

        await callback.message.edit_text("⏳ Создаём платёж...")

        bot_username = cfg.bot_username or "bot"
        payment = await yoo.create_payment(
            amount=total_price,
            description=f"{plan.name} ({device_count} уст.)",
            return_url=f"https://t.me/{bot_username}",
        )

        if not payment:
            await callback.message.edit_text(
                "Ошибка создания платежа. Попробуйте позже.",
                reply_markup=back_button(),
            )
            return

        user = await db.get_user(tg_id)
        await db.add_transaction(
            user_id=user["id"],
            amount=total_price,
            currency=cfg.currency,
            payment_system="yookassa",
            payment_id=payment.payment_id,
            plan_name=plan.name,
        )

        await state.update_data(payment_id=payment.payment_id, plan_index=idx, payment_method="yookassa")
        await callback.message.edit_text(
            f"💳 Счёт создан!\n\n"
            f"Сумма: {total_price} руб\n"
            f"За: {plan.name} ({device_count} уст.)\n\n"
            f"Нажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation_url)],
                    [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_pay:yoo:{payment.payment_id}:{idx}")],
                    [InlineKeyboardButton(text="◀ Назад", callback_data="buy")],
                ]
            ),
        )

    @router.callback_query(F.data == "pay:crypto")
    async def cb_pay_crypto(callback: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        idx = data.get("plan_index")
        device_count = data.get("device_count", 3)
        if idx is None:
            await callback.message.edit_text(
                "Ошибка: выберите тариф заново.",
                reply_markup=back_button(),
            )
            return
        plan = cfg.plans[idx]
        total_price = calc_total_price(plan, device_count)
        tg_id = callback.from_user.id

        if not crypto:
            await callback.message.edit_text(
                "Оплата через CryptoBot недоступна.",
                reply_markup=back_button(),
            )
            return

        await callback.message.edit_text("⏳ Создаём счёт...")

        invoice = await crypto.create_invoice(
            amount=total_price,
            description=f"{plan.name} ({device_count} уст.) | @{callback.from_user.username or tg_id}",
        )

        if not invoice:
            await callback.message.edit_text(
                "Ошибка создания счёта. Попробуйте позже.",
                reply_markup=back_button(),
            )
            return

        user = await db.get_user(tg_id)
        await db.add_transaction(
            user_id=user["id"],
            amount=total_price,
            currency=cfg.currency,
            payment_system="cryptobot",
            payment_id=str(invoice.invoice_id),
            plan_name=plan.name,
        )

        await state.update_data(payment_id=str(invoice.invoice_id), plan_index=idx, payment_method="crypto")
        await callback.message.edit_text(
            f"💱 Счёт создан!\n\n"
            f"Сумма: {total_price} руб\n"
            f"За: {plan.name} ({device_count} уст.)\n\n"
            f"Нажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💱 Оплатить", url=invoice.pay_url)],
                    [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_pay:crypto:{invoice.invoice_id}:{idx}")],
                    [InlineKeyboardButton(text="◀ Назад", callback_data="buy")],
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

        data = await state.get_data()
        device_count = data.get("device_count", 3)

        if paid:
            await db.conn.execute(
                "UPDATE transactions SET status = 'processing' WHERE payment_id = ? AND status = 'pending'",
                (pay_id,),
            )
            await db.conn.commit()
            cursor2 = await db.conn.execute("SELECT changes()")
            rowcount = (await cursor2.fetchone())[0]
            if rowcount == 0:
                await callback.answer("Платеж уже обрабатывается", show_alert=True)
                return
            await _process_payment(cfg, db, xui, bot, tg_id, plan, pay_id, device_count)
            await db.update_transaction(pay_id, "completed")
            await callback.message.edit_text(
                f"✅ Оплата подтверждена!\n\n"
                f"Подписка активирована.",
                reply_markup=main_menu(cfg.has_payment, callback.from_user.id in cfg.admin_ids),
            )
            await state.clear()
        else:
            await callback.answer(
                "⏳ Оплата ещё не найдена. Попробуйте позже.",
                show_alert=True,
            )

    @router.callback_query(F.data.startswith("renew:"))
    async def cb_renew(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split(":")
        _, sub_id, plan_idx = parts
        plan = cfg.plans[int(plan_idx)]
        sub = await db.get_subscription(int(sub_id))
        current_devices = sub["device_count"] if sub else 3
        await state.update_data(plan_index=int(plan_idx))
        text = (
            f"💡 Тариф: {plan.days} дней | Безлимит ♾\n"
            f"💰 Базовая цена: {plan.price} руб (до {plan.base_devices} устройств)\n"
            f"➕ Доп. устройство: +{plan.extra_device_price} руб/шт\n\n"
            f"Выберите количество устройств:"
        )
        await callback.message.edit_text(text, reply_markup=device_count_keyboard(current_devices))

    @router.callback_query(F.data == "my_subs")
    async def cb_my_subs(callback: CallbackQuery):
        tg_id = callback.from_user.id
        user = await db.get_user(tg_id)
        if not user:
            await _nav(callback, "Сначала напишите /start", back_button())
            return

        subs = await db.get_user_subscriptions(user["id"])
        if not subs:
            await _nav(callback, "У вас нет активных подписок.", plans_keyboard(cfg.plans, "plan"))
            return

        text_parts = ["📋 Ваши подписки:\n"]
        for s in subs:
            expired = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else None
            expired_str = expired.strftime("%d.%m.%Y %H:%M") if expired else "бессрочно"
            sub_url = cfg.make_sub_url(s["uuid"])
            devices = s.get("device_count", 3)
            text_parts.append(
                f"\n▶ {s['plan_name']}\n"
                f"📅 До: {expired_str}\n"
                f"📱 Устройств: {devices}\n"
                f"🔗 <code>{sub_url}</code>\n"
            )
        builder = InlineKeyboardBuilder()
        builder.button(text="📱 Изменить устройства", callback_data="edit_devices")
        builder.button(text="◀ Назад", callback_data="menu")
        builder.adjust(1)
        await _nav(callback, "\n".join(text_parts), builder.as_markup())

    @router.callback_query(F.data == "edit_devices")
    async def cb_edit_devices(callback: CallbackQuery):
        tg_id = callback.from_user.id
        user = await db.get_user(tg_id)
        if not user:
            await callback.message.edit_text("Сначала напишите /start", reply_markup=back_button())
            return
        subs = await db.get_user_subscriptions(user["id"])
        if not subs:
            await callback.message.edit_text("Нет активных подписок.", reply_markup=back_button())
            return
        builder = InlineKeyboardBuilder()
        for s in subs:
            label = f"{s['plan_name']} — {s.get('device_count', 3)} шт"
            builder.button(text=label, callback_data=f"edit_dev_sub:{s['id']}")
        builder.button(text="◀ Назад", callback_data="my_subs")
        builder.adjust(1)
        await callback.message.edit_text("📱 Выберите подписку для изменения:", reply_markup=builder.as_markup())

    @router.callback_query(F.data.startswith("edit_dev_sub:"))
    async def cb_edit_dev_sub(callback: CallbackQuery):
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=back_button())
            return
        current = sub.get("device_count", 3)
        email = f"tg_{callback.from_user.id}"
        ips = await xui.get_client_ips(email)
        ips_str = ", ".join(ips) if ips else "нет"
        text = (
            f"💡 {sub['plan_name']}\n"
            f"📱 Лимит устройств: {current}\n"
            f"🔌 Подключено IP: {ips_str}\n"
        )
        await callback.message.edit_text(text, reply_markup=device_mgmt_keyboard(sub_id, current))

    @router.callback_query(F.data.startswith("edit_dev_count:"))
    async def cb_edit_dev_count(callback: CallbackQuery):
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=back_button())
            return
        current = sub.get("device_count", 3)
        await callback.message.edit_text(
            f"💡 {sub['plan_name']}\n"
            f"📱 Текущее количество устройств: {current}\n\n"
            f"Выберите новое количество:",
            reply_markup=edit_device_keyboard(sub_id, current),
        )

    @router.callback_query(F.data.startswith("edit_dev_reset:"))
    async def cb_edit_dev_reset(callback: CallbackQuery):
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=back_button())
            return
        email = f"tg_{callback.from_user.id}"
        try:
            await xui.reset_client_ips(email)
        except Exception as e:
            await callback.message.edit_text(f"Ошибка: {e}", reply_markup=back_button())
            return
        await callback.message.edit_text(
            "🔌 Все подключения сброшены.",
            reply_markup=device_mgmt_keyboard(sub_id, sub.get("device_count", 3)),
        )

    @router.callback_query(F.data.startswith("devedit:"))
    async def cb_confirm_dev_edit(callback: CallbackQuery, bot: Bot):
        parts = callback.data.split(":")
        sub_id = int(parts[1])
        new_count = int(parts[2])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=back_button())
            return
        await db.update_sub_device_count(sub_id, new_count)
        try:
            remaining_days = max(0, (datetime.fromisoformat(sub["expired_at"]) - datetime.now()).days) if sub.get("expired_at") else 0
            await xui.update_client_expiry(sub["uuid"], f"tg_{callback.from_user.id}", remaining_days, new_count)
        except Exception as e:
            logger.error(f"3x-UI device count update error: {e}")
            await callback.message.edit_text(
                f"Ошибка обновления в панели: {e}",
                reply_markup=back_button(),
            )
            return
        await callback.message.edit_text(
            f"✅ Количество устройств изменено на {new_count}.",
            reply_markup=device_mgmt_keyboard(sub_id, new_count),
        )

    @router.callback_query(F.data.startswith("edit_dev_upgrade:"))
    async def cb_edit_dev_upgrade(callback: CallbackQuery):
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=back_button())
            return
        current = sub.get("device_count", 3)
        text = (
            f"📈 Увеличение лимита устройств\n\n"
            f"Текущий лимит: {current}\n"
            f"➕ Стоимость доп. устройства: 50 руб/шт\n\n"
            f"Выберите новое количество устройств:"
        )
        await callback.message.edit_text(text, reply_markup=device_count_keyboard(current, f"upgrade_dev:{sub_id}", f"edit_dev_sub:{sub_id}"))

    @router.callback_query(F.data.startswith("upgrade_dev:"))
    async def cb_upgrade_dev_confirm(callback: CallbackQuery, bot: Bot):
        parts = callback.data.split(":")
        sub_id = int(parts[1])
        new_count = int(parts[2])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=back_button())
            return
        current = sub.get("device_count", 3)
        if new_count <= current:
            await callback.answer("Новое количество должно быть больше текущего.", show_alert=True)
            return
        extra = new_count - current
        plan = next((p for p in cfg.plans if p.name == sub["plan_name"]), None)
        plan_price_extra = plan.extra_device_price if plan else 50
        price = extra * plan_price_extra

        if cfg.has_payment:
            await callback.message.edit_text(
                f"📈 Увеличение лимита\n\n"
                f"Сейчас: {current} устройств\n"
                f"Новый лимит: {new_count} устройств\n"
                f"➕ Дополнительно: +{extra} шт\n"
                f"💵 Сумма: {price} руб\n\n"
                f"Оплата в разработке. Обратитесь к администратору.",
                reply_markup=back_button(),
            )
            return

        tg_id = callback.from_user.id
        await db.update_sub_device_count(sub_id, new_count)
        try:
            remaining_days = max(0, (datetime.fromisoformat(sub["expired_at"]) - datetime.now()).days) if sub.get("expired_at") else 0
            await xui.update_client_expiry(sub["uuid"], f"tg_{tg_id}", remaining_days, new_count)
        except Exception as e:
            await callback.message.edit_text(f"Ошибка 3x-UI: {e}", reply_markup=back_button())
            return
        await callback.message.edit_text(
            f"✅ Лимит увеличен до {new_count} устройств.",
            reply_markup=device_mgmt_keyboard(sub_id, new_count),
        )

    @router.callback_query(F.data == "admin")
    async def cb_admin(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await _nav(callback, "🛡 Админ-панель:", admin_menu())

    @router.callback_query(F.data == "admin:users")
    async def cb_admin_users(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        users = await db.get_all_users()
        text = f"👥 Пользователи ({len(users)}):\n\n"
        for u in users[:50]:
            text += f"▶ {u['username'] or 'no username'} (ID: {u['telegram_id']})\n"
        await callback.message.edit_text(text, reply_markup=admin_menu())

    @router.callback_query(F.data == "admin:subs")
    async def cb_admin_subs(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        cursor = await db.conn.execute(
            "SELECT s.*, u.telegram_id, u.username FROM subscriptions s JOIN users u ON s.user_id = u.id WHERE s.is_active = 1 ORDER BY s.created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        if not rows:
            await callback.message.edit_text("Нет активных подписок.", reply_markup=admin_menu())
            return
        text = "📋 Активные подписки:\n\n"
        for r in rows:
            text += f"▶ {r['username'] or r['telegram_id']} — {r['plan_name']}\n"
        await callback.message.edit_text(text, reply_markup=admin_menu())

    @router.callback_query(F.data == "admin:broadcast")
    async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in cfg.admin_ids:
            return
        await state.set_state(AdminStates.broadcast_text)
        await callback.message.edit_text(
            "📨 Введите текст для рассылки:",
            reply_markup=back_button(),
        )

    @router.message(AdminStates.broadcast_text)
    async def msg_admin_broadcast(message: Message, bot: Bot, state: FSMContext):
        if message.from_user.id not in cfg.admin_ids:
            return
        text = message.text.strip()
        if not text:
            await message.answer("Текст не может быть пустым.")
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
            f"✅ Рассылка завершена. Отправлено: {sent}/{len(users)}",
            reply_markup=admin_menu(),
        )

    @router.callback_query(F.data == "admin:grant")
    async def cb_admin_grant(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in cfg.admin_ids:
            return
        await state.set_state(AdminStates.grant_user_id)
        await callback.message.edit_text(
            "👤 Введите Telegram ID пользователя:",
            reply_markup=back_button(),
        )

    @router.message(AdminStates.grant_user_id)
    async def msg_admin_grant_user(message: Message, state: FSMContext):
        if message.from_user.id not in cfg.admin_ids:
            return
        try:
            tg_id = int(message.text.strip())
        except ValueError:
            await message.answer("Неверный ID. Введите число.")
            return
        user = await db.get_user(tg_id)
        if not user:
            user = await db.create_user(tg_id, None)
        await state.update_data(grant_tg_id=tg_id)
        await state.set_state(AdminStates.grant_plan)
        await message.answer(
            f"✅ Пользователь найден (ID: {tg_id}).\n"
            f"Выберите тариф:",
            reply_markup=plans_keyboard(cfg.plans, "grant_plan"),
        )

    @router.callback_query(F.data.startswith("grant_plan:"))
    async def cb_admin_grant_plan(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in cfg.admin_ids:
            return
        idx = int(callback.data.split(":")[1])
        plan = cfg.plans[idx]
        await state.update_data(grant_plan_index=idx)
        text = (
            f"💡 Тариф: {plan.days} дней | Безлимит ♾\n"
            f"💰 Базовая цена: {plan.price} руб (до {plan.base_devices} устройств)\n"
            f"➕ Доп. устройство: +{plan.extra_device_price} руб/шт\n\n"
            f"Выберите количество устройств:"
        )
        await callback.message.edit_text(
            text,
            reply_markup=device_count_keyboard(),
        )

    @router.callback_query(F.data.startswith("grant_device:"))
    async def cb_admin_grant_device(callback: CallbackQuery, state: FSMContext, bot: Bot):
        if callback.from_user.id not in cfg.admin_ids:
            return
        device_count = int(callback.data.split(":")[1])
        data = await state.get_data()
        idx = data.get("grant_plan_index")
        if idx is None:
            await callback.message.edit_text("Ошибка: выберите тариф заново.", reply_markup=admin_menu())
            await state.clear()
            return
        plan = cfg.plans[idx]
        tg_id = data["grant_tg_id"]

        await _process_payment(cfg, db, xui, bot, tg_id, plan, f"grant_{tg_id}_{idx}", device_count)
        await state.clear()
        total_price = calc_total_price(plan, device_count)
        await callback.message.edit_text(
            f"✅ Подписка выдана!\n"
            f"💡 {plan.days} дней | Безлимит ♾\n"
            f"📱 Устройств: {device_count}\n"
            f"💵 Сумма: {total_price} руб\n"
            f"👤 Пользователь: {tg_id}",
            reply_markup=admin_menu(),
        )

    @router.callback_query(F.data == "admin:manage")
    async def cb_admin_manage(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        subs = await db.get_all_active_subs()
        if not subs:
            await callback.message.edit_text(
                "Нет активных подписок.",
                reply_markup=admin_menu(),
            )
            return
        text = "📝 Активные подписки:\n\n"
        for s in subs:
            expired = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else None
            expired_str = expired.strftime("%d.%m.%Y") if expired else "?"
            label = s["username"] or str(s["telegram_id"])
            text += f"▶ {label} — {s['plan_name']} — до {expired_str}\n"
        await callback.message.edit_text(text, reply_markup=admin_subs_list_keyboard(subs))

    @router.callback_query(F.data.startswith("admin_sub:"))
    async def cb_admin_sub_select(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text(
                "Подписка не найдена.",
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
        devices = sub.get("device_count", 3)
        text = (
            f"👤 {user_name} (ID: {user_tg_id})\n"
            f"💡 {sub['plan_name']}\n"
            f"📅 До: {expired_str}\n"
            f"📱 Устройств: {devices}\n"
            f"🔗 <code>{sub_url}</code>"
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
            "📅 На сколько дней продлить?\n"
            "Напишите число:"
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
            await message.answer("Введите положительное число.")
            return

        data = await state.get_data()
        sub_id = data.get("extend_sub_id")
        sub = await db.get_subscription(sub_id)
        if not sub:
            await message.answer("Подписка не найдена.")
            await state.clear()
            return

        try:
            cursor = await db.conn.execute("SELECT telegram_id FROM users WHERE id = ?", (sub["user_id"],))
            user_row = await cursor.fetchone()
            email = f"tg_{user_row['telegram_id']}" if user_row else f"tg_{sub['user_id']}"
            await xui.update_client_expiry(sub["uuid"], email, days)
        except Exception as e:
            await message.answer(f"Ошибка 3x-UI: {e}")
            await state.clear()
            return

        await db.update_sub_expiry(sub_id, days)
        await state.clear()
        await message.answer(
            f"✅ Подписка #{sub_id} продлена на {days} дней.",
            reply_markup=admin_menu(),
        )

    @router.callback_query(F.data.startswith("sub_delete:"))
    async def cb_admin_sub_delete(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        await callback.message.edit_text(
            "❌ Точно удалить подписку?\n"
            "Клиент будет удален из 3x-UI и базы данных.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"sub_delete_confirm:{sub_id}")],
                [InlineKeyboardButton(text="◀ Нет", callback_data=f"admin_sub:{sub_id}")],
            ]),
        )

    @router.callback_query(F.data.startswith("sub_delete_confirm:"))
    async def cb_admin_sub_delete_confirm(callback: CallbackQuery):
        if callback.from_user.id not in cfg.admin_ids:
            return
        sub_id = int(callback.data.split(":")[1])
        sub = await db.get_subscription(sub_id)
        if not sub:
            await callback.message.edit_text("Подписка не найдена.", reply_markup=admin_menu())
            return

        try:
            await xui.delete_client(sub["uuid"], cfg.xui_inbound_ids)
        except Exception as e:
            await callback.message.edit_text(
                f"Ошибка 3x-UI: {e}",
                reply_markup=admin_menu(),
            )
            return

        await db.deactivate_sub(sub_id)
        await callback.message.edit_text(
            f"✅ Подписка #{sub_id} удалена.",
            reply_markup=admin_menu(),
        )

    @router.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id not in cfg.admin_ids:
            await message.answer("Нет доступа")
            return
        await message.answer("🛡 Админ-панель:", reply_markup=admin_menu())

    @router.message(Command("my"))
    async def cmd_my(message: Message):
        tg_id = message.from_user.id
        user = await db.get_user(tg_id)
        if not user:
            await message.answer("Сначала напишите /start")
            return
        subs = await db.get_user_subscriptions(user["id"])
        if not subs:
            await message.answer(
                "У вас нет активных подписок.",
                reply_markup=plans_keyboard(cfg.plans, "plan"),
            )
            return
        for s in subs:
            expired = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else None
            expired_str = expired.strftime("%d.%m.%Y %H:%M") if expired else "бессрочно"
            sub_url = cfg.make_sub_url(s["uuid"])
            devices = s.get("device_count", 3)
            await message.answer(
                f"▶ {s['plan_name']}\n"
                f"📅 До: {expired_str}\n"
                f"📱 Устройств: {devices}\n"
                f"🔗 <code>{sub_url}</code>"
            )

    @router.message(Command("plans"))
    async def cmd_plans(message: Message):
        if not cfg.plans:
            await message.answer("Нет доступных тарифов.")
            return
        text = "💎 Доступные тарифы:\n\n"
        for i, p in enumerate(cfg.plans):
            text += f"{i+1}. {p.name} — {p.price} руб — {p.days} дн.\n"
        text += "\nИспользуйте кнопку «Купить подписку» для покупки."
        await message.answer(text, reply_markup=main_menu(cfg.has_payment, message.from_user.id in cfg.admin_ids))

    @router.message(Command("broadcast"))
    async def cmd_broadcast(message: Message, bot: Bot):
        if message.from_user.id not in cfg.admin_ids:
            return
        text = message.text.replace("/broadcast", "", 1).strip()
        if not text:
            await message.answer("Укажите текст: /broadcast Сообщение")
            return
        users = await db.get_all_users()
        sent = 0
        for u in users:
            try:
                await bot.send_message(u["telegram_id"], text)
                sent += 1
            except Exception:
                pass
        await message.answer(f"Рассылка завершена. Отправлено: {sent}/{len(users)}")

    @router.message(StateFilter(None))
    async def fallback(message: Message):
        await message.answer(
            "Используйте кнопки меню или /start",
            reply_markup=main_menu(cfg.has_payment, message.from_user.id in cfg.admin_ids),
        )

    return router
