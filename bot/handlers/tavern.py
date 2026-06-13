"""Экран таверны и действия игрока."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import balance, logic
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


async def _safe_edit(callback: CallbackQuery, text: str, markup) -> None:
    """Правит текст или подпись к фото — смотря что за сообщение."""
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        # Текст не изменился — Telegram не любит одинаковые edit
        pass


async def _show_tavern(callback: CallbackQuery, player: Player) -> None:
    """Экран таверны в том же окне: возвращает картинку таверны (например,
    после склада с его собственным фото). Если сообщение без фото — пересоздаёт."""
    await common.show_tavern_panel(
        callback.message, player, callback.from_user.id
    )


async def _get_player(
    callback: CallbackQuery, session: AsyncSession, *, lock: bool = False
) -> Player | None:
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


@router.callback_query(F.data == "tavern")
async def cb_tavern(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    await _show_tavern(callback, player)
    await callback.answer()


@router.callback_query(F.data == "warehouse")
async def cb_warehouse(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    await common.show_warehouse_panel(callback.message, player, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "exp_menu")
async def cb_exp_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    state, minutes = logic.expedition_state(player)
    if state == "active":
        await callback.answer(
            texts.expedition_in_progress(minutes), show_alert=True
        )
        return
    if state == "ready":
        await callback.answer("Сначала забери добычу, раззява!", show_alert=True)
        return
    await _safe_edit(
        callback, texts.expedition_menu(player), kb.expedition_menu_kb(player)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("exp:"))
async def cb_exp_start(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    resource = callback.data.split(":", 1)[1]
    if resource not in balance.RESOURCE_NAMES:
        await callback.answer()
        return

    result = logic.start_expedition(player, resource)
    if not result.ok:
        if result.reason == "busy":
            await callback.answer("Работники уже горбатятся, не дёргай их!", show_alert=True)
        else:
            await callback.answer(
                texts.expedition_no_gold(result.pay, player.gold), show_alert=True
            )
        return

    await _safe_edit(
        callback, texts.expedition_started(resource, result.pay), kb.back_kb()
    )
    await callback.answer("Потопали!")


@router.callback_query(F.data == "exp_status")
async def cb_exp_status(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    state, minutes = logic.expedition_state(player)
    if state == "ready":
        # Пока кнопка висела, работники успели вернуться — обновим экран
        await _show_tavern(callback, player)
        await callback.answer("Уже приползли!")
        return
    await callback.answer(texts.expedition_in_progress(minutes), show_alert=True)


@router.callback_query(F.data == "exp_claim")
async def cb_exp_claim(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return

    result = logic.claim_expedition(player)
    if not result.ok:
        if result.reason == "not_ready":
            await callback.answer(
                texts.expedition_in_progress(result.minutes_left), show_alert=True
            )
        else:
            await callback.answer("Работники никуда не ходили. Глаза разуй.", show_alert=True)
        return

    await _safe_edit(
        callback,
        texts.expedition_claimed(result.resource, result.amount, result.lucky),
        kb.back_kb(),
    )
    await callback.answer(f"🍀 +{result.amount}!" if result.lucky else f"+{result.amount}")


@router.callback_query(F.data == "income")
async def cb_income(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return

    result = logic.collect_income(player, player.tavern)
    if not result.ok:
        await callback.answer(texts.income_empty(), show_alert=True)
        return

    await _safe_edit(callback, texts.income_success(result), kb.back_kb())
    await callback.answer(f"+{result.gold} 🪙")


@router.callback_query(F.data == "upgrade")
async def cb_upgrade(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return

    tavern = player.tavern
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
    player = await _get_player(callback, session, lock=True)
    if player is None:
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

    # Если у нового уровня другая картинка — показываем её
    new_img = images.tavern_image(result.new_level)
    old_img = images.tavern_image(result.new_level - 1)
    success_text = texts.upgrade_success(result.new_level)
    if callback.message.photo and new_img is not None and new_img != old_img:
        try:
            await callback.message.edit_media(
                InputMediaPhoto(
                    media=FSInputFile(new_img),
                    caption=success_text,
                    parse_mode="HTML",
                ),
                reply_markup=kb.back_kb(),
            )
        except TelegramBadRequest:
            await _safe_edit(callback, success_text, kb.back_kb())
    else:
        await _safe_edit(callback, success_text, kb.back_kb())
    await callback.answer("Отгрохал! 🔨")
