"""NPC-трейдеры биржи (живой мир, фаза 4): именные горожане с бюджетами
и повадками ставят НАСТОЯЩИЕ ордера в общий стакан.

Зачем: биржа живёт даже при низком онлайне, цены само-стабилизируются
(перекуп подбирает дешёвку, спекулянт закрывает дефицит), а внимательные
игроки учатся торговать «против» повадок конкретного NPC.

Бюджеты дневные, состояние в world.live['npc'] (JSONB, переживает деплой;
НЕ в world.market — рынок ждёт там только числа, словарь ронял decay 02.07).
seller_id отрицательный — личная лента/уведомления такие id игнорируют."""

import random
from datetime import datetime, timezone

from bot.game import auction as auc
from bot.game import production as prod

# id -> повадка. Отрицательные id не пересекаются с Telegram-игроками.
TRADERS = {
    -9001: {"name": "Перекуп Сизый", "style": "cheap",
            "daily_gold": 400,   # скупает дешёвку ниже 0.8×справедливой (BUY-лоты)
            "goods": ("ale1", "ale2", "bread", "cheese", "kvas", "salat", "patties")},
    -9002: {"name": "Монастырь Святой Бочки", "style": "mead",
            "daily_gold": 300, "friday_gold": 600,   # мёд каждый день, в пятницу — вдвое
            "goods": ("mead",)},
    -9003: {"name": "Спекулянт Крысобой", "style": "supply",
            "daily_qty": 10,     # завозит дефицит по 1.25×цены (SELL-лоты)
            "goods": ("ale1", "bread", "mead", "sausage", "steak", "kebab")},
}
CHEAP_MULT = 0.75        # перекуп: цена скупки
SUPPLY_MULT = 1.25       # спекулянт: цена завоза
NPC_ORDER_QTY_MAX = 8    # не заливать стакан


def _day_key(now: datetime) -> str:
    return now.date().isoformat()


def _state(world, now: datetime) -> dict:
    m = dict(world.live or {})
    st = dict(m.get("npc") or {})
    if st.get("day") != _day_key(now):          # новый день — свежие бюджеты
        st = {"day": _day_key(now), "spent": {}}
    return st


def _save(world, st: dict) -> None:
    m = dict(world.live or {})
    m["npc"] = st
    world.live = m


async def tick(session, repo, world, now: datetime | None = None,
               rng: random.Random | None = None) -> int:
    """Час биржи: каждый NPC без открытого ордера ставит один по повадке.
    Возвращает число выставленных ордеров (для лога)."""
    now = now or datetime.now(timezone.utc)
    rng = rng or random
    st = _state(world, now)
    spent = dict(st.get("spent") or {})
    placed = 0
    for nid, spec in TRADERS.items():
        open_cnt = (await repo.count_seller_orders(session, nid, "buy")
                    + await repo.count_seller_orders(session, nid, "sell"))
        if open_cnt > 0:
            continue                             # его ордер ещё висит
        style = spec["style"]
        used = int(spent.get(str(nid), 0))
        if style == "cheap":
            budget = spec["daily_gold"] - used
            good = rng.choice(spec["goods"])
            unit = max(1, int(auc.fair_value(world, good) * CHEAP_MULT))
            qty = min(NPC_ORDER_QTY_MAX, budget // unit)
            if qty >= 2:
                repo.create_order(session, 0, nid, good, qty, unit, side="buy")
                spent[str(nid)] = used + qty * unit
                placed += 1
        elif style == "mead":
            cap = spec["friday_gold"] if now.weekday() == 4 else spec["daily_gold"]
            budget = cap - used
            good = spec["goods"][0]
            if good not in prod.GOODS:
                continue
            unit = max(1, int(auc.fair_value(world, good)))
            qty = min(NPC_ORDER_QTY_MAX, budget // unit)
            if qty >= 2:
                repo.create_order(session, 0, nid, good, qty, unit, side="buy")
                spent[str(nid)] = used + qty * unit
                placed += 1
        elif style == "supply":
            quota = spec["daily_qty"] - used
            if quota < 2:
                continue
            # дефицит: товар без чужих sell-ордеров
            good = None
            for g in spec["goods"]:
                if g in prod.GOODS and not await repo.has_sell_orders(session, g, exclude=nid):
                    good = g
                    break
            if good is None:
                continue
            unit = max(1, int(auc.fair_value(world, good) * SUPPLY_MULT))
            qty = min(NPC_ORDER_QTY_MAX, quota)
            repo.create_order(session, 0, nid, good, qty, unit, side="sell")
            spent[str(nid)] = used + qty
            placed += 1
    st["spent"] = spent
    _save(world, st)
    return placed


def trader_name(seller_id: int) -> str | None:
    t = TRADERS.get(seller_id)
    return t["name"] if t else None
