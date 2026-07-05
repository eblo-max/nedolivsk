"""Инвентарь снаряги: сток неодетых вещей + надеть/снять/сменить, крафт не теряет
старую вещь (уходит в сток)."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import items as it  # noqa: E402
from bot.game import logic  # noqa: E402


def _p(eq=None, stash=None):
    return NS(equipment=dict(eq or {}), gear_stash=list(stash or []))


def test_unequip_moves_to_stash():
    p = _p({"weapon": "kovsh:2"})
    assert it.unequip(p, "weapon") is True
    assert p.equipment == {} and p.gear_stash == ["kovsh:2"]
    assert it.unequip(p, "weapon") is False           # уже пусто


def test_equip_from_stash_swaps_old_back():
    p = _p({"weapon": "kovsh:2"}, ["fang_cleaver:1"])
    ok, reason = it.equip(p, "fang_cleaver:1")
    assert ok and reason == ""
    assert p.equipment["weapon"] == "fang_cleaver:1"
    assert "kovsh:2" in p.gear_stash and "fang_cleaver:1" not in p.gear_stash


def test_equip_empty_slot_no_swap():
    p = _p({}, ["kovsh:1"])
    ok, _ = it.equip(p, "kovsh:1")
    assert ok and p.equipment["weapon"] == "kovsh:1" and p.gear_stash == []


def test_equip_not_owned():
    p = _p({}, [])
    ok, reason = it.equip(p, "kovsh:1")
    assert not ok and reason == "not_owned"


def test_stash_of_reads_list():
    p = _p({}, ["kovsh:1", "fartuk:2"])
    assert it.stash_of(p) == ["kovsh:1", "fartuk:2"]


def test_craft_of_different_item_stashes_old():
    """Крафт ДРУГОЙ вещи в занятый слот — старую в сток (не теряем)."""
    p = NS(equipment={"weapon": "kovsh:2"}, gear_stash=[],
           craft_item="fang_cleaver:1",
           craft_ends_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    r = logic.claim_craft(p)
    assert r.ok
    assert p.equipment["weapon"].startswith("fang_cleaver")
    assert any(e.startswith("kovsh") for e in p.gear_stash), "старую вещь потеряли!"


def test_gain_includes_affix_matches_combat_stats():
    """Показ (item_combat_gain — карточка/кузница) == вклад в бой (combat_stats),
    ВКЛЮЧАЯ аффикс. Иначе аффикс-вещи занижены (kreposti не давал брони на показе)."""
    for entry in ("kovsh:2", "kovsh:2:3:zloby", "fang_cleaver:1:0:kreposti", "poyas:2:0:zhivuchesti"):
        iid = it.parse_full(entry)[0]
        slot = it.CATALOG[iid].slot
        gain = it.item_combat_gain(entry)
        real = it.combat_stats({slot: entry})
        for k, v in real.items():
            if k == "level" or v == 0:
                continue
            assert gain.get(k, 0) == v, f"{entry}: бой {k}={v}, показ {gain.get(k, 0)}"


def test_gain_sharpen_delta_ignores_affix():
    """Дельта заточки (next_plus) не должна включать аффикс — он постоянен."""
    d = it.item_combat_gain("kovsh:2:3:zloby", next_plus=4)
    # прирост = только от заточки (plus 3→4), аффикс zloby не участвует
    base = it.item_combat_gain("kovsh:2:3")
    assert d.get("damage", 0) == it.item_combat_gain("kovsh:2:3", next_plus=4).get("damage", 0)
    assert base  # sanity


def test_craft_same_item_upgrade_no_stash():
    """Перековка ТОЙ ЖЕ вещи (апгрейд яруса) — не плодит сток."""
    p = NS(equipment={"weapon": "kovsh:1"}, gear_stash=[],
           craft_item="kovsh:2",
           craft_ends_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    r = logic.claim_craft(p)
    assert r.ok and p.equipment["weapon"].startswith("kovsh:2")
    assert p.gear_stash == []                          # апгрейд заменил на месте
