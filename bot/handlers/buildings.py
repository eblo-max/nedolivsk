"""Экран пристроек: постройка зданий (Ярус 1 — производство)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.db.models import Player
from bot.game import buildings
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


@router.callback_query(F.data == "buildings")
async def cb_buildings(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    done = buildings.finalize_build(player, player.tavern)  # ленивое завершение
    await common.caption_edit(
        callback.message,
        texts.buildings_screen(player, player.tavern),
        kb.buildings_kb(player, player.tavern),
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
    await common.caption_edit(
        callback.message,
        texts.building_detail(building, player, player.tavern),
        kb.building_detail_kb(player, player.tavern, building),
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
            }.get(result.reason, "Не вышло.")
            await callback.answer(alert, show_alert=True)
        return

    await common.caption_edit(
        callback.message,
        texts.build_started(result.building, result.hours),
        kb.buildings_back_kb(),
    )
    await callback.answer("Заложили фундамент!")
