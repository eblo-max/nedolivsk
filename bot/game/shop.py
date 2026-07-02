"""Лавка скупщика: покупка СЫРЬЯ за золото с наценкой и дневным лимитом.

Зачем: золото льётся из боя, а прогресс (апгрейд/рецепты) заперт за сырьём из
вылазок — золото копится впустую. Лавка даёт золоту сток и осознанный размен
«время ↔ деньги»: терпеливый копит вылазками (дёшево, долго), богатый платит
премию (быстро, дорого). Продаём ТОЛЬКО сырьё вылазок — не полуфабрикаты
(солод/мука/слиток): их делают пристройки, прогрессию зданий не ломаем.

Чистая логика (цены/лимит/окно) — здесь; списание золота и выдача — в хендлере
под локом строки игрока.
"""

import math
from datetime import datetime, timezone

from bot.game import balance

WINDOW_HOURS = 24


def sellable() -> list[str]:
    """Что продаёт лавка — только добываемое вылазками сырьё."""
    return list(balance.EXPEDITION_YIELD)


def price(resource: str) -> int:
    """Цена за единицу: базовая стоимость × наценка (вверх, ≥1)."""
    base = balance.RESOURCE_PRICE.get(resource, 0)
    return max(1, math.ceil(base * balance.SHOP_PRICE_MARKUP))


def price_for(player, resource: str) -> int:
    """ПЕРСОНАЛЬНАЯ цена лавки: друзьям Купеческой лиги дешевле, врагам дороже.
    Единый источник для показа, лимита и списания (показ = действие)."""
    from bot.game import factions
    return max(1, round(price(resource) * factions.shop_buy_mult(player)))


def _fresh(rec: dict, now: datetime) -> bool:
    """Запись лимита ещё в текущем 24-часовом окне?"""
    try:
        return (now - datetime.fromisoformat(rec["t"])).total_seconds() < WINDOW_HOURS * 3600
    except (KeyError, ValueError, TypeError):
        return False


def buy_room(player, resource: str, now: datetime | None = None) -> int:
    """Сколько ещё единиц ресурса можно купить в текущем 24ч-окне."""
    now = now or datetime.now(timezone.utc)
    rec = (player.shop_buys or {}).get(resource)
    used = int(rec.get("q", 0)) if rec and _fresh(rec, now) else 0
    return max(0, balance.SHOP_DAILY_LIMIT - used)


def record_buy(player, resource: str, qty: int, now: datetime | None = None) -> None:
    """Зачесть купленные qty в дневное окно лимита (мутирует player.shop_buys)."""
    if qty <= 0:
        return
    now = now or datetime.now(timezone.utc)
    buys = dict(player.shop_buys or {})
    rec = buys.get(resource)
    if rec and _fresh(rec, now):
        buys[resource] = {"t": rec["t"], "q": int(rec.get("q", 0)) + qty}
    else:
        buys[resource] = {"t": now.isoformat(), "q": qty}
    player.shop_buys = buys   # переприсваивание — для JSONB


def max_affordable(player, resource: str, now: datetime | None = None) -> int:
    """Сколько РЕАЛЬНО можно купить сейчас: ограничено и золотом, и дневным лимитом."""
    if resource not in balance.EXPEDITION_YIELD:
        return 0
    p = price_for(player, resource)
    by_gold = player.gold // p if p else 0
    return max(0, min(int(by_gold), buy_room(player, resource, now)))


def shortfall(have: dict, cost: dict) -> dict:
    """Чего и сколько не хватает по сырью из cost (только продаваемое лавкой)."""
    out: dict[str, int] = {}
    for res in sellable():
        need = cost.get(res, 0)
        gap = need - int((have or {}).get(res, 0))
        if gap > 0:
            out[res] = gap
    return out


def bill(items: dict) -> int:
    """Сколько золота стоит набор {ресурс: кол-во} в лавке."""
    return sum(price(r) * int(q) for r, q in items.items())
