"""Лавка скупщика: цены с наценкой, дневной лимит, без полуфабрикатов, недобор."""

from datetime import datetime, timezone
from types import SimpleNamespace

from bot.game import balance, shop


def _p(gold=1000, inv=None, buys=None):
    return SimpleNamespace(gold=gold, inventory=inv or {}, shop_buys=buys or {})


def test_price_is_base_times_markup():
    assert shop.price("wood") == 6           # 2.0 × 3
    assert shop.price("grain") == 8          # 2.5 × 3 → ceil
    assert shop.price("hops") == 12          # 4.0 × 3


def test_sellable_only_raw_no_semiproducts():
    s = set(shop.sellable())
    assert {"wood", "grain", "hops"} <= s
    assert "malt" not in s and "flour" not in s and "ingot" not in s   # их делают пристройки


def test_max_affordable_capped_by_gold():
    p = _p(gold=20)                          # хватит на 3 дерева (6 каждое)
    assert shop.max_affordable(p, "wood") == 3


def test_max_affordable_capped_by_daily_limit():
    now_iso = datetime.now(timezone.utc).isoformat()
    p = _p(gold=10**9, buys={"wood": {"t": now_iso, "q": balance.SHOP_DAILY_LIMIT - 5}})
    assert shop.max_affordable(p, "wood") == 5      # лимит, а не золото


def test_record_buy_reduces_room():
    p = _p()
    assert shop.buy_room(p, "wood") == balance.SHOP_DAILY_LIMIT
    shop.record_buy(p, "wood", 10)
    assert shop.buy_room(p, "wood") == balance.SHOP_DAILY_LIMIT - 10


def test_shortfall_and_bill():
    have = {"wood": 50}                       # есть 50 дерева, зерна нет
    cost = {"gold": 250, "wood": 75, "grain": 60, "hops": 40}
    short = shop.shortfall(have, cost)
    assert short == {"wood": 25, "grain": 60, "hops": 40}
    assert shop.bill({"wood": 10}) == 60      # 10 × 6
