"""Охота: выбор зверя и мгновенный бой по статам снаряги."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.db.models import Player
from bot.game import combat
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


async def _player(
    callback: CallbackQuery, session: AsyncSession, *, lock: bool = False
) -> Player | None:
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


@router.callback_query(F.data == "hunt")
async def cb_hunt(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    await common.caption_edit(
        callback.message, texts.hunt_menu(player), kb.hunt_menu_kb(player))
    await callback.answer()


@router.callback_query(F.data.startswith("hbeast:"))
async def cb_hunt_beast(callback: CallbackQuery, session: AsyncSession) -> None:
    """Бриф зверя: HP, расклад по статам, таблица добычи."""
    player = await _player(callback, session)
    if player is None:
        return
    enemy = combat.ENEMY.get(callback.data.split(":", 1)[1])
    if enemy is None:
        await callback.answer()
        return
    await common.caption_edit(
        callback.message, texts.hunt_detail(player, enemy),
        kb.hunt_detail_kb(enemy.id))
    await callback.answer()


@router.callback_query(F.data.startswith("hfight:"))
async def cb_hunt_fight(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    enemy_id = callback.data.split(":", 1)[1]
    res = combat.hunt(player, enemy_id)
    if not res.ok:
        if res.reason == "cooldown":
            await callback.answer(
                f"Ещё не оклемался — отдых до охоты {res.minutes_left} мин.",
                show_alert=True)
        else:
            await callback.answer()
        return
    await common.caption_edit(
        callback.message, texts.hunt_result(res), kb.hunt_after_kb())
    await callback.answer("🏹 Победа!" if res.fight.win else "🩸 Поражение…")
