"""Экран персонажа и кузница."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.db.models import Player
from bot.game import character, items, logic
from bot.handlers import common
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


async def _show_on_doll(callback: CallbackQuery, player: Player,
                        caption: str, markup) -> None:
    """Показать на панели куклу персонажа с заданной подписью (в том же окне)."""
    if not character.background_exists():
        await common.show_text_panel(
            callback.message, caption, markup, callback.from_user.id
        )
        return
    media, key, need_capture = await common.doll_media(player)
    result = await common.show_photo_panel(
        callback.message, media, caption, markup, callback.from_user.id
    )
    if need_capture:
        common.remember_media(key, result)


async def _show_character(callback: CallbackQuery, player: Player) -> None:
    """Экран персонажа в том же окне: подменяем фото куклы на месте."""
    state, _ = logic.craft_state(player)
    caption = texts.character_screen(player, texts.craft_line(player))
    markup = kb.character_kb(craft_ready=(state == "ready"))
    await _show_on_doll(callback, player, caption, markup)


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
    await common.show_tavern_panel(callback.message, player, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "forge")
async def cb_forge(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    # Список кузницы живёт на кукле — возвращаем фото куклы (после показа вещи).
    await _show_on_doll(callback, player, texts.forge_screen(player), kb.forge_kb(player))
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
    caption = texts.forge_item_screen(item, player, cur_tier, next_tier)
    markup = kb.forge_item_kb(item.id, maxed=cur_tier >= items.TIER_MAX,
                              craftable=item.craftable)
    # Показываем картинку самой вещи (спрайт из assets/items/<sprite>.png).
    sprite = item.sprite or item.id
    img_path = character.ITEMS_DIR / f"{sprite}.png"
    await common.show_image_panel(
        callback.message, img_path if img_path.is_file() else None,
        caption, markup, callback.from_user.id,
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

    # Ковка пошла — возвращаем фото куклы (уходим с картинки вещи).
    await _show_on_doll(
        callback, player,
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
