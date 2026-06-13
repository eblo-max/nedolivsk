"""Игра в общем чате: команды-словом «гг …».

Каждый игрок открывает свою панель прямо в чате; кнопки чужой панели
жать нельзя (см. PanelGuardMiddleware). Регистрация — только в личке.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.handlers import common
from bot.handlers.rating import show_rating
from bot.handlers.worldmap_cmd import cmd_map
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
}


def _section(text: str | None) -> str | None:
    return SECTIONS.get(text.strip().lower()) if text else None


async def _redirect_to_pm(message: Message) -> None:
    me = await message.bot.me()
    await message.reply(
        texts.GROUP_NEED_TAVERN, reply_markup=kb.pm_link_kb(me.username)
    )


@router.message(F.text.func(lambda t: _section(t) is not None))
async def gg_command(message: Message, session: AsyncSession) -> None:
    section = _section(message.text)

    if section == "help":
        await message.reply(texts.GROUP_HELP)
        return
    if section == "map":
        await cmd_map(message, session)
        return
    if section == "rating":
        await show_rating(message, session)
        return

    player = await repo.get_player(session, message.from_user.id)
    if not player or not player.tavern:
        await _redirect_to_pm(message)
        return

    owner = message.from_user.id
    if section == "character":
        await common.open_character(message, player, owner)
    elif section == "warehouse":
        await common.open_warehouse(message, player, owner)
    elif section == "forge":
        await common.open_forge(message, player, owner)
    else:  # tavern
        await common.open_tavern(message, player, owner)


@router.message(Command("start", "tavern", "play"))
async def group_start(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if not player or not player.tavern:
        await _redirect_to_pm(message)
        return
    await common.open_tavern(message, player, message.from_user.id)
