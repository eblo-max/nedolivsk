"""Бригады: показ = списание (жалоба игрока 02.07 — цифры «не хватает» врали)."""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import buildings as bld, logic  # noqa: E402


def _pl(gold=10_000, level=3, inv=None, equipment=None):
    t = NS(level=level, production={}, products={}, upgrades=[], buildings=[],
           reputation=50, comfort=5, capacity=20)
    return NS(gold=gold, level=level, equipment=equipment or {}, inventory=inv or {},
              expeditions=[], region="green_valleys", buff_kind=None, buff_until=None,
              perks={}, created_at=None, tavern=t, story=None), t


def test_goals_use_real_building_cost():
    """Подсказка «на что не хватает» считает от cost_of (как экран стройки)."""
    p, t = _pl(inv={})
    goals, _ = logic.expedition_goals(p, t, max_goals=99)
    by_label = {label: short for label, short in goals}
    for bid in bld.ORDER:
        b = bld.CATALOG[bid]
        label = f"{b.emoji} {b.name}"
        if label not in by_label:
            continue
        real = bld.cost_of(b)
        for res, short in by_label[label].items():
            assert short == real[res], (
                f"{label}/{res}: подсказка {short} ≠ реальная цена {real[res]}")


def test_quote_equals_actual_charge():
    """Плата в панели = плате при отправке (со всеми множителями снаряги)."""
    from bot.game import items
    # снаряга со скидкой на плату, если есть в каталоге
    disc = next((i for i in items.CATALOG.values() if i.pay_discount_pct), None)
    eq = {disc.slot: items.make_entry(disc.id, 1)} if disc else {}
    p, t = _pl(equipment=eq)
    pay, hours = logic.expedition_quote(p, t)
    g0 = p.gold
    r = logic.start_expedition(p, t, "wood")
    assert r.ok and r.pay == pay == g0 - p.gold
    assert hours > 0


def test_gain_quote_equals_claimed_amount(monkeypatch):
    """Показ добычи в панели == реальному начислению (без «фарта»)."""
    import random as _r
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(_r, "randint", lambda a, b: 100)   # фарт не выпал
    p, t = _pl()
    p.tavern = t
    q = logic.expedition_gain_quote(p, t, "wood")
    p.expeditions = [{"resource": "wood",
                      "ends_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                      "notified": True}]
    claimed = logic.claim_expeditions(p)
    assert claimed and claimed[0][0] == "wood" and claimed[0][1] == q


def test_nightrun_rest_display_equals_heal():
    """«Привал лечит N» в стейте == реальному лечению на привале."""
    from bot.game import nightrun as nr
    p, _t = _pl()
    run = nr.start(p, "green_valleys")
    shown = nr.rest_heal_amount(run)
    run["hp"] = 1                                   # есть куда лечиться
    run["state"] = "fork"
    out = nr.attempt(run, p, "rest")
    assert out["healed"] == shown > 0


def test_income_rate_quote_reflects_gear():
    """Доход/ч на экране чувствует снарягу с +доходом (как реальный пассив)."""
    from bot.game import items
    inc = next(i for i in items.CATALOG.values() if i.income_pct)
    p0, t0 = _pl()
    t0.income_rate = 100
    base = logic.income_rate_quote(p0, t0)
    p1, t1 = _pl(equipment={inc.slot: items.make_entry(inc.id, 1)})
    t1.income_rate = 100
    assert logic.income_rate_quote(p1, t1) > base > 0


def test_income_quote_base_rate_matches_upgrade_preview():
    """Превью дохода при апгрейде == факту после апгрейда (жалоба: 14 vs 15).
    Котировка с base_rate след. уровня == котировке после смены income_rate."""
    from bot.game import logic, balance
    p, t = _pl()
    t.income_rate = 40
    next_base = int(balance.stats_for_level(t.level + 1)["income_rate"])
    preview = logic.income_rate_quote(p, t, base_rate=next_base)
    t.income_rate = next_base                        # как после апгрейда
    fact = logic.income_rate_quote(p, t)
    assert preview == fact, (preview, fact)
