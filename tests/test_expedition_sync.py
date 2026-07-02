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
