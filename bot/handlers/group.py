"""Игра в общем чате: команды-словом «гг …».

Каждый игрок открывает свою панель прямо в чате; кнопки чужой панели
жать нельзя (см. PanelGuardMiddleware). Регистрация — только в личке.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import autoclean, texts
from bot.db import repo
from bot.handlers import common
from bot.handlers.rating import show_rating
from bot.keyboards import inline as kb

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

# Слово -> раздел. Префикс «гг», голое «гг» = таверна.
SECTIONS = {
    "гг": "tavern", "гг таверна": "tavern", "гг кабак": "tavern",
    "гг перс": "character", "гг персонаж": "character",
    "гг склад": "warehouse", "гг запасы": "warehouse",
    "гг кузница": "forge", "гг кузня": "forge",
    "гг карта": "map", "гг мир": "map",
    "гг топ": "rating", "гг рейтинг": "rating",
    "гг помощь": "help", "гг команды": "help",
    "гг правила": "rules", "гг как играть": "rules",
    "гг хроника": "chronicle", "гг летопись": "chronicle",
    "гг репутация": "citizens", "гг горожане": "citizens",
    "гг город": "city", "гг площадь": "city",
    "гг рынок": "market", "гг базар": "market", "гг цены": "market",
    "гг бонус": "bonus", "гг опохмел": "bonus",
}


def _section(text: str | None) -> str | None:
    return SECTIONS.get(text.strip().lower()) if text else None


async def _redirect_to_pm(message: Message) -> Message:
    me = await message.bot.me()
    return await message.reply(
        texts.GROUP_NEED_TAVERN, reply_markup=kb.pm_link_kb(me.username)
    )


@router.message(F.text.func(lambda t: _section(t) is not None))
async def gg_command(message: Message, session: AsyncSession) -> None:
    section = _section(message.text)
    autoclean.schedule_message(message)  # подчистить сам триггер «гг …»
    await repo.remember_chat(session, message.chat.id, message.chat.title)

    if section == "help":
        autoclean.schedule_message(await message.reply(texts.COMMANDS_SCREEN))
        return
    if section == "rules":
        autoclean.schedule_message(await message.reply(texts.RULES))
        return
    if section == "map":
        # Карта живёт в мини-аппе — вместо картинки-снимка даём кнопку на неё
        # (в группе — Direct-Link, если настроен; иначе подсказка открыть в личке).
        mkb = kb.world_map_kb(message.chat.type == "private")
        autoclean.schedule_message(await message.reply(texts.MAP_HINT, reply_markup=mkb))
        return
    if section == "rating":
        autoclean.schedule_message(await show_rating(message, session))
        return
    if section == "chronicle":
        entries = await repo.recent_chronicle(session, repo.GLOBAL_CITY_ID, 10)
        autoclean.schedule_message(await message.reply(texts.chronicle_screen(entries)))
        return
    if section == "city":
        city = await repo.get_world_city(session)   # единый мир — город у всех общий
        autoclean.schedule_message(await message.reply(texts.city_screen(city)))
        return
    if section == "market":
        world = await repo.get_or_create_world(session)  # единый рынок (глобальный)
        autoclean.schedule_message(await message.reply(texts.market_screen(world)))
        return

    player = await repo.get_player(session, message.from_user.id)
    if not player or not player.tavern:
        autoclean.schedule_message(await _redirect_to_pm(message))
        return

    player.chat_id = message.chat.id  # домашний чат — сюда шлём уведомления

    if section == "citizens":
        autoclean.schedule_message(await message.reply(texts.citizens_screen(player)))
        return

    # панели сами планируют свою подчистку (см. common._register_panel)
    owner = message.from_user.id
    if section == "character":
        await common.open_character(message, player, owner)
    elif section == "warehouse":
        await common.open_warehouse(message, player, owner)
    elif section == "forge":
        await common.open_forge(message, player, owner)
    elif section == "bonus":
        await common.open_bonus(message, player, owner)
    else:  # tavern
        await common.open_tavern(message, player, owner)


@router.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
async def track_bot_membership(
    event: ChatMemberUpdated, session: AsyncSession
) -> None:
    """Авто-учёт чатов: бота добавили/повысили — запоминаем как адресата
    анонсов; выгнали/вышел — забываем. remember_chat — идемпотентный upsert,
    так что повторные апдейты безопасны."""
    status = event.new_chat_member.status
    if status in ("member", "administrator", "creator"):
        await repo.remember_chat(session, event.chat.id, event.chat.title)
    elif status in ("left", "kicked"):
        await repo.forget_chat(session, event.chat.id)


@router.message(Command("start", "tavern", "play"))
async def group_start(message: Message, session: AsyncSession) -> None:
    autoclean.schedule_message(message)
    await repo.remember_chat(session, message.chat.id, message.chat.title)
    player = await repo.get_player(session, message.from_user.id)
    if not player or not player.tavern:
        autoclean.schedule_message(await _redirect_to_pm(message))
        return
    player.chat_id = message.chat.id  # домашний чат — сюда шлём уведомления
    await common.open_tavern(message, player, message.from_user.id)
