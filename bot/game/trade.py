"""Торг с заезжими купцами (гибрид A+D).

Купец приходит при сборе дохода (чаще и богаче на ярмарке), хочет купить
партию товара из погреба. Игрок ставит цену; купец принимает / контрит /
уходит — по своим чертам (жадность, нужда, достаток, дружба с купцами).

Сдерживание цен — по-рыночному: справедливая цена-якорь (fv), потолок
наценки, бюджет покупателя, ограниченная партия, случайный приход.
"""

import random

from bot.game import balance, production as prod, story_state

# Пул заезжих покупателей: (имя, эмодзи).
_BUYERS = [
    ("Заезжий купец", "🧔"),
    ("Обозный торговец", "🐎"),
    ("Скупщик с большой дороги", "🎒"),
    ("Корчмарь-перекупщик", "🍻"),
    ("Купчиха Толстогузка", "👩"),
    ("Барыга Кривой Грош", "🤲"),
    ("Заморский гость", "🧳"),
]


def _buyer_desc(greed: float, need: float, rich: bool) -> str:
    bits = []
    if rich:
        bits.append("при деньгах")
    else:
        bits.append("небогат")
    if greed >= 0.66:
        bits.append("прижимист, торгуется за грош")
    elif greed <= 0.33:
        bits.append("не скупится")
    if need >= 0.3:
        bits.append("товар нужен позарез")
    return ", ".join(bits)


def has_sellable(tavern) -> bool:
    prods = tavern.products or {}
    return any(v > 0 and k in prod.GOODS for k, v in prods.items())


def make_offer(tavern, player, fair: bool, rng: random.Random | None = None) -> dict | None:
    """Сгенерировать предложение купца или None."""
    rng = rng or random
    prods = {k: v for k, v in (tavern.products or {}).items()
             if v > 0 and k in prod.GOODS}
    if not prods:
        return None
    # На ярмарке купец метит на дорогое (премиум), иначе берёт, чего больше.
    if fair:
        good = max(prods, key=lambda k: prod.GOODS[k].price)
    else:
        good = max(prods, key=lambda k: prods[k])

    fv = prod.GOODS[good].price * (balance.TRADE_FAIR_FV_MULT if fair else 1.0)
    greed = rng.uniform(0.0, 1.0)
    need = rng.uniform(0.1, 0.4)
    rel = min(0.3, max(0, story_state.faction(player, "merchants")) / 300)

    max_unit = fv * (1 + need + rel) * (1 - greed * 0.3)
    max_unit = max(fv * balance.TRADE_MIN_UNDER,
                   min(fv * balance.TRADE_MAX_OVER, max_unit))

    qty = min(prods[good], rng.randint(balance.TRADE_QTY_MIN, balance.TRADE_QTY_MAX))
    wealth = int(fv * qty * rng.uniform(1.0, 1.6))
    rich = wealth >= fv * qty * 1.3

    name, emoji = rng.choice(_BUYERS)
    prices = [max(1, int(round(fv * t))) for t in balance.TRADE_PRICE_TIERS]
    return {
        "good": good,
        "qty": qty,
        "name": name,
        "emoji": emoji,
        "desc": _buyer_desc(greed, need, rich),
        "fv": round(fv, 2),
        "max_unit": round(max_unit, 2),
        "wealth": wealth,
        "prices": prices,
    }


def _qty_affordable(offer: dict, unit: int) -> int:
    """Сколько купец реально возьмёт по цене unit (бюджет ограничивает)."""
    by_budget = offer["wealth"] // unit if unit > 0 else 0
    return max(0, min(offer["qty"], by_budget))


def evaluate(offer: dict, unit: int) -> tuple[str, int]:
    """Реакция купца на цену unit: ('accept'|'counter'|'walk', цена)."""
    mx = offer["max_unit"]
    if unit <= mx:
        return "accept", unit
    if unit <= mx * balance.TRADE_COUNTER_MARGIN:
        return "counter", max(1, int(round(mx)))
    return "walk", 0
