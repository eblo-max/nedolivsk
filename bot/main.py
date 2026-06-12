import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.db.base import create_tables, engine
from bot.handlers import (
    admin,
    character,
    group,
    rating,
    start,
    tavern,
    worldmap_cmd,
)
from bot.middlewares import DbSessionMiddleware
from bot.notifier import notifier_loop


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await create_tables()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware())
    dp.include_routers(
        admin.router, worldmap_cmd.router, rating.router, character.router,
        start.router, tavern.router, group.router
    )

    notifier_task = asyncio.create_task(notifier_loop(bot))

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
