"""Ежедневный бонус («опохмел»): экран, активация, команда /bonus."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import buff
from bot.keyboards import inline as kb

router = Router()


async def _player(callback: CallbackQuery, session: AsyncSession, *,
                  lock: bool = False) -> Player | None:
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "bonus")
async def cb_bonus(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    buff.refresh(player)
    await _edit(callback, texts.bonus_screen(player), kb.bonus_kb(player))
    await callback.answer()


@router.callback_query(F.data == "bonus_go")
async def cb_bonus_go(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    buff.refresh(player)
    res = buff.activate(player)
    if not res.ok:
        if res.reason == "busy":
            await callback.answer(texts.bonus_busy(res.boon, res.minutes),
                                  show_alert=True)
        else:
            await callback.answer(texts.bonus_none(), show_alert=True)
            await _edit(callback, texts.bonus_screen(player), kb.bonus_kb(player))
        return
    await _edit(callback, texts.bonus_screen(player), kb.bonus_kb(player))
    await callback.answer(texts.bonus_activated(res.boon, res.minutes), show_alert=True)


@router.message(Command("bonus"))
async def cmd_bonus(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if not player or not player.tavern:
        await message.answer("Сначала обзаведись кабаком: /start")
        return
    buff.refresh(player)
    msg = await message.answer(texts.bonus_screen(player), reply_markup=kb.bonus_kb(player))
    panels.claim(msg, message.from_user.id)
