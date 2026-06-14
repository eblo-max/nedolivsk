import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from bot.config import settings
from bot.db.base import create_tables, engine
from bot.handlers import (
    admin,
    auction,
    buildings,
    character,
    commands,
    group,
    hub,
    loot,
    rating,
    start,
    story,
    tavern,
    trade,
    worldmap_cmd,
)
from bot.middlewares import DbSessionMiddleware, PanelGuardMiddleware
from bot.notifier import notifier_loop


async def _setup_commands(bot: Bot) -> None:
    """Меню команд (всплывает на «/»): публичные — всем, /tavern — в группах,
    админские — только в личке админа."""
    sections = [
        BotCommand(command="market", description="🏪 Базар — цены в реальном времени"),
        BotCommand(command="auction", description="🔨 Аукцион — выставить лот"),
        BotCommand(command="top", description="🏆 Рейтинг таверн"),
        BotCommand(command="city", description="🏛 Расклад фракций"),
        BotCommand(command="citizens", description="👥 Горожане и репутация"),
        BotCommand(command="chronicle", description="📜 Летопись города"),
        BotCommand(command="map", description="🗺 Карта мира"),
        BotCommand(command="help", description="❓ Правила и помощь"),
    ]
    public = [BotCommand(command="start", description="🍺 Открыть таверну"), *sections]
    in_group = [
        BotCommand(command="start", description="🍺 Открыть таверну"),
        BotCommand(command="tavern", description="🏠 Мой кабак прямо в чате"),
        *sections,
    ]
    await bot.set_my_commands(public, scope=BotCommandScopeDefault())
    await bot.set_my_commands(in_group, scope=BotCommandScopeAllGroupChats())
    if settings.admin_id:
        await bot.set_my_commands(
            public + [
                BotCommand(command="fair", description="🎪 Запустить ярмарку (админ)"),
                BotCommand(command="reset", description="🔥 Сбросить игрока (админ)"),
            ],
            scope=BotCommandScopeChat(chat_id=settings.admin_id),
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await create_tables()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware())
    dp.callback_query.outer_middleware(PanelGuardMiddleware())
    dp.include_routers(
        admin.router, worldmap_cmd.router, rating.router, character.router,
        buildings.router, start.router, tavern.router, story.router,
        trade.router, auction.router, commands.router, loot.router,
        hub.router, group.router
    )

    notifier_task = asyncio.create_task(notifier_loop(bot))

    await _setup_commands(bot)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
