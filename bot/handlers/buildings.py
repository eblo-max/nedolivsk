"""Экран пристроек: постройка зданий (Ярус 1 — производство)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import buildings, production
from bot.handlers import common
from bot.keyboards import inline as kb


async def _show_production(callback: CallbackQuery, player: Player, building) -> None:
    img = images.named_image(building.image) if building.image else None
    await common.show_image_panel(
        callback.message,
        img,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
        callback.from_user.id,
    )

router = Router()


async def _get_player(
    callback: CallbackQuery, session: AsyncSession, *, lock: bool = False
) -> Player | None:
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


@router.callback_query(F.data == "buildings")
async def cb_buildings(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    done = buildings.finalize_build(player, player.tavern)  # ленивое завершение
    await common.show_image_panel(
        callback.message,
        images.tavern_image(player.tavern.level),  # список — на фоне таверны
        texts.buildings_screen(player, player.tavern),
        kb.buildings_kb(player, player.tavern),
        callback.from_user.id,
    )
    await callback.answer(f"🏗 {done.name} достроена!" if done else None)


@router.callback_query(F.data.startswith("build_open:"))
async def cb_build_open(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    building = buildings.CATALOG.get(callback.data.split(":", 1)[1])
    if building is None:
        await callback.answer()
        return
    # построенное здание с производством → сразу экран производства
    if buildings.is_built(player.tavern, building.id) and building.id in production.PRODUCERS:
        await _show_production(callback, player, building)
        await callback.answer()
        return
    img = images.named_image(building.image) if building.image else None
    await common.show_image_panel(
        callback.message,
        img,
        texts.building_detail(building, player, player.tavern),
        kb.building_detail_kb(player, player.tavern, building),
        callback.from_user.id,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("build_make:"))
async def cb_build_make(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    bid = callback.data.split(":", 1)[1]
    buildings.finalize_build(player, player.tavern)  # вдруг прошлая уже готова

    result = buildings.start_build(player, player.tavern, bid)
    if not result.ok:
        if result.reason == "not_enough":
            await common.caption_edit(
                callback.message,
                texts.build_not_enough(result.building, player),
                kb.buildings_back_kb(),
            )
            await callback.answer()
        else:
            alert = {
                "built": "Уже построено.",
                "busy": "Другая стройка ещё идёт — артель одна.",
                "requires": "Сначала построй, что требуется.",
                "reputation": "Репутация низковата для этой постройки.",
            }.get(result.reason, "Не вышло.")
            await callback.answer(alert, show_alert=True)
        return

    await common.caption_edit(
        callback.message,
        texts.build_started(result.building, result.hours),
        kb.buildings_back_kb(),
    )
    await callback.answer("Заложили фундамент!")


@router.callback_query(F.data.startswith("prod_make:"))
async def cb_prod_make(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    bid = callback.data.split(":", 1)[1]
    if bid != "mill":
        await callback.answer()
        return
    ok, reason, cin = production.start_mill(player, player.tavern)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.mill_not_enough(cin), show_alert=True)
        else:
            await callback.answer("Жернова уже крутятся.", show_alert=True)
        return
    building = buildings.CATALOG["mill"]
    await common.caption_edit(
        callback.message,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
    )
    await callback.answer("Закрутились!")


@router.callback_query(F.data.startswith("meadery:"))
async def cb_meadery(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    recipe = callback.data.split(":", 1)[1]
    ok, reason, cin = production.start_meadery(player, player.tavern, recipe)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.meadery_not_enough(recipe, cin), show_alert=True)
        elif reason == "busy":
            await callback.answer("Котлы уже заняты.", show_alert=True)
        else:
            await callback.answer()
        return
    building = buildings.CATALOG["meadery"]
    await common.caption_edit(
        callback.message,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
    )
    await callback.answer("Забулькало!")


@router.callback_query(F.data.startswith("brew:"))
async def cb_brew(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    try:
        tier = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    ok, reason, cin = production.start_brew(player, player.tavern, tier)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.brew_not_enough(tier, cin), show_alert=True)
        elif reason == "busy":
            await callback.answer("Чаны заняты — варка идёт.", show_alert=True)
        else:
            await callback.answer()
        return
    building = buildings.CATALOG["brewery"]
    await common.caption_edit(
        callback.message,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
    )
    await callback.answer("Заброжало!")


@router.callback_query(F.data == "brew_age")
async def cb_brew_age(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    if not production.start_age(player, player.tavern):
        await callback.answer("Выдержка сейчас невозможна.", show_alert=True)
        return
    building = buildings.CATALOG["brewery"]
    await common.caption_edit(
        callback.message,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
    )
    await callback.answer("Поставили на выдержку — теперь не зевай!")


@router.callback_query(F.data.startswith("prod_claim:"))
async def cb_prod_claim(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    bid = callback.data.split(":", 1)[1]
    if bid == "mill":
        amount = production.claim_mill(player, player.tavern)
        if amount <= 0:
            await callback.answer("Солод ещё не готов.", show_alert=True)
            return
        building = buildings.CATALOG["mill"]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(f"🌱 +{amount} солода")
        return
    if bid == "meadery":
        result = production.claim_meadery(player, player.tavern)
        if result is None:
            await callback.answer("Напиток ещё не готов.", show_alert=True)
            return
        recipe, qty = result
        drink = production.DRINKS[recipe]
        building = buildings.CATALOG["meadery"]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(f"{drink.emoji} +{qty} {drink.name} в погреб")
        return
    if bid == "brewery":
        result = production.claim_brew(player, player.tavern)
        if result is None:
            await callback.answer("Эль ещё не готов.", show_alert=True)
            return
        outcome, tier, qty = result
        building = buildings.CATALOG["brewery"]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(texts.brew_claimed(outcome, tier, qty), show_alert=True)
        return
    await callback.answer()
