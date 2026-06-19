"""Ночная ходка: движок push-your-luck (чистая логика)."""

import random
from types import SimpleNamespace

import pytest

from bot.game import balance, combat, nightrun


class FakeRNG:
    """Управляемый ГСЧ: random()->r, randint->ri, shuffle no-op, choice->первый."""
    def __init__(self, r=0.0, ri=5):
        self._r, self._ri = r, ri

    def random(self):
        return self._r

    def randint(self, a, b):
        return min(b, max(a, self._ri))

    def shuffle(self, x):
        pass

    def choice(self, x):
        return x[0]


def _player():
    return SimpleNamespace(id=1, gold=0, inventory={}, equipment={}, level=5,
                           buff_kind=None, buff_until=None)


def _stub(monkeypatch, armor=0, luck=0):
    monkeypatch.setattr(combat, "player_stats", lambda p=None: {
        "armor": armor, "luck": luck, "damage": 0, "crit": 0, "dmg_taken_mult": 1.0})


# ── математика ──────────────────────────────────────────────────────────────
def test_leg_value_grows():
    assert nightrun.leg_value(1) < nightrun.leg_value(3) < nightrun.leg_value(6)


def test_success_p_falls_with_depth_and_rises_with_gear(monkeypatch):
    _stub(monkeypatch, armor=0, luck=0)
    p = _player()
    r1 = nightrun.start(p, "green_valleys")
    r5 = dict(r1, leg=5)
    assert nightrun.success_p(r1, p, "sneak") > nightrun.success_p(r5, p, "sneak")  # глубже — труднее
    _stub(monkeypatch, armor=60, luck=20)
    assert nightrun.success_p(r5, p, "sneak") > 0.4                                # снаряга поднимает
    # клампы
    _stub(monkeypatch, armor=9999, luck=9999)
    assert nightrun.success_p(r1, p, "fight") <= balance.NIGHTRUN_P_CAP


def test_start_state():
    r = nightrun.start(_player(), "north_wilds")
    assert r["leg"] == 1 and r["state"] == "fork" and r["satchel"] == {}
    assert r["hp"] == balance.BASE_HP


# ── безопасные ноды ─────────────────────────────────────────────────────────
def test_find_loots_no_bust(monkeypatch):
    _stub(monkeypatch)
    r = nightrun.start(_player(), "green_valleys")
    out = nightrun.attempt(r, _player(), "find", FakeRNG())
    assert not out["busted"] and out["loot"] and r["state"] == "crossroad"
    assert nightrun.satchel_value(r["satchel"]) > 0


def test_rest_heals_capped(monkeypatch):
    _stub(monkeypatch)
    r = nightrun.start(_player(), "green_valleys")
    r["hp"] = balance.BASE_HP - 5
    out = nightrun.attempt(r, _player(), "rest", FakeRNG())
    assert out["healed"] == 5 and r["hp"] == balance.BASE_HP        # не выше макс


# ── 🎲 Лихо (честный кубик) ──────────────────────────────────────────────────
def test_gamble_low_roll_busts(monkeypatch):
    _stub(monkeypatch)
    r = nightrun.start(_player(), "green_valleys")
    nightrun._merge(r["satchel"], {"gold": 50})
    out = nightrun.attempt(r, _player(), "gamble", FakeRNG(), roll=1)   # 1 — точно проигрыш
    assert out["busted"] and r["satchel"] == {} and r["state"] == "busted"


def test_gamble_high_roll_loots(monkeypatch):
    _stub(monkeypatch)
    r = nightrun.start(_player(), "green_valleys")
    out = nightrun.attempt(r, _player(), "gamble", FakeRNG(), roll=6)   # 6 — куш
    assert not out["busted"] and out["loot"] and r["state"] == "crossroad"


# ── ⚔️ Засада ────────────────────────────────────────────────────────────────
def test_fight_win_costs_hp(monkeypatch):
    _stub(monkeypatch, armor=80)                                       # высокий шанс
    r = nightrun.start(_player(), "north_wilds")
    out = nightrun.attempt(r, _player(), "fight", FakeRNG(r=0.0, ri=5))
    assert not out["busted"] and out["hp_cost"] > 0 and r["hp"] < balance.BASE_HP


def test_fight_loss_busts(monkeypatch):
    _stub(monkeypatch, armor=0)
    r = nightrun.start(_player(), "north_wilds")
    nightrun._merge(r["satchel"], {"gold": 30})
    out = nightrun.attempt(r, _player(), "fight", FakeRNG(r=1.0))      # 1.0 > p → провал
    assert out["busted"] and r["satchel"] == {}


def test_fight_collapse_when_hp_drained(monkeypatch):
    _stub(monkeypatch, armor=80)
    r = nightrun.start(_player(), "north_wilds")
    r["hp"] = 3                                                        # на последнем издыхании
    out = nightrun.attempt(r, _player(), "fight", FakeRNG(r=0.0, ri=10))
    assert out["busted"] and out.get("collapsed")                     # победил, но рухнул


# ── перекрёсток / банк ──────────────────────────────────────────────────────
def test_push_and_cap():
    r = nightrun.start(_player(), "green_valleys")
    assert nightrun.can_push(r)
    nightrun.push(r)
    assert r["leg"] == 2 and r["state"] == "fork"
    r["leg"] = balance.NIGHTRUN_LEGS
    assert not nightrun.can_push(r)                                    # дальше — только банк


def test_bank_deposits_and_clears():
    p = _player()
    r = nightrun.start(p, "green_valleys")
    r["satchel"] = {"gold": 120, "grain": 8}
    banked = nightrun.bank(r, p)
    assert p.gold == 120 and p.inventory.get("grain") == 8
    assert banked["gold"] == 120 and r["satchel"] == {} and r["state"] == "done"


def test_fork_deterministic_by_seed():
    r = nightrun.start(_player(), "green_valleys", seed=42)
    assert nightrun.fork(r) == nightrun.fork(dict(r))                  # та же развилка
    a, b = nightrun.fork(r)
    assert a in nightrun.KINDS and b in nightrun.KINDS and a != b


# ── кулдаун / активность (для хендлеров) ─────────────────────────────────────
def test_is_active():
    assert not nightrun.is_active({})
    assert not nightrun.is_active({"state": "done"})
    assert nightrun.is_active({"state": "fork"})
    assert nightrun.is_active({"state": "crossroad"})


def test_cooldown_left():
    from datetime import datetime, timedelta, timezone
    p = _player()
    p.night_run_at = None
    assert nightrun.cooldown_left(p) == 0
    p.night_run_at = datetime.now(timezone.utc)
    assert nightrun.cooldown_left(p) > 0
    p.night_run_at = datetime.now(timezone.utc) - timedelta(hours=balance.NIGHTRUN_COOLDOWN_H + 1)
    assert nightrun.cooldown_left(p) == 0
