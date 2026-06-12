"""Экран персонажа и кузница."""

import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.db.models import Player
from bot.game import character, items, logic
from bot.handlers.common import send_tavern_screen
from bot.keyboards import inline as kb

router = Router()


async def _get_player(
    callback: CallbackQuery, session: AsyncSession, *, lock: bool = False
) -> Player | None:
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


async def _caption_edit(callback: CallbackQuery, text: str, markup) -> None:
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


def _craft_line(player: Player) -> str:
    state, minutes = logic.craft_state(player)
    if state == "active":
        item = items.CATALOG.get(player.craft_item)
        name = item.name if item else "вещь"
        return f"⚒ Мастер куёт «{name}» — ещё {minutes // 60} ч {minutes % 60} мин."
    if state == "ready":
        return "🎁 Мастер закончил заказ — забери вещь!"
    return ""


async def _show_character(callback: CallbackQuery, player: Player) -> None:
    """Всегда свежее фото куклы (старое сообщение убираем)."""
    state, _ = logic.craft_state(player)
    caption = texts.character_screen(player, _craft_line(player))
    markup = kb.character_kb(craft_ready=(state == "ready"))
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    if character.background_exists():
        img = await asyncio.to_thread(character.render, player.equipment)
        await callback.message.answer_photo(
            BufferedInputFile(img, filename="character.jpg"),
            caption=caption,
            reply_markup=markup,
        )
    else:
        await callback.message.answer(caption, reply_markup=markup)


@router.callback_query(F.data == "character")
async def cb_character(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    await _show_character(callback, player)
    await callback.answer()


@router.callback_query(F.data == "tavern_new")
async def cb_tavern_new(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_tavern_screen(callback.message, player)
    await callback.answer()


@router.callback_query(F.data == "forge")
async def cb_forge(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    await _caption_edit(callback, texts.forge_screen(player), kb.forge_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("forge_item:"))
async def cb_forge_item(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    item = items.CATALOG.get(callback.data.split(":", 1)[1])
    if item is None:
        await callback.answer()
        return
    await _caption_edit(
        callback, texts.forge_item_screen(item, player), kb.forge_item_kb(item.id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("forge_make:"))
async def cb_forge_make(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    item_id = callback.data.split(":", 1)[1]

    state, minutes = logic.craft_state(player)
    if state == "active":
        await callback.answer(texts.craft_in_progress(minutes), show_alert=True)
        return
    if state == "ready":
        await callback.answer("Сначала забери готовую вещь!", show_alert=True)
        return

    result = logic.start_craft(player, item_id)
    if not result.ok:
        if result.reason == "not_enough":
            await callback.answer(texts.craft_not_enough(result.item), show_alert=True)
        else:
            await callback.answer()
        return

    await _caption_edit(callback, texts.craft_started(result.item), kb.character_kb())
    await callback.answer("Мастер взялся за дело!")


@router.callback_query(F.data == "craft_claim")
async def cb_craft_claim(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return

    result = logic.claim_craft(player)
    if not result.ok:
        if result.reason == "not_ready":
            await callback.answer(
                texts.craft_in_progress(result.minutes_left), show_alert=True
            )
        else:
            await callback.answer("Мастер ничего для тебя не ковал.", show_alert=True)
        return

    await callback.answer(f"{result.item.name} — твоё!")
    await _show_character(callback, player)
