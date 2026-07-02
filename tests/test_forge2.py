"""Кузница 2.0: формат записи слота, заточка, аффиксы."""

import os
import random

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, items, logic  # noqa: E402


def test_parse_full_backward_compatible():
    assert items.parse_full("kovsh") == ("kovsh", 1, 0, "")
    assert items.parse_full("kovsh:2") == ("kovsh", 2, 0, "")
    assert items.parse_full("kovsh:2:3") == ("kovsh", 2, 3, "")
    assert items.parse_full("kovsh:2:3:zloby") == ("kovsh", 2, 3, "zloby")
    # мусор зажимается, неизвестный аффикс отбрасывается
    assert items.parse_full("kovsh:9:99:xxx") == ("kovsh", items.TIER_MAX, items.PLUS_MAX, "")
    # старый parse_entry не ломается на новом формате
    assert items.parse_entry("kovsh:2:3:zloby") == ("kovsh", 2)


def test_make_entry_roundtrip():
    e = items.make_entry("sablya", 3, 4, "farta")
    assert items.parse_full(e) == ("sablya", 3, 4, "farta")
    assert items.make_entry("sablya", 2) == "sablya:2"   # без хвостов — как раньше


def test_sharpen_boosts_combat_stats():
    itm = next(i for i in items.CATALOG.values() if i.damage > 10)
    base = items.combat_stats({itm.slot: items.make_entry(itm.id, 1)})
    plus5 = items.combat_stats({itm.slot: items.make_entry(itm.id, 1, 5)})
    assert plus5["damage"] == int(itm.damage * 1.20)      # +4% × 5
    assert plus5["damage"] > base["damage"]


def test_plus_zero_identical_to_old():
    two = list(items.CATALOG.values())[:2]
    eq = {it.slot: items.make_entry(it.id, 1) for it in two}
    eq2 = {k: v + ":0" for k, v in eq.items()}
    old = items.combat_stats(eq)
    assert any(old.values())                    # не сравниваем нули с нулями
    assert old == items.combat_stats(eq2)


def test_affix_adds_flat_by_tier():
    itm = next(i for i in items.CATALOG.values() if i.damage > 0)
    noaff = items.combat_stats({itm.slot: items.make_entry(itm.id, 3)})
    aff = items.combat_stats({itm.slot: items.make_entry(itm.id, 3, 0, "kreposti")})
    assert aff["armor"] == noaff["armor"] + 3 * 3          # +3×ярус брони
    assert aff["damage"] == noaff["damage"]


def test_display_name():
    itm = next(iter(items.CATALOG.values()))
    e = items.make_entry(itm.id, 2, 3, "zloby")
    assert items.display_name(e) == f"{itm.name} злобы +3"
    assert items.display_name(items.make_entry(itm.id, 2)) == itm.name


def test_roll_affix_rates_and_t1_never():
    r = random.Random(7)
    got = sum(1 for _ in range(2000) if logic.roll_affix(2, r))
    assert 400 < got < 600                                  # ~25% на T2
    assert all(logic.roll_affix(1, random.Random(i)) == "" for i in range(100))


def test_sharpen_tables_consistent():
    assert set(balance.SHARPEN_COST_GOLD) == set(balance.SHARPEN_SUCCESS)
    assert max(balance.SHARPEN_COST_GOLD) == items.PLUS_MAX
    costs = [balance.SHARPEN_COST_GOLD[i] for i in sorted(balance.SHARPEN_COST_GOLD)]
    assert costs == sorted(costs)                           # дороже с каждым уровнем
