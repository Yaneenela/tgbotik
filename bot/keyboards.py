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


def back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀ Назад", callback_data="menu")
    return builder.as_markup()


def plans_keyboard(plans: list, prefix: str = "plan") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, plan in enumerate(plans):
        builder.button(
            text=f"{plan.name} | {plan.price} руб",
            callback_data=f"{prefix}:{i}",
        )
    builder.button(text="◀ Назад", callback_data="menu")
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
