from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(has_payment: bool = True, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Купить подписку", callback_data="buy")
    builder.button(text="👤 Мой профиль", callback_data="my_subs")
    builder.button(text="❓ Помощь", callback_data="help")
    if is_admin:
        builder.button(text="🛡 Админка", callback_data="admin")
        builder.adjust(1, 2, 1)
    else:
        builder.adjust(1, 2)
    return builder.as_markup()


def back_button(back_cb: str = "menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀ Назад", callback_data=back_cb)
    return builder.as_markup()


def help_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Android", callback_data="help_platform:android")
    builder.button(text="🍎 iOS", callback_data="help_platform:ios")
    builder.button(text="💻 Desktop (Windows/MacOS)", callback_data="help_platform:desktop")
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(2)
    return builder.as_markup()


def plans_keyboard(plans: list, prefix: str = "plan") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, plan in enumerate(plans):
        builder.button(
            text=f"{plan.days} дней | ♾ Безлимит | {plan.price} руб",
            callback_data=f"{prefix}:{i}",
        )
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def device_count_keyboard(current: int = 3, prefix: str = "device", back_cb: str = "buy") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(1, 11):
        mark = " ✅" if i == current else ""
        builder.button(text=f"{i}{mark}", callback_data=f"{prefix}:{i}")
    builder.button(text="◀ Назад", callback_data=back_cb)
    builder.adjust(5)
    return builder.as_markup()


def edit_device_keyboard(sub_id: int, current: int = 3) -> InlineKeyboardMarkup:
    return device_count_keyboard(current, f"devedit:{sub_id}", f"edit_dev_sub:{sub_id}")


def device_mgmt_keyboard(sub_id: int, current: int = 3) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Изменить количество", callback_data=f"edit_dev_count:{sub_id}")
    builder.button(text="🔌 Отключить все", callback_data=f"edit_dev_reset:{sub_id}")
    builder.button(text="📈 Увеличить лимит", callback_data=f"edit_dev_upgrade:{sub_id}")
    builder.button(text="◀ Назад", callback_data="my_subs")
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(has_yookassa: bool, has_crypto: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_yookassa:
        builder.button(text="💳 Карта / СБП", callback_data="pay:yookassa")
    if has_crypto:
        builder.button(text="💱 CryptoBot", callback_data="pay:crypto")
    builder.button(text="◀ Назад", callback_data="buy")
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
