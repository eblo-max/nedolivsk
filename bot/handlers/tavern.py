"""Экран таверны и действия игрока."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.game import logic
from bot.keyboards import inline as kb

router = Router()


async def _safe_edit(callback: CallbackQuery, text: str, markup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        # Текст не изменился — Telegram не любит одинаковые edit
        pass


@router.callback_query(F.data == "tavern")
async def cb_tavern(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if not player or not player.tavern:
        await callback.answer("Сначала создай таверну: /start", show_alert=True)
        return
    await _safe_edit(
        callback, texts.tavern_screen(player, player.tavern), kb.tavern_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "collect")
async def cb_collect(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if not player or not player.tavern:
        await callback.answer("Сначала создай таверну: /start", show_alert=True)
        return

    result = logic.collect_resources(player)
    if not result.ok:
        await callback.answer(
            texts.collect_cooldown(result.wait_minutes), show_alert=True
        )
        return

    await _safe_edit(callback, texts.collect_success(result.gained), kb.back_kb())
    await callback.answer("Собрано!")


@router.callback_query(F.data == "income")
async def cb_income(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if not player or not player.tavern:
        await callback.answer("Сначала создай таверну: /start", show_alert=True)
        return

    result = logic.collect_income(player, player.tavern)
    if not result.ok:
        await callback.answer(texts.income_empty(), show_alert=True)
        return

    await _safe_edit(callback, texts.income_success(result.gold), kb.back_kb())
    await callback.answer(f"+{result.gold} 🪙")


@router.callback_query(F.data == "upgrade")
async def cb_upgrade(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if not player or not player.tavern:
        await callback.answer("Сначала создай таверну: /start", show_alert=True)
        return

    tavern = player.tavern
    from bot.game import balance

    if tavern.level >= balance.MAX_LEVEL:
        await callback.answer(texts.UPGRADE_MAX, show_alert=True)
        return

    cost = balance.upgrade_cost(tavern.level)
    await _safe_edit(
        callback, texts.upgrade_offer(tavern, cost), kb.upgrade_confirm_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "upgrade_confirm")
async def cb_upgrade_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if not player or not player.tavern:
        await callback.answer("Сначала создай таверну: /start", show_alert=True)
        return

    result = logic.try_upgrade(player, player.tavern)
    if not result.ok:
        if result.reason == "max_level":
            await callback.answer(texts.UPGRADE_MAX, show_alert=True)
        else:
            await _safe_edit(
                callback, texts.upgrade_not_enough(result.cost, player), kb.back_kb()
            )
            await callback.answer()
        return

    await _safe_edit(callback, texts.upgrade_success(result.new_level), kb.back_kb())
    await callback.answer("Уровень повышен! 🎉")
