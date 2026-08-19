import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from dotenv import load_dotenv

from bot.config import load_config
from bot.db import Database
from bot.xui import XUIManager
from bot.handlers import create_router, check_pending_payments, scheduler, sync_subscriptions

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    load_dotenv()
    cfg = load_config()

    if not cfg.bot_token:
        logger.error("BOT_TOKEN is required")
        return
    if not cfg.xui_url or not cfg.xui_username or not cfg.xui_password:
        logger.error("XUI_URL, XUI_USERNAME, XUI_PASSWORD are required")
        return
    has_platega = cfg.has_platega
    has_crypto = bool(cfg.crypto_bot_token)
    if not has_platega and not has_crypto:
        logger.warning("No payment methods configured — bot will start without purchase functionality")

    db = Database()
    await db.connect()
    logger.info("Database connected")

    xui = XUIManager(cfg.xui_url, cfg.xui_username, cfg.xui_password)
    try:
        inbounds = await xui.get_inbounds()
        logger.info(f"Connected to 3x-UI, found {len(inbounds)} inbounds")
    except Exception as e:
        logger.error(f"Failed to connect to 3x-UI: {e}")
        return

    await sync_subscriptions(cfg, db, xui)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    default_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="my", description="Мои подписки"),
        BotCommand(command="plans", description="Тарифы"),
    ]
    await bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())
    for admin_id in cfg.admin_ids:
        await bot.set_my_commands(
            default_commands + [
                BotCommand(command="admin", description="Админка"),
                BotCommand(command="broadcast", description="Рассылка"),
            ],
            scope=BotCommandScopeChat(chat_id=admin_id),
        )

    dp = Dispatcher()
    dp.include_router(create_router(cfg, db, xui))

    asyncio.create_task(check_pending_payments(cfg, db, xui, bot))
    asyncio.create_task(scheduler(cfg, db, xui, bot))

    logger.info("Starting bot polling...")
    await dp.start_polling(bot, db=db, cfg=cfg, xui=xui)


if __name__ == "__main__":
    asyncio.run(main())
