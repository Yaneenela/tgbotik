import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault

from dotenv import load_dotenv

from bot.config import load_config
from bot.db import Database
from bot.xui import XUIManager
from bot.handlers import create_router, check_pending_payments, scheduler, sync_subscriptions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_bg_tasks: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


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
    inbounds = []
    for attempt in range(1, 6):
        try:
            inbounds = await xui.get_inbounds()
            break
        except Exception as e:
            logger.error(f"3x-UI connection attempt {attempt}/5 failed: {e}")
            if attempt == 5:
                return
            await asyncio.sleep(10)
    logger.info(f"Connected to 3x-UI, found {len(inbounds)} inbounds")

    await sync_subscriptions(cfg, db, xui)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    default_commands = [
        BotCommand(command="start", description="Главное меню"),
    ]
    await bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())

    dp = Dispatcher()
    dp.include_router(create_router(cfg, db, xui))

    await bot.delete_webhook(drop_pending_updates=True)
    _spawn(check_pending_payments(cfg, db, xui, bot))
    _spawn(scheduler(cfg, db, xui, bot))

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, db=db, cfg=cfg, xui=xui)
    finally:
        for t in list(_bg_tasks):
            t.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
