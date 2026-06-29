import asyncio
import logging
import os

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
    admin_panel,
    auction,
    bonus,
    buildings,
    character,
    commands,
    group,
    hub,
    hunt,
    invasion,
    loot,
    nightrun,
    raid,
    rating,
    referral,
    shop,
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
        BotCommand(command="bonus", description="🎁 Ежедневный бонус"),
        BotCommand(command="market", description="🏪 Базар — цены в реальном времени"),
        BotCommand(command="auction", description="🔨 Аукцион — выставить лот"),
        BotCommand(command="hunt", description="🏹 Охота на зверя"),
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
                BotCommand(command="admin", description="🛠 Админ-панель"),
                BotCommand(command="fair", description="🎪 Запустить ярмарку (админ)"),
                BotCommand(command="orc", description="🪓 Запустить Орду орков (админ)"),
                BotCommand(command="reset", description="🔥 Сбросить игрока (админ)"),
            ],
            scope=BotCommandScopeChat(chat_id=settings.admin_id),
        )


async def _load_media_cache() -> None:
    """Подтянуть сохранённые file_id картинок/видео из БД в кэш процесса.
    Они переживают деплой (ФС Railway эфемерна) → медиа не грузятся заново,
    и не нужен прогрев с мельканием сообщений в админ-чате."""
    from bot.db.base import session_factory
    from bot.db import repo
    from bot.handlers import common

    async with session_factory() as session:
        world = await repo.get_or_create_world(session)
        common.load_file_ids(world.media_ids)
        from bot.game import worldevent  # активное мир-событие — в кэш сразу на старте
        worldevent.set_active(world.event_kind, world.event_until, world.event_good)
        # Кэш живого рейда — сразу на старте, иначе после рестарта кнопка «РЕЙД-БОСС»
        # в меню таверны пропадает до первого тика нотифаера (≤60с) — игроки не
        # могут зайти в бой из лички (особенно если сообщение в чате удалили).
        from bot.game import raid as raidmod
        active_raid = await repo.get_active_raid(session)
        raidmod.set_active(active_raid.id if active_raid else None)
        # Кэш «идёт сбор на Орду» — чтобы кнопка «в строй» в меню таверны пережила рестарт.
        from bot.game import invasion as invmod
        active_inv = await repo.get_active_invasion(session)
        invmod.set_gathering(active_inv.id if (active_inv and active_inv.status == "gathering")
                             else None)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await create_tables()
    await _load_media_cache()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware())
    dp.callback_query.outer_middleware(PanelGuardMiddleware())
    dp.include_routers(
        admin.router, admin_panel.router, worldmap_cmd.router, rating.router,
        character.router,
        buildings.router, start.router, tavern.router, story.router,
        trade.router, auction.router, commands.router, loot.router,
        hunt.router, raid.router, bonus.router, referral.router, shop.router,
        nightrun.router, invasion.router, hub.router, group.router
    )

    notifier_task = asyncio.create_task(notifier_loop(bot))

    # Mini App карта: веб-сервер на $PORT (Railway даёт публичный домен). Без PORT
    # (локально/воркер без веба) — не поднимаем, бот работает как обычно.
    webapp_runner = None
    port = os.environ.get("PORT")
    if port:
        from bot.webapp import run_webapp
        webapp_runner = await run_webapp(int(port), bot)   # bot → рассылка в чаты из эндпоинтов
        logging.info("Mini App карта поднята на порту %s", port)

    me = await bot.get_me()
    from bot.keyboards.inline import set_bot_username
    set_bot_username(me.username)   # для Direct-Link URL анонса орды (карта в группах)

    await _setup_commands(bot)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        if webapp_runner is not None:
            await webapp_runner.cleanup()
        await engine.dispose()


if __name__ == "__main__":
    try:
        import uvloop  # быстрый event loop (Linux/Railway); на Windows-dev нет — ок
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
