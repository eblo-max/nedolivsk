"""Экран таверны и действия игрока."""

import random
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from bot import effects, images, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import (
    balance, economy, logic, newbie, perks, season, story_engine, story_state,
)
from bot.game import city as citymod
from bot.game import trade as trademod
from bot.game import world as wld
from bot.handlers import common, story
from bot.handlers import trade as trade_h
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


async def _kassa(callback: CallbackQuery, text: str, markup) -> None:
    """Экран кассы/сбора дохода на картинке dohod_sobrat (морфит панель)."""
    await common.show_image_panel(
        callback.message, images.named_image("dohod_sobrat"),
        text, markup, callback.from_user.id)


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


@router.callback_query(F.data == "more")
async def cb_more(callback: CallbackQuery, session: AsyncSession) -> None:
    """Подменю «⋯ Ещё» — меняем только клавиатуру (экран таверны остаётся)."""
    player = await _get_player(callback, session)
    if player is None:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.tavern_more_kb(player))
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "dmnews")
async def cb_dmnews(callback: CallbackQuery, session: AsyncSession) -> None:
    """Одиночка переключает вести мира в ЛС (подкидыши и так шлём всем без группы)."""
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    player.dm_news = not bool(player.dm_news)
    await _show_tavern(callback, player)
    await callback.answer(
        "🌍 Вести мира теперь приходят в ЛС!" if player.dm_news
        else "Вести мира в ЛС выключены.", show_alert=True)


@router.callback_query(F.data == "newbie")
async def cb_newbie(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session)
    if player is None:
        return
    await _safe_edit(callback, texts.newbie_screen(player, player.tavern),
                     kb.newbie_kb(player))
    await callback.answer()


@router.callback_query(F.data == "newbie_claim")
async def cb_newbie_claim(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    total = newbie.claim_all(player, player.tavern)
    await _safe_edit(callback, texts.newbie_screen(player, player.tavern),
                     kb.newbie_kb(player))
    if total:
        repo.add_log(session, "player", player.id,
                     f"📜 забрал награды грамоты: {sum(total.values())} ед.")
        await effects.react_msg(callback.message, "🎉")
    await callback.answer(texts.newbie_claimed(total), show_alert=True)


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
    newbie.mark(player, "nb_brigade")  # веха грамоты новосёла

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
        await callback.answer("Бригады ещё в пути — на экране видно, сколько им топать. "
                              "Загляни позже за добычей.", show_alert=True)
        return

    await _safe_edit(callback, texts.expedition_claimed(claimed), kb.back_kb())
    total = sum(a for _, a, _ in claimed)
    await callback.answer(f"+{total} на склад")


@router.callback_query(F.data == "income")
async def cb_income(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return

    pending = story_state.get_retail(player)
    if pending:  # уже висит нерешённый заказ — сперва реши его (не копим заново)
        await _kassa(callback, texts.retail_prompt(pending, player),
                     kb.retail_kb(logic.retail_total(pending, player)))
        await callback.answer()
        return

    now = datetime.now(timezone.utc)
    city = await repo.get_world_city(session)   # единый мир — ситуация общая
    ce = citymod.effects(city, player, now)  # эффект городской ситуации
    perk_demand = perks.demand_bonus(player)
    mood_factor = citymod.mood_factor(city)
    season_demand = season.demand_mult()

    result = logic.collect_income(
        player, player.tavern,
        demand_mult=(wld.demand_mult() * ce.demand_mult * perk_demand
                     * mood_factor * season_demand),
    )
    if not result.ok:
        await callback.answer(texts.income_empty(), show_alert=True)
        return

    result.fair = wld.is_fair()
    result.city_label = ce.label
    result.perk_demand = perk_demand
    result.mood_factor = mood_factor
    result.season_demand = season_demand
    hol = season.holiday()
    result.season_label = (
        f"{hol.emoji} {hol.name}" if hol
        else f"{season.current().emoji} {season.current().name}"
    )
    if ce.skim_pct and result.gold > 0:  # воры/корона снимают долю с пассива
        result.skim = int(result.gold * ce.skim_pct)
        player.gold -= result.skim
        economy.record(player, "skim", -result.skim)

    # Сбыт гостям — на ПОДТВЕРЖДЕНИЕ: показываем заказ, игрок решает наливать ли.
    if result.order:
        story_state.set_retail(player, result.order)
        await _kassa(callback, texts.income_success(result, player),
                     kb.retail_kb(logic.retail_total(result.order, player)))
        await callback.answer(f"Пассив +{result.gold - result.skim} 🪙")
        return

    await _kassa(callback, texts.income_success(result, player), kb.back_kb())
    await callback.answer(f"+{result.gold - result.skim} 🪙")

    owner = callback.from_user.id
    busy = story_state.get_pending(player) or story_state.get_trade(player)

    # Торг: на сбор дохода заглядывает купец (чаще и богаче на ярмарке).
    if not busy and trademod.has_sellable(player.tavern):
        chance = (balance.TRADE_FAIR_CHANCE if wld.is_fair()
                  else balance.TRADE_CHANCE)
        if random.random() < chance:
            world = await repo.get_or_create_world(session)
            offer = trademod.make_offer(
                player.tavern, player, wld.is_fair(), world=world)
            if offer is not None:
                story_state.set_trade(player, offer)
                await trade_h.deliver_trade(callback.message, player, owner)
                busy = True

    # Живой город: иначе иногда заглядывает «гость» с событием.
    if not busy and story_engine.maybe_spawn(player, city, now) is not None:
        await story.deliver_pending(callback.message, player, owner)


@router.callback_query(F.data == "retail_open")
async def cb_retail_open(callback: CallbackQuery, session: AsyncSession) -> None:
    """Вернуться к заказу гостей (кнопка «Гости ждут заказ»)."""
    player = await _get_player(callback, session)
    if player is None:
        return
    want = story_state.get_retail(player)
    if not want:
        await callback.answer("Гости уже разошлись.", show_alert=True)
        return
    await _safe_edit(callback, texts.retail_prompt(want, player),
                     kb.retail_kb(logic.retail_total(want, player)))
    await callback.answer()


@router.callback_query(F.data == "retail_sell")
async def cb_retail_sell(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    want = story_state.get_retail(player)
    if not want:
        await callback.answer("Гости уже разошлись.", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    city = await repo.get_world_city(session)   # единый мир
    sold, gold, rep, noble_raw = logic.apply_retail(player, player.tavern, want)
    story_state.set_retail(player, None)
    if not sold:
        await _safe_edit(callback, texts.retail_held(), kb.back_kb())
        await callback.answer("Товар разошёлся или скис.")
        return
    newbie.mark(player, "nb_sale")  # веха грамоты новосёла
    skim = 0
    ce = citymod.effects(city, player, now)
    if ce.skim_pct and gold > 0:  # воры/корона снимают долю и со сбыта
        skim = int(gold * ce.skim_pct)
        player.gold -= skim
        economy.record(player, "skim", -skim)
    # Розница НЕ трогает единый оптовый рынок: гости пьют в своей таверне —
    # конечное потребление, замкнутый локальный контур.
    _msg = texts.retail_sold(sold, gold, rep, skim, logic.retail_rep_left(player.tavern))
    _tip = int(noble_raw["tip"]) if noble_raw else 0
    if noble_raw:  # 🎩 знатный гость отсыпал чаевые сверх — отдельной строкой
        _msg += "\n\n" + texts.retail_noble_line(noble_raw["i"], _tip)
    await _safe_edit(callback, _msg, kb.back_kb())
    await callback.answer(f"+{gold - skim + _tip} 🪙")


@router.callback_query(F.data == "retail_hold")
async def cb_retail_hold(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _get_player(callback, session, lock=True)
    if player is None:
        return
    story_state.set_retail(player, None)
    await _safe_edit(callback, texts.retail_held(), kb.back_kb())
    await callback.answer()


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
        callback, texts.upgrade_offer(player, tavern, cost), kb.upgrade_confirm_kb()
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
                callback, texts.upgrade_not_enough(result.cost, player),
                kb.upgrade_short_kb()
            )
            await callback.answer()
        return
    repo.add_log(session, "player", player.id,
                 f"🔨 улучшил таверну до ур.{result.new_level}")

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
    await effects.react_msg(callback.message, "🔥", big=True)   # веха — пусть искрит
