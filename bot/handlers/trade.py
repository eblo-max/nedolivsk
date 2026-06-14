"""Торг с заезжими купцами: показ предложения и резолв сделки."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import story_state, trade
from bot.keyboards import inline as kb

router = Router()


async def deliver_trade(message: Message, player: Player, owner_id: int) -> None:
    """Показать предложение купца новой панелью (в чате — за владельцем)."""
    offer = story_state.get_trade(player)
    if offer is None:
        return
    msg = await message.answer(texts.trade_offer(offer), reply_markup=kb.trade_kb(offer))
    panels.claim(msg, owner_id)


async def _edit(callback: CallbackQuery, text: str, markup=None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


def _sell(player: Player, offer: dict, unit: int) -> tuple[int, int]:
    """Применить продажу: вернуть (qty, gold). Списывает товар, добавляет золото."""
    tavern = player.tavern
    stock = int((tavern.products or {}).get(offer["good"], 0))
    qty = min(trade._qty_affordable(offer, unit), stock)
    if qty <= 0:
        return 0, 0
    gold = qty * unit
    prods = dict(tavern.products or {})
    prods[offer["good"]] = stock - qty
    tavern.products = prods
    player.gold += gold
    return qty, gold


@router.callback_query(F.data == "trade_open")
async def cb_trade_open(callback: CallbackQuery, session: AsyncSession) -> None:
    """Вернуться к торгу (кнопка «Купец торгуется»)."""
    player = await repo.get_player(session, callback.from_user.id)
    if player is None or story_state.get_trade(player) is None:
        await callback.answer("Купец уже ушёл.", show_alert=True)
        return
    await deliver_trade(callback.message, player, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("trd:"))
async def cb_trade(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id, for_update=True)
    if player is None:
        await callback.answer()
        return
    offer = story_state.get_trade(player)
    if offer is None:
        await callback.answer("Купец уже ушёл.", show_alert=True)
        return

    arg = callback.data.split(":", 1)[1]

    if arg == "no":
        story_state.set_trade(player, None)
        await _edit(callback, texts.trade_cancelled(), kb.back_kb())
        await callback.answer()
        return

    if arg == "ok":  # согласие на контр-цену
        unit = int(offer.get("counter", offer["max_unit"]))
        qty, gold = _sell(player, offer, unit)
        story_state.set_trade(player, None)
        if qty:
            await _edit(callback, texts.trade_sold(offer, qty, unit, gold), kb.back_kb())
            await callback.answer(f"+{gold} 🪙")
        else:
            await _edit(callback, texts.trade_walked(offer), kb.back_kb())
            await callback.answer()
        return

    if not arg.isdigit() or int(arg) >= len(offer["prices"]):
        await callback.answer()
        return

    unit = offer["prices"][int(arg)]
    decision, price = trade.evaluate(offer, unit)
    if decision == "accept":
        qty, gold = _sell(player, offer, price)
        story_state.set_trade(player, None)
        if qty:
            await _edit(callback, texts.trade_sold(offer, qty, price, gold), kb.back_kb())
            await callback.answer(f"+{gold} 🪙")
        else:
            await _edit(callback, texts.trade_walked(offer), kb.back_kb())
            await callback.answer()
    elif decision == "counter":
        offer["counter"] = price
        story_state.set_trade(player, offer)
        await _edit(callback, texts.trade_counter(offer, price),
                    kb.trade_counter_kb(price))
        await callback.answer()
    else:  # walk
        story_state.set_trade(player, None)
        await _edit(callback, texts.trade_walked(offer), kb.back_kb())
        await callback.answer()
