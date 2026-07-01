"""Торговый контур мини-аппа: лавка скупщика (/api/torg), аукцион (/api/auction/*)
и биржа (/api/bourse/*). Перенесено из bot/webapp.py дословно (move-only)."""

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth, _is_admin, _npc_avatar

def _torg_open(uid: int) -> bool:
    """Открыт ли Торг этому игроку: всем (флаг) либо только админу (закрытый запуск)."""
    from bot.game import balance as bal
    from bot.config import settings
    return bool(bal.TORG_OPEN) or uid == settings.admin_id


def _shop_items(p) -> list:
    """Ассортимент скупщика для игрока: цена, дневной остаток, сколько по карману, запас."""
    from bot.game import balance as bal, shop
    inv = p.inventory or {}
    out = []
    for r in shop.sellable():
        out.append({
            "key": r, "name": bal.RESOURCE_NAMES.get(r, r), "emoji": bal.RESOURCE_EMOJI.get(r, "📦"),
            "price": shop.price(r), "room": shop.buy_room(p, r), "limit": bal.SHOP_DAILY_LIMIT,
            "max": shop.max_affordable(p, r), "have": int(inv.get(r, 0)),
        })
    return out


async def _api_torg(request: web.Request) -> web.Response:
    """Вкладка «Торг». Закрыта для всех (open=false) — кроме админа/флага. Открытому —
    скупщик (цены/лимиты/золото). Аукцион и биржа — пока «скоро»."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _torg_open(uid):
            return web.json_response({"ok": True, "open": False}, headers={"Cache-Control": "no-store"})
        out = {"ok": True, "open": True, "gold": p.gold, "limit": bal.SHOP_DAILY_LIMIT,
               "shop": _shop_items(p)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_torg_buy(request: web.Request) -> web.Response:
    """Купить сырьё у скупщика. Серверный гейт + клампы (золото/дневной лимит)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal, economy, inventory, shop
    res = str(body.get("res") or "")
    try:
        want = int(body.get("qty") or 0)
    except (TypeError, ValueError):
        want = 0
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _torg_open(uid):
            return web.json_response({"ok": False, "error": "closed"})
        if res not in shop.sellable():
            return web.json_response({"ok": False, "error": "bad_res"})
        qty = max(0, min(want, shop.max_affordable(p, res)))
        if qty <= 0:
            return web.json_response({"ok": False, "error": "cant"})
        cost = qty * shop.price(res)
        p.gold -= cost
        economy.record(p, "shop", -cost)
        inventory.add(p, res, qty)
        shop.record_buy(p, res, qty)
        repo.add_log(s, "player", p.id,
                     f"🛒 купил в лавке {qty}×{bal.RESOURCE_NAMES.get(res, res)} (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "limit": bal.SHOP_DAILY_LIMIT,
               "shop": _shop_items(p), "bought": {"res": res, "qty": qty, "cost": cost}}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _auction_open(uid: int) -> bool:
    from bot.game import balance as bal
    from bot.config import settings
    return bool(bal.AUCTION_OPEN) or uid == settings.admin_id


def _auc_npc(nid):
    from bot.game import npc as npcmod
    if not nid:
        return None
    cz = npcmod.CATALOG.get(nid)
    return {"name": cz.name if cz else nid, "emoji": cz.emoji if cz else "🙂",
            "avatar": _npc_avatar(nid, cz.estate if cz else None)}


def _auction_state(p, world) -> dict:
    """Состояние аукциона: живой лот (товар/таймер/ставки/история) либо форма
    выставления (товары погреба со справедливой ценой, объёмы, тиры цены)."""
    from bot.game import auction as auc, balance as bal, production as prod
    t = p.tavern
    lot = auc.active(t)
    if lot:
        g = prod.GOODS.get(lot["good"])
        hist = [{"unit": h["unit"], **(_auc_npc(h["npc"]) or {})} for h in reversed(lot.get("history", []))]
        return {"active": True, "good": lot["good"], "name": g.name if g else lot["good"],
                "emoji": g.emoji if g else "📦", "qty": lot["qty"], "reserve": lot["unit_min"],
                "top_bid": lot.get("top_bid"), "bidder": _auc_npc(lot.get("top_bidder")),
                "bids": lot.get("bids", 0), "ends_at": lot["ends_at"],
                "mins_left": auc.time_left_minutes(lot), "history": hist,
                "duration_h": bal.AUCTION_DURATION_HOURS}
    prods = t.products or {}

    def _good(k):
        fv = auc.fair_value(world, k)
        return {"key": k, "name": (prod.GOODS[k].name if k in prod.GOODS else k),
                "emoji": (prod.GOODS[k].emoji if k in prod.GOODS else "📦"),
                "stock": int(prods.get(k, 0)), "fv": int(round(fv)),
                # точные цены тиров (та же формула, что и при создании) — превью == факт
                "prices": [max(1, round(fv * m)) for m in bal.AUCTION_PRICE_TIERS]}
    goods = [_good(k) for k in auc.sellable_goods(t)]
    tiers = [{"mult": m, "label": lbl}
             for m, lbl in zip(bal.AUCTION_PRICE_TIERS, ("по рынку", "бодро", "дорого"), strict=True)]
    return {"active": False, "goods": goods, "tiers": tiers,
            "presets": list(bal.AUCTION_QTY_PRESETS), "qty_max": bal.AUCTION_QTY_MAX,
            "duration_h": bal.AUCTION_DURATION_HOURS}


def _auc_result(res: dict) -> dict | None:
    """Итог последних торгов для финал-экрана (свежее AUCTION_DURATION ч)."""
    if not res:
        return None
    from datetime import datetime, timezone
    from bot.game import balance as bal, production as prod
    try:
        ts = datetime.fromisoformat(res["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - ts).total_seconds() > bal.AUCTION_DURATION_HOURS * 3600:
            return None
    except (KeyError, ValueError, TypeError):
        return None
    g = prod.GOODS.get(res.get("good"))
    out = {"sold": bool(res.get("sold")), "qty": res.get("qty"), "good": res.get("good"),
           "name": g.name if g else res.get("good"), "emoji": g.emoji if g else "📦"}
    if res.get("sold"):
        out["unit"] = res.get("unit"); out["gold"] = res.get("gold")
        out["winner"] = _auc_npc(res.get("npc"))
    return out


async def _api_auction(request: web.Request) -> web.Response:
    """Аукцион: живой лот или форма выставления. Гейт: admin/AUCTION_OPEN.
    Если лот вышел по таймеру — закрываем прямо тут и отдаём итог (финал-экран)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import auction as auc
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _auction_open(uid):
            return web.json_response({"ok": True, "open": False}, headers={"Cache-Control": "no-store"})
        world = await repo.get_or_create_world(s)
        if auc.is_due(p.tavern):                       # таймер вышел — закрыть немедленно
            res = auc.settle(p, p.tavern, world)
            repo.add_log(s, "player", p.id, "🔨 торги закрыты (мини-апп)")
            if res is not None:                        # DM как у нотифаера — чтобы паритет был полный
                from bot import texts as _t
                repo.queue_notify(s, p.id, _t.auction_settled(res))
            await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": _is_admin(uid), **_auction_state(p, world)}
        res = _auc_result((p.story or {}).get("auc_last"))
        if res and not out.get("active"):
            out["result"] = res
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_seen(request: web.Request) -> web.Response:
    """Игрок увидел финал-экран — гасим запомненный итог."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is not None and (p.story or {}).get("auc_last"):
            st = dict(p.story); st.pop("auc_last", None); p.story = st
            await s.commit()
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


async def _api_auction_create(request: web.Request) -> web.Response:
    """Выставить лот: {good, qty, tier} (индекс тира цены) или {good, qty, price}."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import auction as auc, balance as bal
    good = str(body.get("good") or "")
    try:
        qty = int(body.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _auction_open(uid):
            return web.json_response({"ok": False, "error": "closed"})
        world = await repo.get_or_create_world(s)
        if "tier" in body:
            prices = [max(1, round(auc.fair_value(world, good) * m)) for m in bal.AUCTION_PRICE_TIERS]
            try:
                price = prices[int(body.get("tier"))]
            except (TypeError, ValueError, IndexError):
                return web.json_response({"ok": False, "error": "price"})
        else:
            try:
                price = int(body.get("price") or 0)
            except (TypeError, ValueError):
                price = 0
        ok, reason = auc.create(p, p.tavern, good, qty, price)
        if not ok:
            return web.json_response({"ok": False, "error": reason})
        repo.add_log(s, "player", p.id, f"🔨 выставил лот {qty}×{good} по {price}🪙 (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": _is_admin(uid), **_auction_state(p, world)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_cancel(request: web.Request) -> web.Response:
    """Снять лот: замороженный товар вернётся в погреб."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import auction as auc
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not auc.cancel(p, p.tavern):
            return web.json_response({"ok": False, "error": "none"})
        repo.add_log(s, "player", p.id, "🔨 снял лот с торгов (мини-апп)")
        await s.commit()
        world = await repo.get_or_create_world(s)
        out = {"ok": True, "open": True, "gold": p.gold, "admin": _is_admin(uid), **_auction_state(p, world)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_seed(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): подбросить 2-3 живые ставки горожан на текущий лот —
    чтобы вживую проверить зал торгов/подсветку/финал, не дожидаясь нотифаера."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    import random
    from bot.game import npc as npcmod
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        world = await repo.get_or_create_world(s)
        lot = p.tavern.auction
        if not lot:
            return web.json_response({"ok": False, "error": "none"})
        lot = dict(lot)   # КОПИЯ (см. try_bid): иначе in-place мутация не сохранится (JSONB)
        rng = random.Random()
        added = 0
        for _ in range(rng.randint(2, 3)):                 # цена лезет от резерва вверх
            cit = npcmod.random_trader(rng)
            cur = lot.get("top_bid") or 0
            bid = lot["unit_min"] if cur == 0 else cur + rng.randint(1, 3)
            lot["top_bid"], lot["top_bidder"] = bid, cit.id
            lot["bids"] = lot.get("bids", 0) + 1
            hist = list(lot.get("history", []))
            hist.append({"npc": cit.id, "unit": bid})
            lot["history"] = hist[-5:]
            added += 1
        p.tavern.auction = dict(lot)                        # переприсваивание для JSONB
        repo.add_log(s, "player", p.id, f"🧪 тест: +{added} ставок на лот (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": True, **_auction_state(p, world)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_settle_now(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): закрыть торги немедленно — увидеть финал «Продано/Не взяли»."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from bot.game import auction as auc
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not p.tavern.auction:
            return web.json_response({"ok": False, "error": "none"})
        world = await repo.get_or_create_world(s)
        auc.settle(p, p.tavern, world)
        repo.add_log(s, "player", p.id, "🧪 тест: торги закрыты вручную (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": True, **_auction_state(p, world)}
        res = _auc_result((p.story or {}).get("auc_last"))
        if res and not out.get("active"):
            out["result"] = res
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _bourse_open(uid: int) -> bool:
    from bot.game import balance as bal
    return bool(bal.BOURSE_OPEN) or _is_admin(uid)


def _good_dto(k: str) -> dict:
    from bot.game import production as prod
    g = prod.GOODS.get(k)
    return {"key": k, "name": g.name if g else k, "emoji": g.emoji if g else "📦"}


async def _bourse_state(s, p) -> dict:
    """Снимок биржи для игрока: чужие продажи/заявки, мои ордера, стакан, топ-
    продавцы и товары с коридором цены/пресетами/лимитом скупки (для форм)."""
    from bot.game import bourse, production as prod, balance as bal
    from sqlalchemy import select
    from bot.db.models import Player
    sells = await repo.open_orders(s, p.id, "sell", limit=20)   # чужие продажи → купить
    buys = await repo.open_orders(s, p.id, "buy", limit=20)     # чужие заявки → продать в них
    mine = await repo.seller_orders(s, p.id)
    board = await repo.market_summary(s)
    sellers = await repo.top_sellers(s, 10)
    ids = {o.seller_id for o in (*sells, *buys)}
    names = {}
    if ids:
        rows = (await s.execute(
            select(Player.id, Player.first_name).where(Player.id.in_(ids)))).all()
        names = {i: n for i, n in rows}

    def _ord(o, who: bool):
        d = {"id": o.id, "side": o.side, "qty": o.qty, "unit": o.unit_price, **_good_dto(o.good)}
        if who:
            d["who"] = names.get(o.seller_id) or "горожанин"
        return d

    board_list = [{**_good_dto(k), "ask": b.get("ask"), "ask_qty": b.get("ask_qty"),
                   "bid": b.get("bid"), "bid_qty": b.get("bid_qty"),
                   "floor": bourse.price_floor(k), "ceil": bourse.price_ceil(k)}
                  for k, b in sorted(board.items())]
    prods = p.tavern.products or {}
    goods = [{**_good_dto(k), "stock": int(prods.get(k, 0)),
              "floor": bourse.price_floor(k), "ceil": bourse.price_ceil(k),
              "presets": bourse.price_tiers(k), "room": bourse.buy_room(p, k)}
             for k in prod.GOODS]
    return {
        "gold": p.gold,
        "sells": [_ord(o, True) for o in sells],
        "buys": [_ord(o, True) for o in buys],
        "mine": [_ord(o, False) for o in mine],
        "board": board_list,
        "sellers": [{"name": t.name, "sold": int(t.auction_sold or 0), "me": pl.id == p.id}
                    for t, pl in sellers],
        "goods": goods,
        "qty_max": bal.BOURSE_QTY_MAX, "max_orders": bal.BOURSE_MAX_ORDERS,
    }


async def _api_bourse(request: web.Request) -> web.Response:
    """Биржа (P2P-ордербук): доска + товары. Гейт: admin/BOURSE_OPEN."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _bourse_open(uid):
            return web.json_response({"ok": True, "open": False}, headers={"Cache-Control": "no-store"})
        out = {"ok": True, "open": True, "admin": _is_admin(uid), **(await _bourse_state(s, p))}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _bourse_chat(p) -> int:
    """Источник ордеров мини-аппа: домашний чат игрока, иначе его id (матчинг
    глобальный, chat_id — лишь привязка)."""
    return p.chat_id if p.chat_id is not None else p.id


async def _api_bourse_act(request: web.Request) -> web.Response:
    """Действия Биржи (ФАЗА 2): {op, ...}. Переиспользует боевые исполнители
    текст-бота (_do_buy/_do_fill/_do_create_sell/_do_create_buy) — логика и
    налоги/лимиты/коридор идентичны бирже в чате. Возвращает свежую доску + итог."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import bourse, production as prod
    from bot.handlers.auction import (_do_buy, _do_fill, _do_create_sell, _do_create_buy)
    op = str(body.get("op") or "")

    def _int(key):
        try:
            return int(body.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _bourse_open(uid):
            return web.json_response({"ok": False, "error": "closed"})
        chat = _bourse_chat(p)
        done = None

        if op in ("buy", "fill"):
            order = await repo.get_order(s, _int("order_id"), lock=True)
            if order is None or order.qty <= 0 or order.seller_id == p.id:
                return web.json_response({"ok": False, "error": "gone"})
            qty = _int("qty")
            if op == "buy":
                if order.side != "sell":
                    return web.json_response({"ok": False, "error": "gone"})
                cap = min(order.qty, p.gold // order.unit_price if order.unit_price else 0,
                          bourse.buy_room(p, order.good))
                qty = max(1, min(qty, cap))
                if cap <= 0:
                    return web.json_response({"ok": False, "error": "cant"})
                done = await _do_buy(s, p, chat, order, qty)
            else:
                if order.side != "buy":
                    return web.json_response({"ok": False, "error": "gone"})
                buyer = await repo.get_player(s, order.seller_id, for_update=True)
                if buyer is None or buyer.tavern is None:
                    await repo.delete_order(s, order.id)
                    await s.commit()
                    return web.json_response({"ok": False, "error": "gone"})
                stock = int((p.tavern.products or {}).get(order.good, 0))
                qty = max(1, min(qty, order.qty, stock))
                if stock <= 0:
                    return web.json_response({"ok": False, "error": "cant"})
                done = await _do_fill(s, p, chat, order, qty, buyer)

        elif op in ("sell", "bid"):
            good = str(body.get("good") or "")
            qty, price = _int("qty"), _int("price")
            if good not in prod.GOODS or qty <= 0 or not bourse.valid_price(good, price):
                return web.json_response({"ok": False, "error": "bad"})
            if op == "sell":
                stock = int((p.tavern.products or {}).get(good, 0))
                qty = min(qty, stock, _bal_qty_max())
                if qty <= 0:
                    return web.json_response({"ok": False, "error": "empty"})
                done = await _do_create_sell(s, p, chat, good, qty, price)
            else:
                qty = min(qty, _bal_qty_max())
                done = await _do_create_buy(s, p, chat, good, qty, price)

        elif op == "cancel":
            order = await repo.get_order(s, _int("order_id"), lock=True)
            if order is None or order.seller_id != p.id:
                return web.json_response({"ok": False, "error": "gone"})
            if order.side == "sell":
                bourse.unfreeze(p.tavern, order.good, order.qty)
                done = "Лот снят — товар вернулся в погреб."
            else:
                p.gold += order.qty * order.unit_price
                done = f"Заявка снята — залог {order.qty * order.unit_price} 🪙 вернулся."
            await repo.delete_order(s, order.id)
        else:
            return web.json_response({"ok": False, "error": "bad_op"})

        await s.commit()
        out = {"ok": True, "open": True, "admin": _is_admin(uid), "done": done,
               **(await _bourse_state(s, p))}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _bal_qty_max() -> int:
    from bot.game import balance as bal
    return bal.BOURSE_QTY_MAX

