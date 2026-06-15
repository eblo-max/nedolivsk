"""Аукцион: выставление лота и просмотр торгов (асинхронный сбыт)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import auction, balance, bourse
from bot.game import production as prod
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


async def _player(callback: CallbackQuery, session: AsyncSession, *, lock: bool = False):
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


async def _city(callback: CallbackQuery, session: AsyncSession, player: Player):
    chat_id = callback.message.chat.id if panels.is_group(callback.message) \
        else player.chat_id
    return (await repo.get_or_create_city(session, chat_id)
            if chat_id is not None else None)


@router.callback_query(F.data == "auction")
async def cb_auction(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    city = await _city(callback, session, player)
    await common.show_image_panel(
        callback.message, images.named_image("auction"),
        texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern), callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "auc_new")
async def cb_auc_new(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if player.tavern.auction:
        await callback.answer("Лот уже на торгах — дождись конца или сними.",
                              show_alert=True)
        return
    if not auction.sellable_goods(player.tavern):
        await callback.answer("В погребе пусто — нечего выставлять.", show_alert=True)
        return
    await common.caption_edit(
        callback.message, "🔨 <b>ЧТО ВЫСТАВИМ?</b>\n\nВыбери товар из погреба:",
        kb.auction_goods_kb(player.tavern))
    await callback.answer()


@router.callback_query(F.data.startswith("aucg:"))
async def cb_auc_good(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    stock = int((player.tavern.products or {}).get(good, 0))
    if stock <= 0:
        await callback.answer("Этого товара уже нет.", show_alert=True)
        return
    city = await _city(callback, session, player)
    await common.caption_edit(
        callback.message, texts.auction_pick_qty(good, stock, city),
        kb.auction_qty_kb(good, stock))
    await callback.answer()


@router.callback_query(F.data.startswith("aucq:"))
async def cb_auc_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    _, good, qty_s = callback.data.split(":")
    qty = int(qty_s)
    city = await _city(callback, session, player)
    fv = auction.fair_value(city, good)
    prices = [max(1, round(fv * t)) for t in balance.AUCTION_PRICE_TIERS]
    await common.caption_edit(
        callback.message, texts.auction_pick_price(good, qty, city),
        kb.auction_price_kb(good, qty, prices))
    await callback.answer()


@router.callback_query(F.data.startswith("aucp:"))
async def cb_auc_price(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, good, qty_s, idx_s = callback.data.split(":")
    qty, idx = int(qty_s), int(idx_s)
    city = await _city(callback, session, player)
    fv = auction.fair_value(city, good)
    prices = [max(1, round(fv * t)) for t in balance.AUCTION_PRICE_TIERS]
    if not 0 <= idx < len(prices):
        await callback.answer()
        return
    ok, reason = auction.create(player, player.tavern, good, qty, prices[idx])
    if not ok:
        msg = {"busy": "Лот уже на торгах.", "empty": "Товара нет.",
               "price": "Неверная цена."}.get(reason, "Не вышло выставить.")
        await callback.answer(msg, show_alert=True)
        return
    await common.caption_edit(
        callback.message, texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern))
    await callback.answer("Лот выставлен — жди покупателей!")


@router.callback_query(F.data == "auc_cancel")
async def cb_auc_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    lot = player.tavern.auction or None
    if lot and lot.get("top_bid"):
        # есть ставка — предупреждаем, что упустит куш (но позволяем)
        pass
    if not auction.cancel(player, player.tavern):
        await callback.answer("Активных торгов нет.", show_alert=True)
        return
    city = await _city(callback, session, player)
    await common.caption_edit(
        callback.message, texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern))
    await callback.answer("Лот снят, товар вернулся в погреб.")


# ── Городская биржа (P2P) ───────────────────────────────────────────────────
def _chat_id(callback: CallbackQuery, player: Player) -> int | None:
    return (callback.message.chat.id if panels.is_group(callback.message)
            else player.chat_id)


async def _seller_names(session: AsyncSession, orders) -> dict:
    ids = [o.seller_id for o in orders]
    if not ids:
        return {}
    rows = (await session.execute(
        select(Player.id, Player.first_name).where(Player.id.in_(ids)))).all()
    return {i: n for i, n in rows}


async def _show_bourse(callback: CallbackQuery, session: AsyncSession,
                       player: Player, page: int) -> None:
    chat_id = _chat_id(callback, player)
    total = await repo.count_open_orders(session, chat_id, player.id)
    orders = await repo.open_orders(
        session, chat_id, player.id, balance.BOURSE_PAGE, page * balance.BOURSE_PAGE)
    names = await _seller_names(session, orders)
    await common.caption_edit(
        callback.message, texts.bourse_list(orders, names, page, total),
        kb.bourse_list_kb(orders, page, total))


@router.callback_query(F.data.startswith("bourse:"))
async def cb_bourse_list(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа работает в общем чате. Заходи через «гг».",
                              show_alert=True)
        return
    page = int(callback.data.split(":", 1)[1])
    await _show_bourse(callback, session, player, page)
    await callback.answer()


@router.callback_query(F.data.startswith("bord:"))
async def cb_bourse_order(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0:
        await callback.answer("Лот уже разобрали.", show_alert=True)
        return
    seller = await repo.get_player(session, order.seller_id)
    sname = seller.first_name if seller else "кто-то"
    await common.caption_edit(
        callback.message, texts.bourse_order(order, sname, player),
        kb.bourse_order_kb(order, player))
    await callback.answer()


@router.callback_query(F.data.startswith("bbuy:"))
async def cb_bourse_buy(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)  # лок покупателя (анти-overspend)
    if player is None:
        return
    _, oid, qarg = callback.data.split(":")
    order = await repo.get_order(session, int(oid), lock=True)  # лок лота (анти-дюп)
    if order is None or order.qty <= 0:
        await callback.answer("Лот уже разобрали.", show_alert=True)
        return
    if order.seller_id == player.id:
        await callback.answer("Это твой лот — себе не продашь.", show_alert=True)
        return
    want = order.qty if qarg == "all" else int(qarg)
    want = max(0, min(want, order.qty))
    afford = player.gold // order.unit_price if order.unit_price > 0 else 0
    qty = min(want, afford)
    if qty <= 0:
        await callback.answer("Не хватает золота даже на одну штуку.", show_alert=True)
        return
    cost = qty * order.unit_price
    good = order.good
    nm = prod.GOODS[good].name if good in prod.GOODS else good
    # перевод: золото у покупателя, товар в погреб, золото продавцу за вычетом налога
    player.gold -= cost
    prods = dict(player.tavern.products or {})
    prods[good] = prods.get(good, 0) + qty
    player.tavern.products = prods
    net = bourse.net_to_seller(cost)
    seller = await repo.get_player(session, order.seller_id, for_update=True)
    if seller is not None:
        seller.gold += net
        repo.add_log(session, "player", seller.id,
                     f"🏪 продал на бирже {qty}×{nm} за {net}🪙 "
                     f"(налог {bourse.tax_amount(cost)})")
    order.qty -= qty
    if order.qty <= 0:
        await repo.delete_order(session, order.id)
    repo.add_log(session, "player", player.id,
                 f"🏪 купил на бирже {qty}×{nm} за {cost}🪙")
    await _show_bourse(callback, session, player, 0)
    await callback.answer(f"Куплено {qty}×{nm} за {cost}🪙")


@router.callback_query(F.data == "bsell")
async def cb_bourse_sell(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа работает в общем чате. Заходи через «гг».",
                              show_alert=True)
        return
    n = await repo.count_seller_orders(session, player.id)
    if n >= balance.BOURSE_MAX_ORDERS:
        await callback.answer(
            f"Лимит лотов ({balance.BOURSE_MAX_ORDERS}). Сними что-нибудь сперва.",
            show_alert=True)
        return
    if not bourse.sellable_goods(player.tavern):
        await callback.answer("В погребе пусто — нечего выставлять.", show_alert=True)
        return
    await common.caption_edit(
        callback.message,
        texts.bourse_sell_intro(player.tavern, balance.BOURSE_MAX_ORDERS - n),
        kb.bourse_sell_goods_kb(player.tavern))
    await callback.answer()


@router.callback_query(F.data.startswith("bsg:"))
async def cb_bourse_sell_good(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    stock = int((player.tavern.products or {}).get(good, 0))
    if stock <= 0:
        await callback.answer("Этого товара уже нет.", show_alert=True)
        return
    await common.caption_edit(
        callback.message, texts.bourse_pick_qty(good, stock),
        kb.bourse_sell_qty_kb(good, stock))
    await callback.answer()


@router.callback_query(F.data.startswith("bsq:"))
async def cb_bourse_sell_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    _, good, q = callback.data.split(":")
    await common.caption_edit(
        callback.message, texts.bourse_pick_price(good, int(q)),
        kb.bourse_sell_price_kb(good, int(q), bourse.price_tiers(good)))
    await callback.answer()


@router.callback_query(F.data.startswith("bsp:"))
async def cb_bourse_sell_price(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, good, q, idx = callback.data.split(":")
    qty, idx = int(q), int(idx)
    chat_id = _chat_id(callback, player)
    if chat_id is None:
        await callback.answer("Биржа работает в общем чате.", show_alert=True)
        return
    if await repo.count_seller_orders(session, player.id) >= balance.BOURSE_MAX_ORDERS:
        await callback.answer("Лимит лотов достигнут.", show_alert=True)
        return
    prices = bourse.price_tiers(good)
    if not 0 <= idx < len(prices):
        await callback.answer()
        return
    price = prices[idx]
    qty = min(qty, balance.BOURSE_QTY_MAX)
    if not bourse.valid_price(good, price) or not bourse.freeze(player.tavern, good, qty):
        await callback.answer("Не вышло выставить (товар/цена).", show_alert=True)
        return
    repo.create_order(session, chat_id, player.id, good, qty, price)
    nm = prod.GOODS[good].name if good in prod.GOODS else good
    repo.add_log(session, "player", player.id,
                 f"📤 выставил на биржу {qty}×{nm} по {price}🪙")
    city = await _city(callback, session, player)
    await common.show_image_panel(
        callback.message, images.named_image("auction"),
        texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern), callback.from_user.id)
    await callback.answer(f"Лот выставлен: {qty}×{nm} по {price}🪙")


@router.callback_query(F.data == "bmine")
async def cb_bourse_mine(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    orders = await repo.seller_orders(session, player.id)
    await common.caption_edit(
        callback.message, texts.bourse_mine(orders), kb.bourse_mine_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("bcancel:"))
async def cb_bourse_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]), lock=True)
    if order is None or order.seller_id != player.id:
        await callback.answer("Лот не найден.", show_alert=True)
        return
    bourse.unfreeze(player.tavern, order.good, order.qty)
    await repo.delete_order(session, order.id)
    orders = await repo.seller_orders(session, player.id)
    await common.caption_edit(
        callback.message, texts.bourse_mine(orders), kb.bourse_mine_kb(orders))
    await callback.answer("Лот снят, товар вернулся в погреб.")
