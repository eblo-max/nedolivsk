"""Аукцион: выставление лота и просмотр торгов (асинхронный сбыт)."""

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import auction, balance, bourse, logic, market
from bot.game import production as prod
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()

_QTY_ALL = {"всё", "все", "all", "max", "максимум"}


class BInput(StatesGroup):
    """Свободный ввод числа на бирже (кол-во/цена). op в data задаёт шаг."""
    wait = State()


# Анти-залипание: «висящий» ввод биржи протухает, чтобы случайно набранное позже
# число не было проглочено как сделка (юзер давно ушёл с экрана биржи).
_BINPUT_TTL_SECONDS = 600


async def _arm_input(state: FSMContext, **data) -> None:
    """Взвести ожидание ввода биржи со штампом времени (для TTL-протухания)."""
    await state.set_state(BInput.wait)
    await state.update_data(ts=datetime.now(timezone.utc).isoformat(), **data)


def _input_stale(data: dict) -> bool:
    ts = data.get("ts")
    if not ts:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
    except (ValueError, TypeError):
        return False
    return age > _BINPUT_TTL_SECONDS


def _parse_qty(text: str, cap: int) -> int | None:
    t = (text or "").strip().lower()
    if t in _QTY_ALL:
        return cap if cap > 0 else None
    if t.isdigit():
        v = min(int(t), cap)
        return v if v > 0 else None
    return None


def _parse_price(text: str) -> int | None:
    t = (text or "").strip()
    return int(t) if t.isdigit() and int(t) > 0 else None


async def _player(callback: CallbackQuery, session: AsyncSession, *, lock: bool = False):
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


@router.callback_query(F.data == "auction")
async def cb_auction(callback: CallbackQuery, session: AsyncSession,
                     state: FSMContext) -> None:
    await state.clear()  # сбросить незавершённый ввод кол-ва/цены
    player = await _player(callback, session)
    if player is None:
        return
    await common.show_image_panel(
        callback.message, images.named_image("auction"),
        texts.auction_screen(player.tavern),
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
    world = await repo.get_or_create_world(session)
    await common.caption_edit(
        callback.message, texts.auction_pick_qty(good, stock, world),
        kb.auction_qty_kb(good, stock))
    await callback.answer()


@router.callback_query(F.data.startswith("aucq:"))
async def cb_auc_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    _, good, qty_s = callback.data.split(":")
    qty = int(qty_s)
    world = await repo.get_or_create_world(session)
    fv = auction.fair_value(world, good)
    prices = [max(1, round(fv * t)) for t in balance.AUCTION_PRICE_TIERS]
    await common.caption_edit(
        callback.message, texts.auction_pick_price(good, qty, world),
        kb.auction_price_kb(good, qty, prices))
    await callback.answer()


@router.callback_query(F.data.startswith("aucp:"))
async def cb_auc_price(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, good, qty_s, idx_s = callback.data.split(":")
    qty, idx = int(qty_s), int(idx_s)
    world = await repo.get_or_create_world(session)
    fv = auction.fair_value(world, good)
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
        callback.message, texts.auction_screen(player.tavern),
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
    await common.caption_edit(
        callback.message, texts.auction_screen(player.tavern),
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
    goods = bourse.category_goods(cat)
    total = await repo.count_open_orders(session, player.id, side, goods=goods)
    orders = await repo.open_orders(
        session, player.id, side, goods=goods,
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
async def cb_sell_list(callback: CallbackQuery, session: AsyncSession,
                       state: FSMContext) -> None:
    await state.clear()
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
async def cb_buy_list(callback: CallbackQuery, session: AsyncSession,
                      state: FSMContext) -> None:
    await state.clear()
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
async def cb_sell_order(callback: CallbackQuery, session: AsyncSession,
                        state: FSMContext) -> None:
    await state.clear()
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0 or order.side != "sell":
        await callback.answer("Лот уже разобрали.", show_alert=True)
        return
    owner = await repo.get_player(session, order.seller_id)
    best_bid = await repo.best_price(session, order.good, "buy")
    await common.caption_edit(
        callback.message,
        texts.bourse_order(order, owner.first_name if owner else "кто-то",
                           player, best_bid),
        kb.bourse_order_kb(order, player))
    await callback.answer()


@router.callback_query(F.data.startswith("bbid:"))
async def cb_buy_order(callback: CallbackQuery, session: AsyncSession,
                       state: FSMContext) -> None:
    await state.clear()
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0 or order.side != "buy":
        await callback.answer("Заявку уже закрыли.", show_alert=True)
        return
    owner = await repo.get_player(session, order.seller_id)
    best_ask = await repo.best_price(session, order.good, "sell")
    await common.caption_edit(
        callback.message,
        texts.bourse_bid(order, owner.first_name if owner else "кто-то",
                         player.tavern, best_ask),
        kb.bourse_bid_kb(order, player.tavern))
    await callback.answer()


@router.callback_query(F.data.startswith("bbuyq:"))
async def cb_buy_prompt(callback: CallbackQuery, session: AsyncSession,
                        state: FSMContext) -> None:
    """Покупка из лота: спросить КОЛИЧЕСТВО (свободный ввод)."""
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0 or order.side != "sell":
        await callback.answer("Лот уже разобрали.", show_alert=True)
        return
    if order.seller_id == player.id:
        await callback.answer("Это твой лот.", show_alert=True)
        return
    if bourse.buy_room(player, order.good) <= 0:
        await callback.answer(
            f"Лимит скупки {_gname(order.good)} исчерпан "
            f"({balance.BOURSE_BUY_LIMIT} шт/{balance.BOURSE_BUY_WINDOW_H}ч). "
            "Скоро обновится.", show_alert=True)
        return
    cap = min(order.qty, player.gold // order.unit_price if order.unit_price else 0,
              bourse.buy_room(player, order.good))
    if cap <= 0:
        await callback.answer("Не хватает золота даже на одну штуку.", show_alert=True)
        return
    await _arm_input(state, op="buy_qty", order_id=order.id)
    await callback.message.answer(
        f"🛒 Сколько купить {_gname(order.good)}? До {cap} шт "
        f"(по {order.unit_price}🪙). Введи число или «всё».",
        reply_markup=kb.bourse_cancel_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("bfillq:"))
async def cb_fill_prompt(callback: CallbackQuery, session: AsyncSession,
                         state: FSMContext) -> None:
    """Продажа в заявку: спросить КОЛИЧЕСТВО."""
    player = await _player(callback, session)
    if player is None:
        return
    order = await repo.get_order(session, int(callback.data.split(":", 1)[1]))
    if order is None or order.qty <= 0 or order.side != "buy":
        await callback.answer("Заявку уже закрыли.", show_alert=True)
        return
    if order.seller_id == player.id:
        await callback.answer("Это твоя заявка.", show_alert=True)
        return
    stock = int((player.tavern.products or {}).get(order.good, 0))
    cap = min(order.qty, stock)
    if cap <= 0:
        await callback.answer("Нет такого товара в погребе.", show_alert=True)
        return
    await _arm_input(state, op="fill_qty", order_id=order.id)
    await callback.message.answer(
        f"📤 Сколько продать {_gname(order.good)} в заявку? До {cap} шт "
        f"(по {order.unit_price}🪙). Введи число или «всё».",
        reply_markup=kb.bourse_cancel_kb())
    await callback.answer()


# ── Создание лота продажи ───────────────────────────────────────────────────
@router.callback_query(F.data == "bsell")
async def cb_sell_new(callback: CallbackQuery, session: AsyncSession,
                      state: FSMContext) -> None:
    await state.clear()
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
async def cb_sell_good(callback: CallbackQuery, session: AsyncSession,
                       state: FSMContext) -> None:
    """Выбран товар — спросить КОЛИЧЕСТВО (свободный ввод)."""
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    stock = min(int((player.tavern.products or {}).get(good, 0)), balance.BOURSE_QTY_MAX)
    if stock <= 0:
        await callback.answer("Этого товара уже нет.", show_alert=True)
        return
    await _arm_input(state, op="sell_qty", good=good)
    await callback.message.answer(
        f"📤 Сколько продать {_gname(good)}? До {stock} шт. Введи число или «всё».",
        reply_markup=kb.bourse_cancel_kb())
    await callback.answer()


# ── Создание заявки «куплю» ─────────────────────────────────────────────────
@router.callback_query(F.data == "bbidnew")
async def cb_bid_new(callback: CallbackQuery, session: AsyncSession,
                     state: FSMContext) -> None:
    await state.clear()
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
async def cb_bid_good(callback: CallbackQuery, session: AsyncSession,
                      state: FSMContext) -> None:
    """Выбран товар для заявки — спросить КОЛИЧЕСТВО."""
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    if bourse.buy_room(player, good) <= 0:
        await callback.answer(
            f"Лимит скупки {_gname(good)} исчерпан "
            f"({balance.BOURSE_BUY_LIMIT} шт/{balance.BOURSE_BUY_WINDOW_H}ч). "
            "Скоро обновится.", show_alert=True)
        return
    cap = min(balance.BOURSE_QTY_MAX, player.gold // bourse.price_floor(good),
              bourse.buy_room(player, good))
    if cap <= 0:
        await callback.answer("Маловато золота даже на одну штуку.", show_alert=True)
        return
    await _arm_input(state, op="bid_qty", good=good)
    await callback.message.answer(
        f"📣 Сколько {_gname(good)} хочешь купить? До {cap} шт. Введи число или «всё».",
        reply_markup=kb.bourse_cancel_kb())
    await callback.answer()


# ── Мои лоты / отмена ───────────────────────────────────────────────────────
@router.callback_query(F.data == "bprices")
async def cb_prices(callback: CallbackQuery, session: AsyncSession,
                    state: FSMContext) -> None:
    await state.clear()
    player = await _player(callback, session)
    if player is None:
        return
    if _chat_id(callback, player) is None:
        await callback.answer("Биржа — в общем чате. Заходи через «гг».", show_alert=True)
        return
    board = await repo.market_summary(session)
    await common.caption_edit(callback.message, texts.bourse_prices(board),
                              kb.bourse_prices_kb())
    await callback.answer()


@router.callback_query(F.data == "sellers")
async def cb_sellers(callback: CallbackQuery, session: AsyncSession,
                     state: FSMContext) -> None:
    await state.clear()
    player = await _player(callback, session)
    if player is None:
        return
    rows = await repo.top_sellers(session)
    await common.caption_edit(callback.message, texts.sellers_screen(rows, player.id),
                              kb.sellers_kb())
    await callback.answer()


@router.callback_query(F.data == "bmine")
async def cb_mine(callback: CallbackQuery, session: AsyncSession,
                  state: FSMContext) -> None:
    await state.clear()
    player = await _player(callback, session)
    if player is None:
        return
    orders = await repo.seller_orders(session, player.id)
    await common.caption_edit(callback.message, texts.bourse_mine(orders),
                              kb.bourse_mine_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("bcancel:"))
async def cb_cancel(callback: CallbackQuery, session: AsyncSession,
                    state: FSMContext) -> None:
    await state.clear()
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


def _seller_fame(seller: Player | None, qty: int) -> None:
    """Продавцу за проданное на бирже — немного репутации (молва) и +счётчик
    проданного (для рейтинга продавцов). Тихо пропускаем, если таверны нет."""
    if seller is None or seller.tavern is None or qty <= 0:
        return
    logic.add_goods_rep_progress(seller, seller.tavern, qty * balance.REP_POINTS_AUCTION)
    seller.tavern.auction_sold = int(seller.tavern.auction_sold or 0) + qty


async def _match_sell(session: AsyncSession, player: Player,
                      good: str, qty: int, ask: int) -> int:
    """Свести новую ПРОДАЖУ со встречными заявками «куплю» со всего мира (цена >=
    ask, дороже первыми). Сделка по цене заявки (maker). Возвращает сведённое кол-во."""
    nm = _gname(good)
    remaining = qty
    bids = await repo.best_buy_orders(session, good, ask, player.id,
                                      limit=balance.BOURSE_MATCH_MAX)
    await repo.lock_players(session, [bo.seller_id for bo in bids])  # анти-дедлок
    for bo in bids:
        if remaining <= 0:
            break
        if bo.qty <= 0:
            continue
        buyer = await repo.get_player(session, bo.seller_id, for_update=True)
        if buyer is None and bo.seller_id >= 0:   # сиротская заявка удалённого ИГРОКА — снести
            await repo.delete_order(session, bo.id)
            continue
        if buyer is not None and buyer.tavern is None:
            await repo.delete_order(session, bo.id)
            continue
        # buyer=None при seller_id<0 — заявка ГОРОЖАНИНА (NPC): сделка идёт, товар молча
        k = min(remaining, bo.qty)
        gross = k * bo.unit_price            # по цене заявки
        net = bourse.net_to_seller(gross)
        bourse.freeze(player.tavern, good, k)  # списать у продавца
        player.gold += net
        _seller_fame(player, k)                # молва + рейтинг продавцу
        if buyer is not None:
            _give(buyer.tavern, good, k)           # игроку-покупателю (оплачено из залога)
            repo.queue_notify(session, buyer.id,
                              f"📥 По твоей заявке свели {k}×{nm} (из залога {gross} 🪙)", kind="auction")
            repo.add_log(session, "player", buyer.id, f"📥 заявка свелась: {k}×{nm}")
        bo.qty -= k
        if bo.qty <= 0:
            await repo.delete_order(session, bo.id)
        remaining -= k
    return qty - remaining


async def _match_buy(session: AsyncSession, player: Player,
                     good: str, qty: int, bid: int) -> tuple[int, int]:
    """Свести новую ЗАЯВКУ «куплю» со встречными лотами продажи со всего мира
    (цена <= bid, дешевле первыми). Сделка по цене лота. (сведено, остаток)."""
    nm = _gname(good)
    remaining = qty
    asks = await repo.best_sell_orders(session, good, bid, player.id,
                                       limit=balance.BOURSE_MATCH_MAX)
    await repo.lock_players(session, [so.seller_id for so in asks])  # анти-дедлок
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
            _seller_fame(seller, k)            # молва + рейтинг продавцу
            repo.queue_notify(session, seller.id,
                              f"🛒 Твой лот свели на бирже: {k}×{nm} → +{net} 🪙", kind="auction")
            repo.add_log(session, "player", seller.id, f"🛒 лот свёлся: {k}×{nm}")
        so.qty -= k
        if so.qty <= 0:
            await repo.delete_order(session, so.id)
        remaining -= k
    return qty - remaining, remaining


async def _market_nudge(session: AsyncSession, good: str, delta: int) -> None:
    """P2P-сделка двигает оптовую цену ЕДИНОГО рынка по потоку ордеров (order-flow):
    агрессор-ПРОДАВЕЦ давит цену вниз (delta>0 — завал), агрессор-ПОКУПАТЕЛЬ тянет
    вверх (delta<0 — скупка/дефицит). Мягко, через вес MARKET_P2P_WEIGHT."""
    if delta == 0:
        return
    world = await repo.get_or_create_world(session)
    market.nudge(world, good, delta * balance.MARKET_P2P_WEIGHT)


async def _back_auction(callback: CallbackQuery, session: AsyncSession,
                        player: Player) -> None:
    await common.show_image_panel(
        callback.message, images.named_image("auction"),
        texts.auction_screen(player.tavern),
        kb.auction_kb(player.tavern), callback.from_user.id)


# ── Исполнители сделок (вызываются из обработчика ввода) ─────────────────────
async def _do_buy(session: AsyncSession, player: Player, chat_id: int | None,
                  order, qty: int) -> str:
    good, nm = order.good, _gname(order.good)
    qty = min(qty, bourse.buy_room(player, good))  # анти-абуз: лимит покупки 4ч
    if qty <= 0:
        return (f"Лимит покупки {nm} исчерпан (до {balance.BOURSE_BUY_LIMIT} шт "
                f"за {balance.BOURSE_BUY_WINDOW_H}ч). Подожди — обновится.")
    cost = qty * order.unit_price
    player.gold -= cost
    _give(player.tavern, good, qty)
    bourse.record_buy(player, good, qty)
    net = bourse.net_to_seller(cost)
    seller = await repo.get_player(session, order.seller_id, for_update=True)
    if seller is not None:
        seller.gold += net
        _seller_fame(seller, qty)             # молва + рейтинг продавцу
        from bot.game import fgoal, rumors
        fgoal.note("gold_trade", net)         # продажа игрока двигает цель недели
        rumors.note("trade", seller, net)     # крупная продажа — пища для сплетен
        repo.add_log(session, "player", seller.id, f"🏪 продал на бирже {qty}×{nm}")
        repo.queue_notify(session, seller.id,
                          f"🛒 На бирже купили твой товар: {qty}×{nm} → +{net} 🪙", kind="auction")
    order.qty -= qty
    if order.qty <= 0:
        await repo.delete_order(session, order.id)
    repo.add_log(session, "player", player.id, f"🏪 купил на бирже {qty}×{nm} за {cost}🪙")
    await _market_nudge(session, good, -qty)  # скупка тянет цену вверх
    return f"Куплено {qty}×{nm} за {cost} 🪙."


async def _do_fill(session: AsyncSession, player: Player, chat_id: int | None,
                   order, qty: int, buyer: Player | None) -> str:
    # buyer=None → заявка ГОРОЖАНИНА (NPC-трейдер, seller_id<0): сделка идёт, но
    # доставка/уведомление только реальному игроку — NPC потребляет товар молча.
    good, nm = order.good, _gname(order.good)
    gross = qty * order.unit_price
    net = bourse.net_to_seller(gross)
    bourse.freeze(player.tavern, good, qty)
    player.gold += net
    _seller_fame(player, qty)                 # молва + рейтинг продавцу
    from bot.game import fgoal, rumors
    fgoal.note("gold_trade", net)             # продажа игрока двигает цель недели
    rumors.note("trade", player, net)         # крупная продажа — пища для сплетен
    if buyer is not None:
        _give(buyer.tavern, good, qty)
        repo.queue_notify(session, buyer.id,
                          f"📥 По твоей заявке доставили {qty}×{nm} (из залога {gross} 🪙)", kind="auction")
        repo.add_log(session, "player", buyer.id, f"📥 заявка: получил {qty}×{nm}")
    order.qty -= qty
    if order.qty <= 0:
        await repo.delete_order(session, order.id)
    repo.add_log(session, "player", player.id, f"🏪 продал по заявке {qty}×{nm} за {net}🪙")
    await _market_nudge(session, good, qty)
    return f"Продано {qty}×{nm} → +{net} 🪙."


async def _do_create_sell(session: AsyncSession, player: Player, chat_id: int,
                          good: str, qty: int, price: int) -> str:
    nm = _gname(good)
    matched = await _match_sell(session, player, good, qty, price)
    remaining = qty - matched
    listed = 0
    if remaining > 0 and await repo.count_seller_orders(
            session, player.id, "sell") < balance.BOURSE_MAX_ORDERS:
        bourse.freeze(player.tavern, good, remaining)
        repo.create_order(session, chat_id, player.id, good, remaining, price, side="sell")
        listed = remaining
    if matched:
        await _market_nudge(session, good, matched)
    repo.add_log(session, "player", player.id,
                 f"📤 продажа {qty}×{nm} по {price}🪙 (свёл {matched}, выставил {listed})")
    parts = []
    if matched:
        parts.append(f"свёл сразу {matched}")
    if listed:
        parts.append(f"выставил {listed} по {price}🪙")
    if remaining and not listed:
        parts.append(f"{remaining} в погребе (лимит лотов)")
    return f"📤 {nm}: " + (", ".join(parts) if parts else "ничего")


async def _do_create_buy(session: AsyncSession, player: Player, chat_id: int,
                         good: str, qty: int, price: int) -> str:
    nm = _gname(good)
    qty = min(qty, bourse.buy_room(player, good))  # анти-абуз: лимит покупки 4ч
    if qty <= 0:
        return (f"📣 {nm}: лимит покупки исчерпан (до {balance.BOURSE_BUY_LIMIT} шт "
                f"за {balance.BOURSE_BUY_WINDOW_H}ч). Подожди — обновится.")
    matched, remaining = await _match_buy(session, player, good, qty, price)
    listed = 0
    if remaining > 0:
        affordable = player.gold // price if price > 0 else 0
        listed = min(remaining, affordable)
        if listed > 0 and await repo.count_seller_orders(
                session, player.id, "buy") < balance.BOURSE_MAX_ORDERS:
            player.gold -= listed * price
            repo.create_order(session, chat_id, player.id, good, listed, price, side="buy")
        else:
            listed = 0
    # Лимит расходуем на ВСё законтрактованное (купленное + заявка): чтобы пассивный
    # долив заявки позже не обошёл потолок. Отмена заявки лимит не возвращает.
    bourse.record_buy(player, good, matched + listed)
    if matched:
        await _market_nudge(session, good, -matched)  # скупка тянет цену вверх
    repo.add_log(session, "player", player.id,
                 f"📣 куплю {qty}×{nm} по {price}🪙 (свёл {matched}, заявка {listed})")
    parts = []
    if matched:
        parts.append(f"купил сразу {matched}")
    if listed:
        parts.append(f"заявка на {listed} (залог {listed * price}🪙)")
    return f"📣 {nm}: " + (", ".join(parts) if parts else "ничего не вышло")


# ── Свободный ввод количества/цены ──────────────────────────────────────────
@router.callback_query(F.data == "binputcancel")
async def cb_input_cancel(callback: CallbackQuery, session: AsyncSession,
                          state: FSMContext) -> None:
    await state.clear()
    player = await _player(callback, session)
    if player is not None:
        await _back_auction(callback, session, player)
    await callback.answer("Отменено")


@router.message(BInput.wait)
async def on_bourse_input(message: Message, session: AsyncSession,
                          state: FSMContext) -> None:
    data = await state.get_data()
    if _input_stale(data):  # давно висящий ввод — игрок ушёл; не глотаем сообщение
        await state.clear()
        return
    op = data.get("op")
    player = await repo.get_player(session, message.from_user.id, for_update=True)
    if player is None or player.tavern is None:
        await state.clear()
        return
    is_group = message.chat.type in ("group", "supergroup")
    chat_id = message.chat.id if is_group else player.chat_id
    if chat_id is None:
        await state.clear()
        await message.answer("Биржа — в общем чате. Заходи через «гг».")
        return
    raw = message.text or ""
    cancel = kb.bourse_cancel_kb()

    if op == "sell_qty":
        good = data["good"]
        cap = min(int((player.tavern.products or {}).get(good, 0)), balance.BOURSE_QTY_MAX)
        qty = _parse_qty(raw, cap)
        if not qty:
            await message.answer(f"Не понял. Число до {cap} или «всё».", reply_markup=cancel)
            return
        lo, hi = bourse.price_floor(good), bourse.price_ceil(good)
        await _arm_input(state, op="sell_price", qty=qty)  # обновляем штамп времени
        await message.answer(
            f"💰 Цена за штуку {_gname(good)} (коридор {lo}–{hi} 🪙)? Введи число.",
            reply_markup=cancel)
        return

    if op == "sell_price":
        good, qty = data["good"], data["qty"]
        price = _parse_price(raw)
        if price is None or not bourse.valid_price(good, price):
            lo, hi = bourse.price_floor(good), bourse.price_ceil(good)
            await message.answer(f"Цена вне коридора {lo}–{hi}. Введи число.",
                                 reply_markup=cancel)
            return
        qty = min(qty, int((player.tavern.products or {}).get(good, 0)))
        await state.clear()
        if qty <= 0:
            await message.answer("Товара уже нет.", reply_markup=kb.auction_kb(player.tavern))
            return
        summary = await _do_create_sell(session, player, chat_id, good, qty, price)
        await message.answer(summary, reply_markup=kb.auction_kb(player.tavern))
        return

    if op == "bid_qty":
        good = data["good"]
        cap = min(balance.BOURSE_QTY_MAX, player.gold // bourse.price_floor(good),
              bourse.buy_room(player, good))
        qty = _parse_qty(raw, cap)
        if not qty:
            await message.answer(f"Не понял. Число до {cap} или «всё».", reply_markup=cancel)
            return
        lo, hi = bourse.price_floor(good), bourse.price_ceil(good)
        await _arm_input(state, op="bid_price", qty=qty)  # обновляем штамп времени
        await message.answer(
            f"💰 Цена за штуку (коридор {lo}–{hi} 🪙)? Залог = кол-во × цена.",
            reply_markup=cancel)
        return

    if op == "bid_price":
        good, qty = data["good"], data["qty"]
        price = _parse_price(raw)
        if price is None or not bourse.valid_price(good, price):
            lo, hi = bourse.price_floor(good), bourse.price_ceil(good)
            await message.answer(f"Цена вне коридора {lo}–{hi}. Введи число.",
                                 reply_markup=cancel)
            return
        await state.clear()
        summary = await _do_create_buy(session, player, chat_id, good, qty, price)
        await message.answer(summary, reply_markup=kb.auction_kb(player.tavern))
        return

    if op == "buy_qty":
        order = await repo.get_order(session, data["order_id"], lock=True)
        if order is None or order.qty <= 0 or order.side != "sell" \
                or order.seller_id == player.id:
            await state.clear()
            await message.answer("Лот недоступен.", reply_markup=kb.auction_kb(player.tavern))
            return
        cap = min(order.qty, player.gold // order.unit_price if order.unit_price else 0,
              bourse.buy_room(player, order.good))
        qty = _parse_qty(raw, cap)
        if not qty:
            await message.answer(f"Не понял. Число до {cap} или «всё».", reply_markup=cancel)
            return
        await state.clear()
        summary = await _do_buy(session, player, chat_id, order, qty)
        await message.answer(summary, reply_markup=kb.auction_kb(player.tavern))
        return

    if op == "fill_qty":
        order = await repo.get_order(session, data["order_id"], lock=True)
        if order is None or order.qty <= 0 or order.side != "buy" \
                or order.seller_id == player.id:
            await state.clear()
            await message.answer("Заявка недоступна.", reply_markup=kb.auction_kb(player.tavern))
            return
        buyer = await repo.get_player(session, order.seller_id, for_update=True)
        # buyer=None при seller_id<0 — заявка ГОРОЖАНИНА (NPC), это норм. Сносим только
        # осиротевшую заявку удалённого ИГРОКА (id>=0) или игрока без таверны.
        if (buyer is None and order.seller_id >= 0) or (buyer is not None and buyer.tavern is None):
            await repo.delete_order(session, order.id)
            await state.clear()
            await message.answer("Заявка протухла — хозяин сгинул.",
                                 reply_markup=kb.auction_kb(player.tavern))
            return
        cap = min(order.qty, int((player.tavern.products or {}).get(order.good, 0)))
        qty = _parse_qty(raw, cap)
        if not qty:
            await message.answer(f"Не понял. Число до {cap} или «всё».", reply_markup=cancel)
            return
        await state.clear()
        summary = await _do_fill(session, player, chat_id, order, qty, buyer)
        await message.answer(summary, reply_markup=kb.auction_kb(player.tavern))
        return

    await state.clear()
