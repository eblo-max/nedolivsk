"""Экран пристроек: постройка зданий (Ярус 1 — производство)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import balance, buildings, newbie, production
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

    repo.add_log(session, "player", player.id,
                 f"🏗 заложил постройку: {result.building.name}")
    await common.caption_edit(
        callback.message,
        texts.build_started(result.building, result.hours),
        kb.buildings_back_kb(),
    )
    await callback.answer("Заложили фундамент!")


@router.callback_query(F.data.startswith("grind:"))
async def cb_grind(callback: CallbackQuery, session: AsyncSession) -> None:
    """Грайндеры (мельница/горн): сырьё → полуфабрикат."""
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    _, _, rest = callback.data.partition(":")
    building, _, recipe = rest.partition(":")
    ok, reason, cin = production.start_grind(player, player.tavern, building, recipe)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.recipe_not_enough(recipe, cin), show_alert=True)
        elif reason == "busy":
            await callback.answer("Уже работает — дождись.", show_alert=True)
        else:
            await callback.answer()
        return
    b = buildings.CATALOG[building]
    await common.caption_edit(
        callback.message,
        texts.production_screen(b, player, player.tavern),
        kb.production_kb(player, player.tavern, b),
    )
    await callback.answer("Закрутилось!")


@router.callback_query(F.data.startswith("rcp:"))
async def cb_recipe(callback: CallbackQuery, session: AsyncSession) -> None:
    """Рецептурные пристройки (пекарня/коптильня/сыроварня): вход → товар."""
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    _, _, rest = callback.data.partition(":")
    building, _, recipe = rest.partition(":")
    ok, reason, cin = production.start_recipe(player, player.tavern, building, recipe)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.recipe_not_enough(recipe, cin), show_alert=True)
        elif reason == "busy":
            await callback.answer("Уже занято — дождись.", show_alert=True)
        else:
            await callback.answer()
        return
    b = buildings.CATALOG[building]
    await common.caption_edit(
        callback.message,
        texts.production_screen(b, player, player.tavern),
        kb.production_kb(player, player.tavern, b),
    )
    await callback.answer("Готовится!")


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


@router.callback_query(F.data.startswith("kitchen:"))
async def cb_kitchen(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    recipe = callback.data.split(":", 1)[1]
    ok, reason, cin = production.start_kitchen(player, player.tavern, recipe)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.kitchen_not_enough(recipe, cin), show_alert=True)
        elif reason == "busy":
            await callback.answer("Очаг уже занят.", show_alert=True)
        else:
            await callback.answer()
        return
    building = buildings.CATALOG["kitchen"]
    await common.caption_edit(
        callback.message,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
    )
    await callback.answer("На огонь!")


@router.callback_query(F.data.startswith("winery:"))
async def cb_winery(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    recipe = callback.data.split(":", 1)[1]
    ok, reason, cin = production.start_winery(player, player.tavern, recipe)
    if not ok:
        if reason == "not_enough":
            await callback.answer(texts.winery_not_enough(recipe, cin), show_alert=True)
        elif reason == "busy":
            await callback.answer("Бочки уже заняты.", show_alert=True)
        else:
            await callback.answer()
        return
    building = buildings.CATALOG["winery"]
    await common.caption_edit(
        callback.message,
        texts.production_screen(building, player, player.tavern),
        kb.production_kb(player, player.tavern, building),
    )
    await callback.answer("Поставили бродить!")


@router.callback_query(F.data.startswith("prod_claim:"))
async def cb_prod_claim(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    bid = callback.data.split(":", 1)[1]
    if bid in production.GRIND:  # мельница/горн → полуфабрикат в инвентарь
        res = production.claim_grind(player, player.tavern, bid)
        if res is None:
            await callback.answer("Ещё не готово.", show_alert=True)
            return
        r, qty = res
        building = buildings.CATALOG[bid]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(
            f"{balance.GOODS_EMOJI.get(r, '📦')} +{qty} {balance.GOODS_NAMES.get(r, r)}")
        return
    if bid in production.RECIPES:  # пекарня/коптильня/сыроварня → товар в погреб
        res = production.claim_recipe(player, player.tavern, bid)
        if res is None:
            await callback.answer("Ещё не готово.", show_alert=True)
            return
        recipe, qty = res
        good = production.GOODS[recipe]
        newbie.mark(player, "nb_craft")  # веха грамоты новосёла
        building = buildings.CATALOG[bid]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(f"{good.emoji} +{qty} {good.name}")
        return
    if bid in ("meadery", "kitchen", "winery"):
        claim = {"meadery": production.claim_meadery,
                 "kitchen": production.claim_kitchen,
                 "winery": production.claim_winery}[bid]
        result = claim(player, player.tavern)
        if result is None:
            await callback.answer("Ещё не готово.", show_alert=True)
            return
        recipe, qty = result
        good = production.GOODS[recipe]
        newbie.mark(player, "nb_craft")  # веха грамоты новосёла
        building = buildings.CATALOG[bid]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(f"{good.emoji} +{qty} {good.name}")
        return
    if bid == "brewery":
        result = production.claim_brew(player, player.tavern)
        if result is None:
            await callback.answer("Эль ещё не готов.", show_alert=True)
            return
        outcome, tier, qty = result
        if qty > 0:
            newbie.mark(player, "nb_craft")  # веха грамоты новосёла
        building = buildings.CATALOG["brewery"]
        await common.caption_edit(
            callback.message,
            texts.production_screen(building, player, player.tavern),
            kb.production_kb(player, player.tavern, building),
        )
        await callback.answer(texts.brew_claimed(outcome, tier, qty), show_alert=True)
        return
    await callback.answer()
