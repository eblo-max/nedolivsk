"""Аукцион Недоливска: игрок выставляет лот — горожане перебивают ставки.

Асинхронный сбыт в пару к реактивному торгу (trade.py). Лот живёт сам: нотифаер
раз в тик катит, не зайдёт ли покупатель и не поднимет ли цену. Кто и насколько
щедро ставит — те же 58 горожан и их архетипы, плюс настроение города (в духе —
ставят задорого), дефицит рынка и ярмарка. Товар заморожен в лоте (нельзя продать
дважды), потолок ставки тот же, что у заезжего купца (fv×TRADE_MAX_OVER).
"""

import random
from datetime import datetime, timedelta, timezone

from bot.game import balance, market, npc, production as prod, story_state, trade
from bot.game import city as citymod
from bot.game import world as wld


def _now() -> datetime:
    return datetime.now(timezone.utc)


def active(tavern) -> dict | None:
    return tavern.auction or None


def time_left_minutes(lot: dict, now: datetime | None = None) -> int:
    left = (datetime.fromisoformat(lot["ends_at"]) - (now or _now())).total_seconds()
    return max(0, int(left // 60) + 1) if left > 0 else 0


def is_due(tavern, now: datetime | None = None) -> bool:
    lot = tavern.auction
    return bool(lot) and datetime.fromisoformat(lot["ends_at"]) <= (now or _now())


def sellable_goods(tavern) -> list[str]:
    prods = tavern.products or {}
    return [k for k in prod.GOODS if prods.get(k, 0) > 0]


def fair_value(city, good: str) -> float:
    """Текущая справедливая цена товара (ярмарка × перекос рынка)."""
    fairmult = balance.TRADE_FAIR_FV_MULT if wld.is_fair() else 1.0
    return prod.GOODS[good].price * fairmult * market.factor(city, good)


def _mood_factor(city) -> float:
    return 1.0 + citymod.mood_value(city) / balance.AUCTION_MOOD_DIV


def _interested(arch, good: str) -> bool:
    pr = prod.GOODS[good].price
    if arch.pref == "premium":
        return pr >= 10
    if arch.pref == "cheap":
        return pr <= balance.COMMONER_MAX_PRICE
    return True


def _ceiling(arch, fv: float, mood_f: float, rng: random.Random) -> float:
    """Личный потолок цены покупателя за штуку (та же логика, что у купца)."""
    greed = rng.uniform(*arch.greed)
    need = rng.uniform(*arch.need)
    c = fv * (1 + need) * (1 - greed * 0.3) * mood_f
    return max(fv * balance.TRADE_MIN_UNDER, min(fv * balance.TRADE_MAX_OVER, c))


def create(player, tavern, good: str, qty: int, unit_min: int) -> tuple[bool, str]:
    """Выставить лот: товар замораживается. reason: busy|empty|price."""
    if active(tavern):
        return False, "busy"
    stock = int((tavern.products or {}).get(good, 0))
    if good not in prod.GOODS or stock <= 0:
        return False, "empty"
    if unit_min < 1:
        return False, "price"
    qty = max(1, min(qty, stock, balance.AUCTION_QTY_MAX))
    prods = dict(tavern.products or {})
    prods[good] = stock - qty
    tavern.products = prods
    tavern.auction = {
        "good": good, "qty": qty, "unit_min": int(unit_min),
        "ends_at": (_now() + timedelta(hours=balance.AUCTION_DURATION_HOURS)).isoformat(),
        "top_bid": None, "top_bidder": None, "bids": 0, "history": [],
    }
    return True, ""


def cancel(player, tavern) -> bool:
    """Снять лот: вернуть замороженный товар в погреб."""
    lot = tavern.auction
    if not lot:
        return False
    prods = dict(tavern.products or {})
    prods[lot["good"]] = prods.get(lot["good"], 0) + lot["qty"]
    tavern.products = prods
    tavern.auction = {}
    return True


def try_bid(tavern, city, rng: random.Random | None = None) -> dict | None:
    """Один прогон ставки: заглянул ли горожанин и перебил ли цену.
    Мутирует лот; возвращает {npc, unit} при новой ставке, иначе None."""
    rng = rng or random
    lot = tavern.auction
    if not lot:
        return None
    good = lot["good"]
    fv = fair_value(city, good)
    mood_f = _mood_factor(city)
    cit = npc.random_trader(rng)
    arch = trade.ARCH[cit.arch]
    if not _interested(arch, good):
        return None
    ceil = _ceiling(arch, fv, mood_f, rng)
    cur = lot.get("top_bid") or 0
    floor = lot["unit_min"]
    if ceil < max(floor, cur + 1):       # не дотянет до резерва/перебивки
        return None
    if cur == 0:
        bid = floor                       # открывает торги по резервной цене
    else:
        step = max(1, round(fv * balance.AUCTION_BID_STEP))
        bid = min(int(round(ceil)), cur + step)
        if bid <= cur:
            return None
    # бюджет: крупный лот потянет только состоятельный
    purse = 0.6 + cit.wealth * 0.15
    wealth = fv * lot["qty"] * rng.uniform(*arch.wealth_mult) * purse
    if wealth < bid * lot["qty"]:
        return None
    lot["top_bid"] = bid
    lot["top_bidder"] = cit.id
    lot["bids"] = lot.get("bids", 0) + 1
    hist = list(lot.get("history", []))
    hist.append({"npc": cit.id, "unit": bid})
    lot["history"] = hist[-5:]
    tavern.auction = dict(lot)            # переприсваивание — для JSONB
    return {"npc": cit.id, "unit": bid, "fv": fv}


def settle(player, tavern, city) -> dict | None:
    """Закрыть торги: продать победителю или вернуть товар. Возвращает итог."""
    lot = tavern.auction
    if not lot:
        return None
    good, qty = lot["good"], lot["qty"]
    top, bidder = lot.get("top_bid"), lot.get("top_bidder")
    tavern.auction = {}
    if top and bidder:
        gold = qty * top
        player.gold += gold
        story_state.adjust_faction(player, "merchants", 1)
        market.add_supply(city, good, int(qty * balance.MARKET_WHOLESALE_WEIGHT))
        return {"sold": True, "good": good, "qty": qty,
                "unit": top, "gold": gold, "npc": bidder}
    prods = dict(tavern.products or {})
    prods[good] = prods.get(good, 0) + qty
    tavern.products = prods
    return {"sold": False, "good": good, "qty": qty}
