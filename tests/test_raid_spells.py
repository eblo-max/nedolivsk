"""Рейд-боссы: фазы, ярость и спеллбук (щит / проклятье / призыв миньонов)."""

import random
from datetime import datetime, timedelta, timezone

from bot.game import raid
from conftest import make_boss, make_player

UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _started(boss_key="dragon", **kw):
    """Босс в бою, «начатый» час назад — чтобы все касты были due."""
    return make_boss(boss_key, ends_at=NOW + timedelta(minutes=1), **kw)


# ── фазы ярости ─────────────────────────────────────────────────────────────
def test_phase_thresholds():
    assert raid.phase(make_boss("dragon", hp=1000, max_hp=1000)) == 1   # 100%
    assert raid.phase(make_boss("dragon", hp=700, max_hp=1000)) == 1    # 70% > 66%
    assert raid.phase(make_boss("dragon", hp=500, max_hp=1000)) == 2    # 50%
    assert raid.phase(make_boss("dragon", hp=300, max_hp=1000)) == 3    # 30% < 33%


def test_enrage_regen_stronger_in_higher_phase():
    # один и тот же max_hp, простой >5 мин: в бешенстве (фаза 3) лечит сильнее.
    last = (NOW - timedelta(minutes=10)).isoformat()
    p1 = make_boss("dragon", hp=900, max_hp=1000, ends_at=NOW + timedelta(minutes=40),
                   contributions={"1": {"dmg": 5, "last": last}})    # фаза 1
    p3 = make_boss("dragon", hp=200, max_hp=1000, ends_at=NOW + timedelta(minutes=40),
                   contributions={"1": {"dmg": 5, "last": last}})    # фаза 3
    assert raid.regen_if_stalled(p3, NOW) > raid.regen_if_stalled(p1, NOW)


# ── 🛡 щит / 💀 проклятье: режут урон ─────────────────────────────────────────
def _dmg_once(boss, seed=1):
    return raid.resolve_hit(boss, make_player(level=10), NOW, random.Random(seed))["dmg"]


def test_ward_reduces_damage():
    plain = _dmg_once(make_boss("dragon"))
    warded = _dmg_once(make_boss(
        "dragon", state={"ward_until": (NOW + timedelta(seconds=60)).isoformat()}))
    assert warded < plain


def test_curse_reduces_damage():
    plain = _dmg_once(make_boss("dragon"))
    cursed = _dmg_once(make_boss(
        "dragon", state={"curse_until": (NOW + timedelta(seconds=60)).isoformat()}))
    assert cursed < plain


# ── 👹 миньоны: щит бьётся первым, потом — босс ──────────────────────────────
def test_summon_shield_absorbs_then_boss():
    boss = make_boss("dragon", hp=2000, max_hp=2000,
                     state={"adds_hp": 100000,
                            "adds_until": (NOW + timedelta(seconds=200)).isoformat()})
    res = raid.resolve_hit(boss, make_player(level=10), NOW, random.Random(2))
    assert res["adds_dmg"] > 0 and res["dmg"] == 0   # весь урон ушёл в щит
    assert boss.hp == 2000                            # босс не задет
    assert res["adds_left"] < 100000                  # щит просел


def test_summon_clear_lets_overflow_hit_boss():
    boss = make_boss("dragon", hp=2000, max_hp=2000,
                     state={"adds_hp": 1,
                            "adds_until": (NOW + timedelta(seconds=200)).isoformat()})
    res = raid.resolve_hit(boss, make_player(level=10), NOW, random.Random(3))
    assert res["adds_cleared"] and res["adds_left"] == 0
    assert boss.hp < 2000                             # остаток прошёл в босса


def test_summon_merges_back_partial_heal_on_ttl():
    boss = make_boss("dragon", hp=1000, max_hp=2000,
                     state={"adds_hp": 400,
                            "adds_until": (NOW - timedelta(seconds=1)).isoformat()})
    events = raid.cast_tick(boss, NOW)
    assert "adds_merge" in events
    assert raid.adds_hp(boss) == 0
    assert boss.hp == 1000 + int(400 * raid.SUMMON_MERGE_FRAC)   # лечит лишь половину


# ── cast_tick: касты только из спеллбука ─────────────────────────────────────
def test_cast_tick_fires_full_spellbook_for_dragon():
    boss = _started("dragon")
    events = raid.cast_tick(boss, NOW)
    assert raid.ward_left(boss, NOW) > 0      # 🛡 есть в спеллбуке
    assert raid.curse_left(boss, NOW) > 0     # 💀 есть
    assert raid.adds_hp(boss) > 0             # 👹 есть
    assert {"ward", "curse", "summon"} <= set(events)


def test_cast_tick_respects_spellbook_rat_has_no_ward():
    boss = _started("rat_king")               # spellbook = summon, curse (без ward)
    raid.cast_tick(boss, NOW)
    assert raid.ward_left(boss, NOW) == 0     # щит крыса не ставит
    assert raid.adds_hp(boss) > 0 or raid.curse_left(boss, NOW) > 0


def test_cast_tick_enrage_event_once_per_phase():
    boss = _started("dragon", hp=400, max_hp=1000)   # фаза 2
    ev1 = raid.cast_tick(boss, NOW)
    assert "enrage2" in ev1
    ev2 = raid.cast_tick(boss, NOW + timedelta(seconds=30))
    assert "enrage2" not in ev2               # повторно фазу не объявляем


# ── resolve_hit: запись вклада и снятие HP ───────────────────────────────────
def test_resolve_hit_records_and_damages():
    boss = make_boss("dragon", hp=5000, max_hp=5000)
    p = make_player(level=15, pid=42)
    res = raid.resolve_hit(boss, p, NOW, random.Random(5))
    assert res["dmg"] > 0 and boss.hp == 5000 - res["dmg"]
    assert boss.contributions["42"]["dmg"] == res["dmg"]
    assert boss.contributions["42"]["hits"] == 1
