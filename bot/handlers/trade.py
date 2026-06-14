"""Торг с заезжими купцами: показ предложения и резолв сделки."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import balance, market, story_state, trade
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


def _trade_image(offer: dict):
    """Картинка торга: портрет по сословию → общий фон торга → ярмарка.
    Чтобы оживить визуал, клади в assets: torg_<сословие>.png, torg.png."""
    for name in (f"torg_{offer.get('estate', '')}", "torg", "yarmarka"):
        p = images.named_image(name)
        if p is not None:
            return p
    return None


async def deliver_trade(message: Message, player: Player, owner_id: int) -> None:
    """Показать предложение купца новой панелью (в чате — за владельцем)."""
    offer = story_state.get_trade(player)
    if offer is None:
        return
    text = texts.trade_offer(offer)
    markup = kb.trade_kb(offer)
    img = _trade_image(offer)
    if img is not None:
        msg = await message.answer_photo(
            common.cached_media(img), caption=text, reply_markup=markup)
        common.remember_file_id(img, msg)
    else:
        msg = await message.answer(text, reply_markup=markup)
    panels.claim(msg, owner_id)


async def _edit(callback: CallbackQuery, text: str, markup=None) -> None:
    """Правит подпись к фото или текст — смотря чем доставлен торг."""
    await common.caption_edit(callback.message, text, markup)


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
        market.nudge(city, offer["good"],  # оптовый сброс — полный сигнал предложения
                     qty * balance.MARKET_WHOLESALE_WEIGHT)
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
