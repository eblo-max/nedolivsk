"""Ивент «Орда орков»: мощь, порог, исход, раздача/штраф, фазы (чистая логика)."""

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot.game import invasion as inv

UTC = timezone.utc
T0 = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def _tav(level=1, buildings=0):
    return SimpleNamespace(level=level, buildings=list(range(buildings)))


def _inv(registered=None, threshold=100, status="battle",
         started=T0, gather_min=inv.GATHER_MINUTES):
    g = started + timedelta(minutes=gather_min)
    return SimpleNamespace(
        registered=registered or {}, threshold=threshold, status=status,
        started_at=started, gather_until=g, resolve_at=inv.resolve_at(g))


def _reg(*mights):
    return {str(i): {"name": f"p{i}", "tx": 0.1, "ty": 0.1, "might": m}
            for i, m in enumerate(mights, 1)}


# ── мощь и порог ──────────────────────────────────────────────────────────
def test_tavern_might_grows_with_level_and_buildings():
    base = inv.tavern_might(_tav(1, 0))
    assert base == inv.MIGHT_BASE + inv.MIGHT_PER_LEVEL
    assert inv.tavern_might(_tav(5, 0)) > base                  # уровень даёт мощь
    assert inv.tavern_might(_tav(1, 3)) > base                  # пристройки дают мощь


def test_threshold_scales_and_has_floor():
    assert inv.horde_threshold(0) == inv.MIN_THRESHOLD          # пол для пустого мира
    big = inv.horde_threshold(10000)
    assert big == round(inv.COVERAGE * 10000)                   # доля суммарной мощи
    assert big > inv.MIN_THRESHOLD


def test_registered_might_sums():
    i = _inv(_reg(10, 20, 30))
    assert inv.registered_might(i) == 60
    assert inv.registered_count(i) == 3


# ── исход ─────────────────────────────────────────────────────────────────
def test_win_when_might_meets_threshold():
    assert inv.is_won(_inv(_reg(60, 60), threshold=100)) is True   # 120 ≥ 100
    assert inv.is_won(_inv(_reg(30), threshold=100)) is False      # 30 < 100


def test_win_boundary_inclusive():
    assert inv.is_won(_inv(_reg(100), threshold=100)) is True      # ровно порог — победа


# ── раздача / штраф ────────────────────────────────────────────────────────
def test_settle_win_rewards_by_contribution():
    plan = inv.settle(_inv(_reg(10, 40), threshold=20), random.Random(1))   # победа
    assert plan["won"] is True
    # больше мощь — больше золота; репутация всем фикс
    assert plan["gold"][2] > plan["gold"][1] > 0
    assert plan["rep"][1] == plan["rep"][2] == inv.WIN_REP
    # хабар-ресурсы каждому участнику
    assert set(plan["res"][1]) == set(inv.HAUL_RES)
    # ровно один трофей случайному участнику
    assert plan["trophy"] is not None and plan["trophy"]["pid"] in (1, 2)
    assert plan["trophy"]["drop"]["kind"] in ("gold", "res")


def test_settle_loss_penalizes_registered_no_trophy():
    plan = inv.settle(_inv(_reg(5, 5), threshold=1000), random.Random(1))   # провал
    assert plan["won"] is False and plan["trophy"] is None
    assert all(g == -inv.LOSS_GOLD for g in plan["gold"].values())
    assert all(r == -inv.LOSS_REP for r in plan["rep"].values())
    assert plan["res"] == {}


def test_settle_empty_roster_is_loss_no_payouts():
    plan = inv.settle(_inv({}, threshold=50), random.Random(1))
    assert plan["won"] is False and plan["gold"] == {} and plan["trophy"] is None


# ── фазы/тайминги ──────────────────────────────────────────────────────────
def test_phase_transitions_by_time():
    i = _inv(status="gathering")
    assert inv.phase(i, T0 + timedelta(minutes=5)) == "gathering"   # в окне сбора
    assert inv.phase(i, T0 + timedelta(minutes=21)) == "battle"     # сбор кончился
    i.status = "won"
    assert inv.phase(i, T0 + timedelta(hours=2)) == "won"           # терминал — по статусу


def test_resolve_at_after_gather_plus_battle():
    i = _inv()
    span = (i.resolve_at - i.gather_until).total_seconds()
    assert span == inv.MARCH_SECONDS + inv.BATTLE_SECONDS


def test_elapsed_and_gather_left():
    i = _inv(status="gathering")
    assert inv.gather_left(i, T0) == inv.GATHER_MINUTES * 60
    assert inv.elapsed_secs(i, T0 + timedelta(seconds=90)) == 90
