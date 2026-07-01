"""Бюджет предметов (WoW-lite): каждый предмет обязан укладываться в бюджет
своего слота × множитель источника. Ловит «дыры» вроде брони-204 у старого
каталога: новый предмет вне допуска не пройдёт CI.
"""

import os

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import items as it  # noqa: E402

TOLERANCE = 0.15   # ±15% от целевого бюджета (гибкость под «характер» предмета)


def test_every_item_fits_budget():
    bad = {}
    for iid, item in it.CATALOG.items():
        pts, target = it.item_budget_points(item), it.item_budget_target(item)
        if not (target * (1 - TOLERANCE) <= pts <= target * (1 + TOLERANCE)):
            bad[iid] = f"{pts:.1f} из {target:.1f}"
    assert not bad, f"вне бюджета: {bad}"


def test_all_slots_and_sources_known():
    for iid, item in it.CATALOG.items():
        assert item.slot in it.SLOT_BUDGET, f"{iid}: слот {item.slot} без бюджета"
        src = it.ITEM_SOURCE.get(iid, "forge")
        assert src in it.SOURCE_MULT, f"{iid}: источник {src} без множителя"


def test_tier_compression_bounds():
    """Разрыв ★→★★★ по боевым статам ≤2.2 (co-op не рвётся), эконом ≤1.6."""
    assert it.TIER_COMBAT_MULT[3] <= 2.2 and it.TIER_ECON_MULT[3] <= 1.6
    assert it._cmul(10, 3) == 22 and it._emul(10, 3) == 16


def test_combat_stats_include_vitality_and_set():
    eq = {"weapon": "orc_axe:3", "chest": "orc_plate:3", "head": "orc_helm:3"}
    st = it.combat_stats(eq)
    assert st["vitality"] > 0
    assert st["damage"] >= int(26 * 2.2) + 10   # оружие ★★★ + сет-бонус
