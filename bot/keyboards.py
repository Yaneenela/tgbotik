from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(has_payment: bool = True, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_payment:
        builder.button(text="\U0001f48e Купить подписку", callback_data="buy")
    builder.button(text="\U0001f4cb Мои подписки", callback_data="my_subs")
    builder.button(text="\u2753 Помощь", callback_data="help")
    if is_admin:
        builder.button(text="\U0001f6e1 \u0410\u0434\u043c\u0438\u043d\u043a\u0430", callback_data="admin")
    builder.adjust(1)
    return builder.as_markup()


def back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\u25c0 Назад", callback_data="menu")
    return builder.as_markup()


def plans_keyboard(plans: list, prefix: str = "plan") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, plan in enumerate(plans):
        builder.button(
            text=f"{plan.name} | {plan.price} \u0440\u0443\u0431",
            callback_data=f"{prefix}:{i}",
        )
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(has_yookassa: bool, has_crypto: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_yookassa:
        builder.button(text="\U0001f4b3 Карта / СБП", callback_data="pay:yookassa")
    if has_crypto:
        builder.button(text="\U0001f4b1 CryptoBot", callback_data="pay:crypto")
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="buy")
    builder.adjust(1)
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001f465 \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438", callback_data="admin:users")
    builder.button(text="\U0001f4cb \u0412\u0441\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438", callback_data="admin:subs")
    builder.button(text="\U0001f4dd \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430\u043c\u0438", callback_data="admin:manage")
    builder.button(text="\U0001f4e8 \u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430", callback_data="admin:broadcast")
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_subs_list_keyboard(subs: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in subs:
        label = s["username"] or str(s["telegram_id"])
        builder.button(text=label, callback_data=f"admin_sub:{s['id']}")
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="admin")
    builder.adjust(1)
    return builder.as_markup()


def admin_sub_actions_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001f4c5 \u041f\u0440\u043e\u0434\u043b\u0438\u0442\u044c", callback_data=f"sub_extend:{sub_id}")
    builder.button(text="\u274c \u0423\u0434\u0430\u043b\u0438\u0442\u044c", callback_data=f"sub_delete:{sub_id}")
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="admin:manage")
    builder.adjust(1)
    return builder.as_markup()
