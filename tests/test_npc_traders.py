"""NPC-трейдеры биржи: повадки, бюджеты, один ордер за раз."""

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import npc_traders as npct  # noqa: E402


class _Repo:
    def __init__(self, open_cnt=0, has_sells=False):
        self.orders = []
        self.open_cnt = open_cnt
        self.has_sells = has_sells

    async def count_open_orders(self, _s, _nid):
        return self.open_cnt

    async def has_sell_orders(self, _s, _good, exclude=0):
        return self.has_sells

    def create_order(self, _s, chat_id, seller_id, good, qty, unit, side="sell"):
        self.orders.append({"nid": seller_id, "good": good, "qty": qty,
                            "unit": unit, "side": side})


def _world():
    return NS(market={})


def test_friday_full_cast_and_budgets():
    r = _Repo()
    w = _world()
    friday = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    n = asyncio.run(npct.tick(None, r, w, friday))
    nids = {o["nid"] for o in r.orders}
    assert -9001 in nids and -9002 in nids and -9003 in nids and n == 3
    st = w.market["npc"]
    assert st["day"] == "2026-07-03" and st["spent"]
    for o in r.orders:
        assert 1 <= o["qty"] <= npct.NPC_ORDER_QTY_MAX


def test_weekday_no_monastery_and_open_order_skip():
    r = _Repo()
    wed = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    asyncio.run(npct.tick(None, r, _world(), wed))
    assert all(o["nid"] != -9002 for o in r.orders)     # монастырь ждёт пятницы
    r2 = _Repo(open_cnt=1)
    n = asyncio.run(npct.tick(None, r2, _world(), wed))
    assert n == 0 and r2.orders == []                   # ордера висят — не дублируем


def test_supply_only_on_deficit_and_price_styles():
    r = _Repo(has_sells=True)                           # дефицита нет
    wed = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    asyncio.run(npct.tick(None, r, _world(), wed))
    assert all(o["nid"] != -9003 for o in r.orders)
    from bot.game import auction as auc
    w = _world()
    r3 = _Repo()
    asyncio.run(npct.tick(None, r3, w, wed))
    cheap = next(o for o in r3.orders if o["nid"] == -9001)
    fv = auc.fair_value(NS(market={}), cheap["good"])
    assert cheap["side"] == "buy" and cheap["unit"] <= int(fv * npct.CHEAP_MULT) + 1
