"""Экран персонажа и кузница."""

import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import panels, texts
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


async def _show_character(callback: CallbackQuery, player: Player) -> None:
    """Всегда свежее фото куклы (старое сообщение убираем)."""
    state, _ = logic.craft_state(player)
    caption = texts.character_screen(player, texts.craft_line(player))
    markup = kb.character_kb(craft_ready=(state == "ready"))
    panels.release(callback.message)  # старая панель уходит вместе с сообщением
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    if character.background_exists():
        img = await asyncio.to_thread(character.render, player.equipment)
        msg = await callback.message.answer_photo(
            BufferedInputFile(img, filename="character.jpg"),
            caption=caption,
            reply_markup=markup,
        )
    else:
        msg = await callback.message.answer(caption, reply_markup=markup)
    panels.claim(msg, callback.from_user.id)


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
    panels.release(callback.message)
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_tavern_screen(callback.message, player, owner_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "forge")
async def cb_forge(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    await _caption_edit(callback, texts.forge_screen(player), kb.forge_kb(player))
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
    cur_tier = items.equipped_tier(getattr(player, "equipment", None), item.id)
    next_tier = min(cur_tier + 1, items.TIER_MAX)
    await _caption_edit(
        callback,
        texts.forge_item_screen(item, player, cur_tier, next_tier),
        kb.forge_item_kb(item.id, maxed=cur_tier >= items.TIER_MAX),
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
            await callback.answer(
                texts.craft_not_enough(result.item, result.tier), show_alert=True
            )
        elif result.reason == "max_tier":
            await callback.answer(
                "Лучше уже не выкуют. Это вершина ремесла.", show_alert=True
            )
        else:
            await callback.answer()
        return

    await _caption_edit(
        callback,
        texts.craft_started(result.item, result.tier, result.hours),
        kb.character_kb(),
    )
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

    await callback.answer(f"{result.item.name} {items.TIER_STARS[result.tier]} — твоё!")
    await _show_character(callback, player)
