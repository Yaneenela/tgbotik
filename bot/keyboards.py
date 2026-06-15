from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001f48e Купить подписку", callback_data="buy")
    builder.button(text="\U0001f4cb Мои подписки", callback_data="my_subs")
    builder.button(text="\u2753 Помощь", callback_data="help")
    builder.adjust(1)
    return builder.as_markup()


def back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\u25c0 Назад", callback_data="menu")
    return builder.as_markup()


def plans_keyboard(plans: list, prefix: str = "plan") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, plan in enumerate(plans):
        traffic = f"{plan.traffic_gb} \u0413\u0411" if plan.traffic_gb > 0 else "\u0411\u0435\u0437\u043b\u0438\u043c\u0438\u0442"
        builder.button(
            text=f"{plan.name} | {plan.price} \u0440\u0443\u0431 | {traffic}",
            callback_data=f"{prefix}:{i}",
        )
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(has_yookassa: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_yookassa:
        builder.button(text="\U0001f4b3 ЮKassa (карта, ЮMoney)", callback_data="pay:yookassa")
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="buy")
    builder.adjust(1)
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001f465 \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438", callback_data="admin:users")
    builder.button(text="\U0001f4cb \u0412\u0441\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438", callback_data="admin:subs")
    builder.button(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()
