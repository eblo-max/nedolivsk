"""Экран таверны и действия игрока."""

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from bot import autoclean, images, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import balance, logic, perks, story_engine
from bot.game import city as citymod
from bot.game import world as wld
from bot.handlers import common, story
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


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    # Правила длиннее лимита подписи к фото — шлём отдельным сообщением.
    msg = await callback.message.answer(texts.RULES)
    autoclean.schedule_message(msg)  # в группе подчистится, в личке останется
    await callback.answer()


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
    await common.show_image_panel(
        callback.message,
        images.named_image("brigada"),
        texts.expedition_menu(player),
        kb.expedition_menu_kb(player),
        callback.from_user.id,
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

    result = logic.start_expedition(player, player.tavern, resource)
    if not result.ok:
        if result.reason == "no_slot":
            await callback.answer(texts.expedition_no_slot(), show_alert=True)
        else:
            await callback.answer(
                texts.expedition_no_gold(result.pay, player.gold), show_alert=True
            )
        return

    await _safe_edit(
        callback, texts.expedition_menu(player), kb.expedition_menu_kb(player)
    )
    await callback.answer(
        f"Бригада ушла за {balance.RESOURCE_NAMES[resource].lower()} (−{result.pay} 🪙)"
    )


@router.callback_query(F.data == "exp_claim")
async def cb_exp_claim(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return

    claimed = logic.claim_expeditions(player)
    if not claimed:
        await callback.answer("Бригады ещё не вернулись.", show_alert=True)
        return

    await _safe_edit(callback, texts.expedition_claimed(claimed), kb.back_kb())
    total = sum(a for _, a, _ in claimed)
    await callback.answer(f"+{total} на склад")


@router.callback_query(F.data == "income")
async def cb_income(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return

    now = datetime.now(timezone.utc)
    city = None
    if player.chat_id is not None:
        city = await repo.get_or_create_city(session, player.chat_id)
    ce = citymod.effects(city, player, now)  # эффект городской ситуации
    perk_demand = perks.demand_bonus(player)
    mood_factor = citymod.mood_factor(city)

    result = logic.collect_income(
        player, player.tavern,
        demand_mult=wld.demand_mult() * ce.demand_mult * perk_demand * mood_factor,
    )
    if not result.ok:
        await callback.answer(texts.income_empty(), show_alert=True)
        return

    result.fair = wld.is_fair()
    result.city_label = ce.label
    result.perk_demand = perk_demand
    result.mood_factor = mood_factor
    if ce.skim_pct and result.gold > 0:  # воры/корона снимают долю с выручки
        result.skim = int(result.gold * ce.skim_pct)
        player.gold -= result.skim

    await _safe_edit(callback, texts.income_success(result), kb.back_kb())
    await callback.answer(f"+{result.gold - result.skim} 🪙")

    # Живой город: иногда на сбор дохода заглядывает «гость» с событием.
    if story_engine.maybe_spawn(player, city, now) is not None:
        await story.deliver_pending(callback.message, player, callback.from_user.id)


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
