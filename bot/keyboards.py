from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


PAYMENT_METHOD_LABELS = {
    2: "⚡ СБП",
    3: "🏦 ЕРИП",
    11: "💳 Карта",
    12: "🌍 Международная",
    13: "₿ Крипта",
}


def main_menu(has_payment: bool = True, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Купить подписку", callback_data="buy")
    builder.button(text="👤 Профиль", callback_data="my_subs")
    builder.button(text="❓ Помощь", callback_data="help")
    builder.button(text="ℹ️ О сервисе", callback_data="about")
    if is_admin:
        builder.button(text="🛡 Админка", callback_data="admin")
        builder.adjust(1, 2, 1, 1)
    else:
        builder.adjust(1, 2, 1)
    return builder.as_markup()


def back_button(back_cb: str = "menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀ Назад", callback_data=back_cb)
    return builder.as_markup()


def about_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔒 Политика конфиденциальности",
        url="https://telegra.ph/Politika-konfidencialnosti-08-19-119",
    )
    builder.button(
        text="📄 Пользовательское соглашение",
        url="https://telegra.ph/Polzovatelskoe-soglashenie-08-19-43",
    )
    builder.button(text="🆘 Поддержка", callback_data="support")
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def help_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Android", callback_data="help_platform:android")
    builder.button(text="🍎 iOS", callback_data="help_platform:ios")
    builder.button(text="💻 Desktop", callback_data="help_platform:desktop")
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(2)
    return builder.as_markup()


def plans_keyboard(plans: list, prefix: str = "plan") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, plan in enumerate(plans):
        builder.button(
            text=f"{plan.days} дн | Безлимит | {plan.price} ₽",
            callback_data=f"{prefix}:{i}",
        )
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def device_count_keyboard(current: int = 3, prefix: str = "device", back_cb: str = "buy", confirm_cb: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = 3 if confirm_cb else 1
    for i in range(start, 11):
        mark = " ✅" if i == current else ""
        builder.button(text=f"{i}{mark}", callback_data=f"{prefix}:{i}")
    if confirm_cb:
        builder.button(text="💳 Перейти к оплате", callback_data=confirm_cb)
    builder.button(text="◀ Назад", callback_data=back_cb)
    if confirm_cb:
        builder.adjust(4, 4, 1, 1)
    else:
        builder.adjust(5)
    return builder.as_markup()


def _device_label(dev: dict) -> str:
    model = dev.get("deviceModel") or ""
    os_name = dev.get("deviceOs") or dev.get("osVersion") or ""
    label = " / ".join(p.strip() for p in (os_name, model) if p.strip())
    if not label:
        ua = dev.get("userAgent") or ""
        label = ua[:24]
    return label or "Неизвестное устройство"


def device_mgmt_keyboard(sub_id: int, current: int = 3, devices: list[dict] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for dev in devices or []:
        device_id = dev.get("id")
        if device_id is None:
            continue
        builder.button(
            text=f"📱 {_device_label(dev)}  ✖",
            callback_data=f"dsc_hwid:{sub_id}:{device_id}",
        )
    builder.button(text="🗑 Очистить все устройства", callback_data=f"clr_hwid:{sub_id}")
    builder.button(text="📊 Изменить лимит", callback_data=f"edit_dev_upgrade:{sub_id}")
    builder.button(text="◀ Назад", callback_data="my_subs")
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(platega_methods: list[int], has_crypto: bool, back_cb: str = "buy") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m in platega_methods:
        label = PAYMENT_METHOD_LABELS.get(m, f"Оплата ({m})")
        builder.button(text=label, callback_data=f"pay:platega:{m}")
    if has_crypto:
        builder.button(text="💱 CryptoBot", callback_data="pay:crypto")
    builder.button(text="◀ Назад", callback_data=back_cb)
    builder.adjust(1)
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Пользователи", callback_data="admin:users")
    builder.button(text="📋 Все подписки", callback_data="admin:subs")
    builder.button(text="📝 Управление подписками", callback_data="admin:manage")
    builder.button(text="📨 Рассылка", callback_data="admin:broadcast")
    builder.button(text="🎁 Выдать подписку", callback_data="admin:grant")
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_subs_list_keyboard(subs: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in subs:
        label = s["username"] or str(s["telegram_id"])
        builder.button(text=label, callback_data=f"admin_sub:{s['id']}")
    builder.button(text="◀ Назад", callback_data="admin")
    builder.adjust(1)
    return builder.as_markup()


def admin_sub_actions_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Продлить", callback_data=f"sub_extend:{sub_id}")
    builder.button(text="❌ Удалить", callback_data=f"sub_delete:{sub_id}")
    builder.button(text="◀ Назад", callback_data="admin:manage")
    builder.adjust(1)
    return builder.as_markup()
