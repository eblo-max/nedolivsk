"""Ежедневный бонус («опохмел»): экран, активация, команда /bonus."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import effects, images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import buff
from bot.handlers import common
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
    """Экран опохмела на месте, на картинке похмельного утра."""
    await common.show_image_panel(
        callback.message, images.named_image("opoxmel"),
        text, markup, callback.from_user.id)


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
    repo.add_log(session, "player", player.id, f"🎁 активировал баф «{res.boon.name}»")
    await _edit(callback, texts.bonus_screen(player), kb.bonus_kb(player))
    await effects.react_msg(callback.message, "🎉")
    await callback.answer(texts.bonus_activated(res.boon, res.minutes), show_alert=True)


@router.message(Command("bonus"))
async def cmd_bonus(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if not player or not player.tavern:
        await message.answer("Сначала обзаведись кабаком: /start")
        return
    buff.refresh(player)
    img = images.named_image("opoxmel")
    caption = texts.bonus_screen(player)
    if img is not None:
        media = common.cached_media(img)
        msg = await message.answer_photo(media, caption=common.clamp_caption(caption),
                                         reply_markup=kb.bonus_kb(player))
        common.remember_file_id(img, msg)
    else:
        msg = await message.answer(caption, reply_markup=kb.bonus_kb(player))
    panels.claim(msg, message.from_user.id)
