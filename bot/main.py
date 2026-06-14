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
    bonus,
    buildings,
    character,
    commands,
    group,
    hub,
    hunt,
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
                BotCommand(command="fair", description="🎪 Запустить ярмарку (админ)"),
                BotCommand(command="reset", description="🔥 Сбросить игрока (админ)"),
            ],
            scope=BotCommandScopeChat(chat_id=settings.admin_id),
        )


async def _prewarm_videos(bot: Bot) -> None:
    """Прогрев видео: грузим в Telegram на старте и кэшируем file_id, чтобы
    первый показ игроку был мгновенным (FS Railway эфемерна — кэш в процессе)."""
    if not settings.admin_id:
        return
    from bot import images
    from bot.game import combat
    from bot.handlers import common

    seen: set[str] = set()
    for enemy in combat.ENEMIES:
        if not enemy.video or enemy.video in seen:
            continue
        seen.add(enemy.video)
        path = images.named_video(enemy.video)
        if path is None:
            continue
        try:
            msg = await bot.send_video(
                settings.admin_id, common.cached_media(path),
                disable_notification=True)
            common.remember_file_id(path, msg)
            await bot.delete_message(settings.admin_id, msg.message_id)
        except Exception:  # noqa: BLE001 — нет доступа к админ-чату и т.п.
            logging.getLogger(__name__).warning("Прогрев видео %s не удался", enemy.video)


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
        hunt.router, bonus.router, hub.router, group.router
    )

    notifier_task = asyncio.create_task(notifier_loop(bot))

    await _setup_commands(bot)
    await _prewarm_videos(bot)  # прогрев видео-кэша — первый показ без задержки

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        await engine.dispose()


if __name__ == "__main__":
    try:
        import uvloop  # быстрый event loop (Linux/Railway); на Windows-dev нет — ок
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
