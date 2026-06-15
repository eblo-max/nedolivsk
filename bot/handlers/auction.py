"""Аукцион: выставление лота и просмотр торгов (асинхронный сбыт)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import auction, balance, bourse, market
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


# ── Городская биржа (P2P): двусторонний ордербук ────────────────────────────
def _chat_id(callback: CallbackQuery, player: Player) -> int | None:
    return (callback.message.chat.id if panels.is_group(callback.message)
            else player.chat_id)


async def _names(session: AsyncSession, orders) -> dict:
    ids = [o.seller_id for o in orders]
    if not ids:
        return {}
    rows = (await session.execute(
        select(Player.id, Player.first_name).where(Player.id.in_(ids)))).all()
    return {i: n for i, n in rows}


async def _render_list(callback: CallbackQuery, session: AsyncSession,
                       player: Player, side: str, cat: str, page: int) -> None:
    chat_id = _chat_id(callback, player)
    goods = bourse.category_goods(cat)
    total = await repo.count_open_orders(session, chat_id, player.id, side, goods=goods)
    orders = await repo.open_orders(
        session, chat_id, player.id, side, goods=goods,
        limit=balance.BOURSE_PAGE, offset=page * balance.BOURSE_PAGE)
    names = await _names(session, orders)
    await common.caption_edit(
        callback.message, texts.bourse_list(orders, names, page, total, cat, side),
        kb.bourse_list_kb(orders, page, total, cat, side))


def _parse_list_cb(data: str) -> tuple[int, str]:
    parts = data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    cat = parts[2] if len(parts) > 2 else "all"
    return page, cat


@router.callback_query(F.data.startswith("bourse:"))
async def cb_sell_list(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа — в общем чате. Заходи через «гг».", show_alert=True)
        return
    page, cat = _parse_list_cb(callback.data)
    await _render_list(callback, session, player, "sell", cat, page)
    await callback.answer()


@router.callback_query(F.data.startswith("blb:"))
async def cb_buy_list(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа — в общем чате. Заходи через «гг».", show_alert=True)
        return
    page, cat = _parse_list_cb(callback.data)
    await _render_list(callback, session, player, "buy", cat, page)
    await callback.answer()


@router.callback_query(F.data.startswith("bord:"))
async def cb_sell_order(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0 or order.side != "sell":
        await callback.answer("Лот уже разобрали.", show_alert=True)
        return
    owner = await repo.get_player(session, order.seller_id)
    best_bid = await repo.best_price(session, _chat_id(callback, player),
                                     order.good, "buy")
    await common.caption_edit(
        callback.message,
        texts.bourse_order(order, owner.first_name if owner else "кто-то",
                           player, best_bid),
        kb.bourse_order_kb(order, player))
    await callback.answer()


@router.callback_query(F.data.startswith("bbid:"))
async def cb_buy_order(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0 or order.side != "buy":
        await callback.answer("Заявку уже закрыли.", show_alert=True)
        return
    owner = await repo.get_player(session, order.seller_id)
    best_ask = await repo.best_price(session, _chat_id(callback, player),
                                     order.good, "sell")
    await common.caption_edit(
        callback.message,
        texts.bourse_bid(order, owner.first_name if owner else "кто-то",
                         player.tavern, best_ask),
        kb.bourse_bid_kb(order, player.tavern))
    await callback.answer()


@router.callback_query(F.data.startswith("bbuy:"))
async def cb_buy_from_sell(callback: CallbackQuery, session: AsyncSession) -> None:
    """Купить из лота продажи: золото покупателя → товар в погреб, золото продавцу."""
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, oid, qarg = callback.data.split(":")
    order = await repo.get_order(session, int(oid), lock=True)
    if order is None or order.qty <= 0 or order.side != "sell":
        await callback.answer("Лот уже разобрали.", show_alert=True)
        return
    if order.seller_id == player.id:
        await callback.answer("Это твой лот.", show_alert=True)
        return
    want = order.qty if qarg == "all" else int(qarg)
    qty = max(0, min(want, order.qty,
                     player.gold // order.unit_price if order.unit_price else 0))
    if qty <= 0:
        await callback.answer("Не хватает золота.", show_alert=True)
        return
    cost = qty * order.unit_price
    good, nm = order.good, _gname(order.good)
    player.gold -= cost
    _give(player.tavern, good, qty)
    net = bourse.net_to_seller(cost)
    seller = await repo.get_player(session, order.seller_id, for_update=True)
    if seller is not None:
        seller.gold += net
        repo.add_log(session, "player", seller.id,
                     f"🏪 продал на бирже {qty}×{nm} за {net}🪙")
        repo.queue_notify(session, seller.id,
                          f"🛒 На бирже купили твой товар: {qty}×{nm} → +{net} 🪙")
    order.qty -= qty
    if order.qty <= 0:
        await repo.delete_order(session, order.id)
    repo.add_log(session, "player", player.id, f"🏪 купил на бирже {qty}×{nm} за {cost}🪙")
    await _market_nudge(session, _chat_id(callback, player), good, qty)
    await _render_list(callback, session, player, "sell", "all", 0)
    await callback.answer(f"Куплено {qty}×{nm} за {cost}🪙")


@router.callback_query(F.data.startswith("bfill:"))
async def cb_fill_buy(callback: CallbackQuery, session: AsyncSession) -> None:
    """Продать в заявку «куплю»: товар из погреба → покупателю, золото из залога."""
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, oid, qarg = callback.data.split(":")
    order = await repo.get_order(session, int(oid), lock=True)
    if order is None or order.qty <= 0 or order.side != "buy":
        await callback.answer("Заявку уже закрыли.", show_alert=True)
        return
    if order.seller_id == player.id:
        await callback.answer("Это твоя заявка.", show_alert=True)
        return
    # Владелец заявки должен существовать и иметь погреб — иначе товар «в никуда».
    buyer = await repo.get_player(session, order.seller_id, for_update=True)
    if buyer is None or buyer.tavern is None:
        await repo.delete_order(session, order.id)  # протухшая сиротская заявка
        await callback.answer("Заявка протухла — хозяин сгинул.", show_alert=True)
        await _render_list(callback, session, player, "buy", "all", 0)
        return
    good, nm = order.good, _gname(order.good)
    stock = int((player.tavern.products or {}).get(good, 0))
    want = order.qty if qarg == "all" else int(qarg)
    qty = max(0, min(want, order.qty, stock))
    if qty <= 0:
        await callback.answer("Нет столько товара в погребе.", show_alert=True)
        return
    gross = qty * order.unit_price
    net = bourse.net_to_seller(gross)
    bourse.freeze(player.tavern, good, qty)   # списать у продавца
    player.gold += net                        # ему — за вычетом налога
    _give(buyer.tavern, good, qty)            # товар покупателю (из залога оплачено)
    repo.queue_notify(session, buyer.id,
                      f"📥 По твоей заявке доставили {qty}×{nm} "
                      f"(из залога списано {gross} 🪙)")
    repo.add_log(session, "player", buyer.id, f"📥 заявка: получил {qty}×{nm}")
    order.qty -= qty
    if order.qty <= 0:
        await repo.delete_order(session, order.id)
    repo.add_log(session, "player", player.id,
                 f"🏪 продал по заявке {qty}×{nm} за {net}🪙")
    await _market_nudge(session, _chat_id(callback, player), good, qty)
    await _render_list(callback, session, player, "buy", "all", 0)
    await callback.answer(f"Продано {qty}×{nm} → +{net}🪙")


# ── Создание лота продажи ───────────────────────────────────────────────────
@router.callback_query(F.data == "bsell")
async def cb_sell_new(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа — в общем чате. Заходи через «гг».", show_alert=True)
        return
    n = await repo.count_seller_orders(session, player.id, "sell")
    if n >= balance.BOURSE_MAX_ORDERS:
        await callback.answer(f"Лимит лотов продажи ({balance.BOURSE_MAX_ORDERS}).",
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
async def cb_sell_good(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    stock = int((player.tavern.products or {}).get(good, 0))
    if stock <= 0:
        await callback.answer("Этого товара уже нет.", show_alert=True)
        return
    await common.caption_edit(callback.message, texts.bourse_pick_qty(good, stock),
                              kb.bourse_sell_qty_kb(good, stock))
    await callback.answer()


@router.callback_query(F.data.startswith("bsq:"))
async def cb_sell_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    _, good, q = callback.data.split(":")
    await common.caption_edit(
        callback.message, texts.bourse_pick_price(good, int(q)),
        kb.bourse_sell_price_kb(good, int(q), bourse.price_tiers(good)))
    await callback.answer()


@router.callback_query(F.data.startswith("bsp:"))
async def cb_sell_create(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, good, q, idx = callback.data.split(":")
    qty, idx = min(int(q), balance.BOURSE_QTY_MAX), int(idx)
    chat_id = _chat_id(callback, player)
    if chat_id is None:
        await callback.answer("Биржа — в общем чате.", show_alert=True)
        return
    prices = bourse.price_tiers(good)
    if not 0 <= idx < len(prices):
        await callback.answer()
        return
    price = prices[idx]
    stock = int((player.tavern.products or {}).get(good, 0))
    qty = min(qty, stock)
    if qty <= 0 or not bourse.valid_price(good, price):
        await callback.answer("Не вышло выставить (товар/цена).", show_alert=True)
        return
    nm = _gname(good)
    matched = await _match_sell(session, player, chat_id, good, qty, price)  # авто-сведение
    remaining = qty - matched
    listed = 0
    if remaining > 0:
        if await repo.count_seller_orders(session, player.id, "sell") < balance.BOURSE_MAX_ORDERS:
            bourse.freeze(player.tavern, good, remaining)
            repo.create_order(session, chat_id, player.id, good, remaining, price, side="sell")
            listed = remaining
    if matched:
        await _market_nudge(session, chat_id, good, matched)
    repo.add_log(session, "player", player.id,
                 f"📤 продажа {qty}×{nm} по {price}🪙 (свёл {matched}, выставил {listed})")
    await _back_auction(callback, session, player)
    parts = []
    if matched:
        parts.append(f"свёл сразу {matched}")
    if listed:
        parts.append(f"выставил {listed}")
    if remaining and not listed:
        parts.append(f"{remaining} осталось в погребе (лимит лотов)")
    await callback.answer(f"{nm}: " + (", ".join(parts) if parts else "ничего"))


# ── Создание заявки «куплю» ─────────────────────────────────────────────────
@router.callback_query(F.data == "bbidnew")
async def cb_bid_new(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа — в общем чате. Заходи через «гг».", show_alert=True)
        return
    n = await repo.count_seller_orders(session, player.id, "buy")
    if n >= balance.BOURSE_MAX_ORDERS:
        await callback.answer(f"Лимит заявок ({balance.BOURSE_MAX_ORDERS}).",
                              show_alert=True)
        return
    await common.caption_edit(
        callback.message, texts.bourse_bid_intro(player, balance.BOURSE_MAX_ORDERS - n),
        kb.bourse_bid_goods_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("bbg:"))
async def cb_bid_good(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    max_qty = min(balance.BOURSE_QTY_MAX, player.gold // bourse.price_floor(good))
    if max_qty <= 0:
        await callback.answer("Маловато золота даже на одну штуку.", show_alert=True)
        return
    await common.caption_edit(callback.message, texts.bourse_bid_qty(good, max_qty),
                              kb.bourse_bid_qty_kb(good, max_qty))
    await callback.answer()


@router.callback_query(F.data.startswith("bbq:"))
async def cb_bid_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    _, good, q = callback.data.split(":")
    await common.caption_edit(
        callback.message, texts.bourse_pick_price(good, int(q), buy=True),
        kb.bourse_bid_price_kb(good, int(q), bourse.price_tiers(good)))
    await callback.answer()


@router.callback_query(F.data.startswith("bbp:"))
async def cb_bid_create(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, good, q, idx = callback.data.split(":")
    qty, idx = min(int(q), balance.BOURSE_QTY_MAX), int(idx)
    chat_id = _chat_id(callback, player)
    if chat_id is None:
        await callback.answer("Биржа — в общем чате.", show_alert=True)
        return
    prices = bourse.price_tiers(good)
    if not 0 <= idx < len(prices):
        await callback.answer()
        return
    price = prices[idx]
    if not bourse.valid_price(good, price) or qty <= 0:
        await callback.answer("Цена/кол-во вне правил.", show_alert=True)
        return
    nm = _gname(good)
    matched, remaining = await _match_buy(session, player, chat_id, good, qty, price)
    listed = 0
    if remaining > 0:  # остаток — в залог и в книгу
        affordable = player.gold // price if price > 0 else 0
        listed = min(remaining, affordable)
        if listed > 0 and await repo.count_seller_orders(
                session, player.id, "buy") < balance.BOURSE_MAX_ORDERS:
            player.gold -= listed * price
            repo.create_order(session, chat_id, player.id, good, listed, price, side="buy")
        else:
            listed = 0
    if matched:
        await _market_nudge(session, chat_id, good, matched)
    repo.add_log(session, "player", player.id,
                 f"📣 куплю {qty}×{nm} по {price}🪙 (свёл {matched}, заявка {listed})")
    await _back_auction(callback, session, player)
    parts = []
    if matched:
        parts.append(f"купил сразу {matched}")
    if listed:
        parts.append(f"заявка на {listed} (залог {listed * price}🪙)")
    await callback.answer(f"{nm}: " + (", ".join(parts) if parts else "ничего не вышло"))


# ── Мои лоты / отмена ───────────────────────────────────────────────────────
@router.callback_query(F.data == "bprices")
async def cb_prices(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    chat_id = _chat_id(callback, player)
    if chat_id is None:
        await callback.answer("Биржа — в общем чате. Заходи через «гг».", show_alert=True)
        return
    board = await repo.market_summary(session, chat_id)
    await common.caption_edit(callback.message, texts.bourse_prices(board),
                              kb.bourse_prices_kb())
    await callback.answer()


@router.callback_query(F.data == "bmine")
async def cb_mine(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    orders = await repo.seller_orders(session, player.id)
    await common.caption_edit(callback.message, texts.bourse_mine(orders),
                              kb.bourse_mine_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("bcancel:"))
async def cb_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]), lock=True)
    if order is None or order.seller_id != player.id:
        await callback.answer("Лот не найден.", show_alert=True)
        return
    if order.side == "sell":
        bourse.unfreeze(player.tavern, order.good, order.qty)
        note = "товар вернулся в погреб"
    else:
        player.gold += order.qty * order.unit_price  # вернуть залог
        note = f"залог {order.qty * order.unit_price}🪙 вернулся"
    await repo.delete_order(session, order.id)
    orders = await repo.seller_orders(session, player.id)
    await common.caption_edit(callback.message, texts.bourse_mine(orders),
                              kb.bourse_mine_kb(orders))
    await callback.answer(f"Лот снят, {note}.")


# ── Общие помощники биржи ───────────────────────────────────────────────────
def _gname(good: str) -> str:
    return prod.GOODS[good].name if good in prod.GOODS else good


def _give(tavern, good: str, qty: int) -> None:
    prods = dict(tavern.products or {})
    prods[good] = int(prods.get(good, 0)) + qty
    tavern.products = prods


async def _match_sell(session: AsyncSession, player: Player, chat_id: int,
                      good: str, qty: int, ask: int) -> int:
    """Свести новую ПРОДАЖУ со встречными заявками «куплю» (цена >= ask, дороже
    первыми). Сделка по цене заявки (maker). Возвращает сведённое количество."""
    nm = _gname(good)
    remaining = qty
    bids = await repo.best_buy_orders(session, chat_id, good, ask, player.id,
                                      limit=balance.BOURSE_MATCH_MAX)
    for bo in bids:
        if remaining <= 0:
            break
        if bo.qty <= 0:
            continue
        buyer = await repo.get_player(session, bo.seller_id, for_update=True)
        if buyer is None or buyer.tavern is None:  # сиротская заявка — снести
            await repo.delete_order(session, bo.id)
            continue
        k = min(remaining, bo.qty)
        gross = k * bo.unit_price            # по цене заявки
        net = bourse.net_to_seller(gross)
        bourse.freeze(player.tavern, good, k)  # списать у продавца
        player.gold += net
        _give(buyer.tavern, good, k)           # покупателю (оплачено из залога)
        repo.queue_notify(session, buyer.id,
                          f"📥 По твоей заявке свели {k}×{nm} (из залога {gross} 🪙)")
        repo.add_log(session, "player", buyer.id, f"📥 заявка свелась: {k}×{nm}")
        bo.qty -= k
        if bo.qty <= 0:
            await repo.delete_order(session, bo.id)
        remaining -= k
    return qty - remaining


async def _match_buy(session: AsyncSession, player: Player, chat_id: int,
                     good: str, qty: int, bid: int) -> tuple[int, int]:
    """Свести новую ЗАЯВКУ «куплю» со встречными лотами продажи (цена <= bid,
    дешевле первыми). Сделка по цене лота. (сведено, остаток)."""
    nm = _gname(good)
    remaining = qty
    asks = await repo.best_sell_orders(session, chat_id, good, bid, player.id,
                                       limit=balance.BOURSE_MATCH_MAX)
    for so in asks:
        if remaining <= 0:
            break
        if so.qty <= 0:
            continue
        ask = so.unit_price
        k = min(remaining, so.qty, player.gold // ask if ask > 0 else 0)
        if k <= 0:
            if player.gold < ask:
                break          # на самый дешёвый уже не хватает
            continue
        cost = k * ask
        net = bourse.net_to_seller(cost)
        player.gold -= cost
        _give(player.tavern, good, k)         # товар из замороженного лота → покупателю
        seller = await repo.get_player(session, so.seller_id, for_update=True)
        if seller is not None:
            seller.gold += net
            repo.queue_notify(session, seller.id,
                              f"🛒 Твой лот свели на бирже: {k}×{nm} → +{net} 🪙")
            repo.add_log(session, "player", seller.id, f"🛒 лот свёлся: {k}×{nm}")
        so.qty -= k
        if so.qty <= 0:
            await repo.delete_order(session, so.id)
        remaining -= k
    return qty - remaining, remaining


async def _market_nudge(session: AsyncSession, chat_id: int | None,
                        good: str, qty: int) -> None:
    """P2P-сделка двигает оптовую цену чата (мягкий сигнал изобилия)."""
    if chat_id is None or qty <= 0:
        return
    city = await repo.get_or_create_city(session, chat_id)
    market.nudge(city, good, qty * balance.MARKET_P2P_WEIGHT)


async def _back_auction(callback: CallbackQuery, session: AsyncSession,
                        player: Player) -> None:
    city = await _city(callback, session, player)
    await common.show_image_panel(
        callback.message, images.named_image("auction"),
        texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern), callback.from_user.id)
