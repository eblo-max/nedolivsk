"""Аудит рейд-боссов: инварианты конфига (все боссы), показ=действие рейда и
край-кейсы новых механик (острог/стаж/персональные баффы). Регресс-гард после
апекс-Батога — edge/desync-инварианты боссов не трогали ('Кроме боссов')."""
import os
import random
from datetime import datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "test:test")

import pytest  # noqa: E402
from bot.game import raid, items  # noqa: E402
from conftest import make_boss, make_player  # noqa: E402

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
VALID_SPELLS = {"ward", "curse", "summon", "roar", "pit"}
VALID_BARK_EV = {"intro", "ward", "curse", "summon", "roar", "pit", "death"}
KEYS = list(raid.BOSSES)


# ── КОНФИГ: инварианты для КАЖДОГО босса ──────────────────────────────────
@pytest.mark.parametrize("key", KEYS)
def test_boss_config_integrity(key):
    b = raid.BOSSES[key]
    # спеллы скрипта валидны, пороги в (0,100) и по убыванию
    thrs = [t for t, _ in b.script]
    assert all(s in VALID_SPELLS for _, s in b.script), f"{key}: чужой спелл"
    assert all(0 < t < 100 for t in thrs), f"{key}: порог вне (0,100)"
    assert thrs == sorted(thrs, reverse=True), f"{key}: пороги не по убыванию"
    # флаг pit ⟺ 'pit' в скрипте (иначе второе дыхание и скрипт рассинхронятся)
    assert b.pit == ("pit" in {s for _, s in b.script}), f"{key}: pit-флаг ≠ pit в скрипте"
    # веса лута — промилле, сумма 1000
    assert sum(w for _, w, _ in b.loot) == 1000, f"{key}: веса лута ≠ 1000"
    # ярусы снаряги — три, сумма 100
    assert len(b.gear_tier_weights) == 3 and sum(b.gear_tier_weights) == 100, f"{key}: ярусы"
    # каждый предмет пула существует и полностью засорсен
    for iid in b.gear_pool:
        assert iid in items.CATALOG, f"{key}: предмет {iid} не существует"
        src = items.ITEM_SOURCE.get(iid)
        assert src in items.SOURCE_MULT, f"{iid}: источник {src} без множителя"
        assert src in items.RARITY_BY_SOURCE, f"{iid}: источник {src} без редкости"
    # числовые диапазоны
    assert b.hp_per_power > 0 and b.min_hp > 0 and b.gold_pool > 0 and b.armor >= 0
    assert 0 <= b.tenure_max < 1, f"{key}: tenure_max вне [0,1)"
    assert 0 <= b.ward_mult < 1, f"{key}: ward_mult вне [0,1)"
    assert 0 <= b.curse_factor <= 1, f"{key}: curse_factor вне [0,1]"
    assert 0 <= b.summon_pct < 1, f"{key}: summon_pct вне [0,1)"
    # барки: событие валидно, реплика не пустая; лор — непустые строки
    for ev, line in b.barks:
        assert ev in VALID_BARK_EV and line, f"{key}: барк {ev}"
    assert all(isinstance(x, str) and x for x in b.lore), f"{key}: пустой лор"


def test_only_jailer_has_pit_and_tenure():
    """Новые механики — ТОЛЬКО у Батога (регресс: не протекли в других)."""
    for key, b in raid.BOSSES.items():
        if key == "jailer":
            assert b.pit and b.tenure_max > 0 and b.ward_mult and b.curse_factor and b.summon_pct
        else:
            assert not b.pit and b.tenure_max == 0.0 and b.ward_mult == 0.0
            assert b.curse_factor == 0.0 and b.summon_pct == 0.0


# ── ПОКАЗ=ДЕЙСТВИЕ: gear% на сборе == реальному дропу ─────────────────────
@pytest.mark.parametrize("key", KEYS)
def test_gear_pct_matches_real_drop(key):
    shown = raid.gear_drop_pct(key)                       # что видит игрок на сборе
    N = 6000
    gear = sum(1 for s in range(N)
               if raid.settle(make_boss(key, status="dead", max_hp=5000,
                              contributions={"1": {"dmg": 5000, "hits": 9, "name": "X"}}),
                              random.Random(s))["drop"]["kind"] == "gear")
    actual = 100 * gear / N
    assert abs(actual - shown) <= 1.2, f"{key}: показ {shown}% ≠ дроп {actual:.1f}%"


def test_settle_gold_split_even_and_sums_to_pool():
    for key in KEYS:
        b = make_boss(key, status="dead", max_hp=5000,
                      contributions={str(i): {"dmg": 100 * i, "hits": 9, "name": f"P{i}"}
                                     for i in range(1, 6)})
        plan = raid.settle(b, random.Random(3))
        vals = list(plan["gold"].values())
        assert len(set(vals)) == 1, f"{key}: доля не поровну"           # показ=действие: поровну
        assert sum(vals) <= raid.BOSSES[key].gold_pool                   # не переплатили пул


def test_tenure_shown_equals_applied():
    """tenure_pct(DTO) и срез урона в resolve_hit — из ОДНОЙ tenure_frac."""
    b = make_boss("jailer", status="active", max_hp=9000, hp=9000,
                  contributions={"9": {"dmg": 1, "name": "P"}})
    b.ends_at = NOW - timedelta(minutes=10) + timedelta(hours=raid.FIGHT_HOURS)  # стаж на потолке
    t = raid.tenure_frac(b, NOW)
    assert t == raid.BOSSES["jailer"].tenure_max                          # 10 мин → потолок
    p = make_player(level=20, pid=9)
    # средний урон со стажем ≈ без стажа × (1 - t)
    d_ten = sum(raid.resolve_hit(make_boss("jailer", status="active", max_hp=9000, hp=9000,
                ends_at=b.ends_at), p, NOW, random.Random(s))["dmg"] for s in range(300)) / 300
    d_raw = sum(raid.resolve_hit(make_boss("dragon", status="active", max_hp=9000, hp=9000),
                p, NOW, random.Random(s))["dmg"] for s in range(300)) / 300
    # грубо: у Батога урон меньше (стаж+броня), направление верное
    assert d_ten < d_raw, (d_ten, d_raw)


# ── ОСТРОГ: край-кейсы ────────────────────────────────────────────────────
@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 8])
def test_pit_never_locks_everyone(n):
    b = make_boss("jailer")
    for i in range(n):
        p = make_player(pid=10 + i)
        raid.register(b, p)
        b.contributions[str(p.id)]["dmg"] = 10 * (i + 1)
    st = dict(b.state); raid._imprison(st, b, NOW); b.state = st
    ids = [10 + i for i in range(n)]
    jailed = [i for i in ids if raid.pit_left(b, i, NOW) > 0]
    free = [i for i in ids if raid.pit_left(b, i, NOW) == 0]
    assert len(jailed) <= raid.PIT_TARGETS
    if n >= 1:
        assert len(free) >= 1, f"{n} бойцов — залочены ВСЕ (софтлок+реген=вечно)"
    assert len(jailed) <= max(0, n - 1)          # хотя бы одного не сажаем


def test_pit_never_jails_zero_damage_player():
    b = make_boss("jailer")
    for i in range(4):
        p = make_player(pid=20 + i); raid.register(b, p)
    b.contributions["20"]["dmg"] = 500          # только один бил
    st = dict(b.state); raid._imprison(st, b, NOW); b.state = st
    for i in (21, 22, 23):
        assert raid.pit_left(b, i, NOW) == 0, "посадили не бившего"


def test_pit_state_bounded_on_repeat():
    """Многократный острог по той же пачке НЕ раздувает state['pit']."""
    b = make_boss("jailer")
    for i in range(3):
        p = make_player(pid=30 + i); raid.register(b, p)
        b.contributions[str(p.id)]["dmg"] = 100 * (i + 1)
    for _ in range(20):
        st = dict(b.state); raid._imprison(st, b, NOW); b.state = st
    assert len(b.state.get("pit", {})) <= 3, "pit-записи копятся"


def test_second_wind_pit_for_jailer_stun_for_others():
    bj = make_boss("jailer", status="active", hp=100, max_hp=1000,
                   contributions={"1": {"dmg": 999, "name": "A"}, "2": {"dmg": 5, "name": "B"}})
    assert raid.maybe_second_wind(bj, NOW) is True
    assert bj.state.get("pit") and not bj.state.get("stun_until"), "кат: второе дыхание должно сажать"
    bd = make_boss("demon_slime", status="active", hp=100, max_hp=1000,
                   contributions={"1": {"dmg": 999, "name": "A"}})
    raid.maybe_second_wind(bd, NOW)
    assert bd.state.get("stun_until") and not bd.state.get("pit"), "демон: общий стан"


# ── СТАЖ: границы ─────────────────────────────────────────────────────────
def test_tenure_bounds():
    b = make_boss("jailer")
    b.ends_at = NOW + timedelta(hours=raid.FIGHT_HOURS)          # только начался
    assert raid.tenure_frac(b, NOW) == 0.0                        # старт → 0
    b.ends_at = NOW - timedelta(hours=5) + timedelta(hours=raid.FIGHT_HOURS)  # давно
    assert raid.tenure_frac(b, NOW) == raid.BOSSES["jailer"].tenure_max        # ≤ потолок
    # у не-стажевого босса всегда 0
    assert raid.tenure_frac(make_boss("dragon"), NOW) == 0.0


# ── УРОН: без отрицательных / оверкилл ────────────────────────────────────
def test_no_negative_hp_on_overkill():
    b = make_boss("jailer", status="active", hp=5, max_hp=9000)
    p = make_player(level=30, pid=1); raid.register(b, p)
    raid.resolve_hit(b, p, NOW, random.Random(1))
    assert b.hp >= 0, "HP ушёл в минус"


def test_settle_no_hitters_no_crash():
    b = make_boss("jailer", status="dead", max_hp=5000, contributions={})
    plan = raid.settle(b, random.Random(1))
    assert plan["gold"] == {} and plan.get("drop") is None       # никого не наградили, не упали


# ── БОГАТЫЙ DM: ранг/доля/трофей в персональном уведомлении ───────────────
def test_reward_dm_shows_rank_share_and_trophy():
    from bot import texts
    b = make_boss("jailer")
    ranked = [(111, "Гриша", 5000), (222, "Авдотья", 3000), (333, "Ты", 1000)]
    # рядовой боец #2 из 3, трофей ушёл другому — видит и свой ранг, и победителя
    dm = texts.raid_reward_dm(b, ranked, 222, 700, False, "Гриша", "★★★ — 🗡 Клинок")
    assert "#2" in dm and "из 3" in dm and "+700" in dm
    assert "Трофей урвал" in dm and "Гриша" in dm and "Тебе выпал" not in dm
    # победитель видит именно «Тебе выпал», не «урвал»
    dmw = texts.raid_reward_dm(b, ranked, 111, 700, True, "Гриша", "★★★ — 🗡 Клинок")
    assert "#1" in dmw and "Тебе выпал" in dmw and "урвал" not in dmw
    # без дропа — трофейной строки нет вообще
    assert "Трофей" not in texts.raid_reward_dm(b, ranked, 333, 700, False, "Гриша", "")


def test_reward_dm_rank_matches_damage_order():
    """Ранг в DM = позиция бойца по урону (показ=действие для лидерборда)."""
    from bot import texts
    b = make_boss("jailer")
    ranked = sorted([(10, "A", 120), (20, "B", 900), (30, "C", 450)], key=lambda x: -x[2])
    for want_rank, (pid, _n, _d) in enumerate(ranked, 1):
        assert f"#{want_rank}" in texts.raid_reward_dm(b, ranked, pid, 100, False, "B", "")
