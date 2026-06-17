"""Рейд-босс: дележ, броня, self-баффы/дебаффы, редкость лута."""

import random
from datetime import datetime, timedelta, timezone

from bot.game import raid
from conftest import make_boss, make_player

UTC = timezone.utc


def _hit(boss, pid, dmg, name="b"):
    c = dict(boss.contributions)
    rec = c.get(str(pid)) or {"dmg": 0, "hits": 0, "name": name}
    rec["dmg"] += dmg
    c[str(pid)] = rec
    boss.contributions = c


# ── settle: дележ золота и трофея ──────────────────────────────────────────
def test_settle_gold_equal_and_conserved():
    boss = make_boss("dragon", status="dead")
    for i in (1, 2, 3, 4):
        _hit(boss, i, 100 + i * 10)  # разный урон
    plan = raid.settle(boss, random.Random(1))
    pool = raid.BOSSES["dragon"].gold_pool
    assert sum(plan["gold"].values()) <= pool                 # не печатаем сверх пула
    assert len(set(plan["gold"].values())) == 1               # поровну, не по вкладу
    assert plan["gold"][1] == pool // 4


def test_settle_excludes_non_hitters():
    boss = make_boss("rat_king", status="dead")
    _hit(boss, 1, 50)
    boss.contributions["2"] = {"dmg": 0, "hits": 0, "name": "x"}  # записался, не бил
    plan = raid.settle(boss, random.Random(2))
    assert 2 not in plan["gold"]
    assert plan["winner"] == 1


def test_settle_winner_is_a_hitter_and_gold_le_pool_at_scale():
    boss = make_boss("rat_king", status="dead")
    n = raid.BOSSES["rat_king"].gold_pool + 50   # бойцов больше пула
    for i in range(n):
        _hit(boss, i, 5)
    plan = raid.settle(boss, random.Random(3))
    assert sum(plan["gold"].values()) <= raid.BOSSES["rat_king"].gold_pool


def test_loot_gear_only_from_boss_pool_and_rarity_scales():
    rng = random.Random(7)
    for key in raid.BOSSES:
        pool = set(raid.BOSSES[key].gear_pool)
        seen, gear_hits = set(), 0
        for _ in range(20000):
            boss = make_boss(key, status="dead",
                             contributions={"1": {"dmg": 9, "hits": 1, "name": "a"}})
            d = raid.settle(boss, rng)["drop"]
            if d["kind"] == "gear":
                seen.add(d["item_id"]); gear_hits += 1
                assert 1 <= d["tier"] <= 3
        assert seen <= pool and seen                      # только из пула босса
    # Инверсия по сложности: лёгкий босс роняет снарягу ЧАЩЕ (слабую), дракон —
    # реже всего (его снаряга сильнейшая → редкий престиж-трофей).
    def rate(key):
        r = random.Random(99)
        g = sum(raid.settle(make_boss(key, status="dead",
                contributions={"1": {"dmg": 9, "hits": 1, "name": "a"}}), r)["drop"]["kind"] == "gear"
                for _ in range(30000))
        return g / 30000
    assert rate("rat_king") > rate("bog_troll") > rate("dragon")


# ── броня (mitigate) ───────────────────────────────────────────────────────
def test_mitigate_floor_and_scaling():
    assert raid.mitigate("dragon", 5) == 1                 # слабый удар гасится в 1
    assert raid.mitigate("rat_king", 100) == 100 - raid.BOSSES["rat_king"].armor
    assert raid.mitigate("dragon", 100) < raid.mitigate("rat_king", 100)


def test_hp_scales_with_turnout_and_floor():
    assert raid.hp_for("dragon", 1) == raid.BOSSES["dragon"].min_hp     # пол HP
    assert raid.hp_for("dragon", 100) == 100 * raid.BOSSES["dragon"].hp_per_fighter


# ── регистрация ────────────────────────────────────────────────────────────
def test_register_once():
    boss = make_boss(status="gathering", contributions={})
    p = make_player()
    assert raid.register(boss, p) is True
    assert raid.register(boss, p) is False                 # повторно нельзя
    assert raid.is_registered(boss, p.id)


# ── self-баффы / дебафф ────────────────────────────────────────────────────
def test_regen_only_when_stalled():
    now = datetime.now(UTC)
    fresh = make_boss("dragon", hp=1000, max_hp=2000, ends_at=now + timedelta(minutes=40),
                      contributions={"1": {"dmg": 5, "last": now.isoformat()}})
    assert raid.regen_if_stalled(fresh, now) == 0          # только что били
    stalled = make_boss("dragon", hp=1000, max_hp=2000, ends_at=now + timedelta(minutes=40),
                        contributions={"1": {"dmg": 5,
                                             "last": (now - timedelta(minutes=10)).isoformat()}})
    healed = raid.regen_if_stalled(stalled, now)
    assert healed > 0 and stalled.hp == 1000 + healed


def test_roar_stuns_then_cooldowns():
    now = datetime.now(UTC)
    boss = make_boss("dragon", ends_at=now + timedelta(minutes=40),
                     started_at=now - timedelta(minutes=20),
                     contributions={"1": {"dmg": 5, "last": now.isoformat()}})
    assert raid.roar_if_due(boss, now) is True
    assert raid.stun_left(boss, now) > 0
    assert raid.roar_if_due(boss, now) is False            # кулдаун рыка


def test_second_wind_once_and_heals():
    now = datetime.now(UTC)
    low = make_boss("dragon", hp=int(2000 * 0.29), max_hp=2000)
    assert raid.maybe_second_wind(low, now) is True
    assert low.hp > int(2000 * 0.29)                       # подлечился
    assert raid.maybe_second_wind(low, now) is False       # только раз
    high = make_boss("dragon", hp=1400, max_hp=2000)
    assert raid.maybe_second_wind(high, now) is False      # не на 70%


def test_cooldown_takes_max_of_personal_and_stun():
    now = datetime.now(UTC)
    # боец без личного кулдауна (ещё не бил), но под общим оглушением рыка
    boss = make_boss("dragon",
                     state={"stun_until": (now + timedelta(seconds=90)).isoformat()},
                     contributions={"1": {"dmg": 0}})
    assert raid.cooldown_left(boss, 1, now) >= 80          # ждать из-за стана
    assert raid.stunned(boss, 1, now) is True


def test_gear_drop_pct_matches_loot_weights():
    # веса лута в промилле (сумма 1000) → % снаряги = вес/10.
    # Инверсия по сложности: лёгкий босс щедрее на (слабую) снарягу, дракон — редок.
    assert raid.gear_drop_pct("rat_king") == 8.0
    assert raid.gear_drop_pct("bog_troll") == 5.0
    assert raid.gear_drop_pct("dragon") == 3.0
    assert raid.gear_drop_pct("rat_king") > raid.gear_drop_pct("dragon")  # лёгкий > сильный
    assert raid.gear_drop_pct("нет такого") == 0.0


def test_gather_announce_states_loot_rules():
    from types import SimpleNamespace
    from datetime import datetime, timezone, timedelta
    from bot import texts
    b = SimpleNamespace(boss_key="dragon",
                        gather_until=datetime.now(timezone.utc) + timedelta(minutes=8),
                        contributions={})
    s = texts.raid_gather_screen(b)
    assert "Добыча" in s                                   # блок добычи есть
    assert "~3%" in s                                      # честный шанс снаряги (дракон редок)
    assert "поровну" in s                                  # золото делится
    assert "реально бил" in s                              # доля — только бившим
    assert "<blockquote expandable>" in s                  # лор спрятан под разворот
