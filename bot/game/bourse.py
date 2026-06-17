"""Городская биржа (P2P): игроки продают товар друг другу по фикс-цене.

Чистый player-to-player: лот висит, пока его не купит ДРУГОЙ игрок (NPC тут
не выкупает — для гарантии есть обычный аукцион). Анти-абуз:
  • ценовой коридор [floor..ceil] от базовой цены — нельзя перекачать золото
    альту запредельной ценой;
  • налог продавца (сток золота) — перекачка между альтами убыточна;
  • товар заморожен в лоте (списан из погреба), нельзя продать дважды;
  • покупка — под локом строки заказа (см. handler) — без гонок/дюпа.

Здесь — чистые помощники (цены, коридор, заморозка). DB-операции — в repo,
сведение сделки (золото/товар/налог) — в хендлере (там сессия и локи).
"""

import math
from datetime import datetime, timezone

from bot.game import balance
from bot.game import production as prod


def base_price(good: str) -> int:
    if good not in prod.GOODS:
        return 0
    from bot.game import worldevent  # ленивый импорт — без цикла
    return max(1, round(prod.GOODS[good].price * worldevent.good_price_mult(good)))


def price_floor(good: str) -> int:
    return max(1, math.ceil(base_price(good) * balance.BOURSE_PRICE_FLOOR))


def price_ceil(good: str) -> int:
    return max(price_floor(good), math.floor(base_price(good) * balance.BOURSE_PRICE_CEIL))


def valid_price(good: str, price: int) -> bool:
    return price_floor(good) <= price <= price_ceil(good)


def price_tiers(good: str) -> list[int]:
    """Пресеты цены (× базовой), зажатые в коридор, без дублей."""
    base = base_price(good)
    lo, hi = price_floor(good), price_ceil(good)
    out: list[int] = []
    for t in balance.BOURSE_PRICE_TIERS:
        p = max(lo, min(hi, round(base * t)))
        if p not in out:
            out.append(p)
    return out


def sellable_goods(tavern) -> list[str]:
    prods = tavern.products or {}
    return [g for g in prod.GOODS if prods.get(g, 0) > 0]


def freeze(tavern, good: str, qty: int) -> bool:
    """Списать товар из погреба под лот. False — не хватает/некорректно."""
    prods = dict(tavern.products or {})
    have = int(prods.get(good, 0))
    if qty <= 0 or have < qty:
        return False
    prods[good] = have - qty
    tavern.products = prods
    return True


def unfreeze(tavern, good: str, qty: int) -> None:
    """Вернуть замороженный товар в погреб (отмена лота)."""
    prods = dict(tavern.products or {})
    prods[good] = int(prods.get(good, 0)) + qty
    tavern.products = prods


def net_to_seller(gross: int) -> int:
    """Сколько получит продавец после налога биржи."""
    return int(gross * (1 - balance.BOURSE_SALE_TAX))


def tax_amount(gross: int) -> int:
    return gross - net_to_seller(gross)


def _window_fresh(rec: dict, now: datetime) -> bool:
    """Запись лимита покупки ещё в текущем 4-часовом окне?"""
    try:
        t = datetime.fromisoformat(rec["t"])
    except (KeyError, ValueError):
        return False
    return (now - t).total_seconds() < balance.BOURSE_BUY_WINDOW_H * 3600


def buy_room(player, good: str, now: datetime | None = None) -> int:
    """Сколько ещё единиц good игрок вправе СКУПИТЬ в текущем окне (анти-абуз,
    как buy-limit в RuneScape). Истёкшее окно = полный лимит."""
    now = now or datetime.now(timezone.utc)
    rec = (player.bourse_buys or {}).get(good)
    used = int(rec.get("q", 0)) if rec and _window_fresh(rec, now) else 0
    return max(0, balance.BOURSE_BUY_LIMIT - used)


def record_buy(player, good: str, qty: int, now: datetime | None = None) -> None:
    """Зачесть купленные/законтрактованные qty в окно лимита покупки."""
    if qty <= 0:
        return
    now = now or datetime.now(timezone.utc)
    buys = dict(player.bourse_buys or {})
    rec = buys.get(good)
    if rec and _window_fresh(rec, now):
        buys[good] = {"t": rec["t"], "q": int(rec.get("q", 0)) + qty}
    else:
        buys[good] = {"t": now.isoformat(), "q": qty}
    player.bourse_buys = buys  # переприсваивание — для JSONB


def category_goods(cat: str) -> list[str] | None:
    """Фильтр списка по категории: drink/food → список ключей, all → None."""
    if cat == "drink":
        return list(prod.DRINKS)
    if cat == "food":
        return list(prod.FOODS)
    return None
