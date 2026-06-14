"""Торг с заезжими купцами: показ предложения и резолв сделки."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import market, story_state, trade
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
    """Применить продажу: (qty, gold). Списывает товар, золото, растит имя торговца."""
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
    story_state.adjust_faction(player, "merchants", 1)  # доброе имя у купцов
    return qty, gold


async def _finish_sale(callback: CallbackQuery, player: Player, offer: dict,
                       unit: int, kind: str, city=None) -> None:
    qty, gold = _sell(player, offer, unit)
    story_state.set_trade(player, None)
    if qty:
        market.add_supply(city, offer["good"], qty)  # партия давит рынок
        react = trade.reaction(offer, kind)
        await _edit(callback, texts.trade_sold(offer, qty, unit, gold, react),
                    kb.back_kb())
        await callback.answer(f"+{gold} 🪙")
    else:
        await _edit(callback, texts.trade_walked(offer, trade.reaction(offer, "walk")),
                    kb.back_kb())
        await callback.answer()


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

    city = None
    if player.chat_id is not None:
        city = await repo.get_or_create_city(session, player.chat_id)

    arg = callback.data.split(":", 1)[1]

    if arg == "no":
        story_state.set_trade(player, None)
        await _edit(callback, texts.trade_cancelled(), kb.back_kb())
        await callback.answer()
        return

    if arg == "ok":  # согласие на контр-цену
        unit = int(offer.get("counter", offer["max_unit"]))
        kind = "accept_high" if unit >= offer["fv"] * 1.15 else "accept"
        await _finish_sale(callback, player, offer, unit, kind, city)
        return

    if arg == "push":  # дожать контр-цену
        decision, price = trade.push(offer)
        if decision == "walk":
            story_state.set_trade(player, None)
            await _edit(callback,
                        texts.trade_walked(offer, trade.reaction(offer, "walk")),
                        kb.back_kb())
        else:  # concede | hold
            offer["counter"] = price
            story_state.set_trade(player, offer)
            react = trade.reaction(offer, decision, price)
            await _edit(callback, texts.trade_counter(offer, react),
                        kb.trade_counter_kb(price))
        await callback.answer()
        return

    if not arg.isdigit() or int(arg) >= len(offer["prices"]):
        await callback.answer()
        return

    unit = offer["prices"][int(arg)]
    decision, price = trade.evaluate(offer, unit)
    if decision == "accept":
        kind = "accept_high" if unit >= offer["fv"] * 1.15 else "accept"
        await _finish_sale(callback, player, offer, unit, kind, city)
    elif decision == "counter":
        offer["counter"] = price
        story_state.set_trade(player, offer)
        react = trade.reaction(offer, "counter", price)
        await _edit(callback, texts.trade_counter(offer, react),
                    kb.trade_counter_kb(price))
        await callback.answer()
    else:  # walk
        story_state.set_trade(player, None)
        await _edit(callback,
                    texts.trade_walked(offer, trade.reaction(offer, "walk")),
                    kb.back_kb())
        await callback.answer()
