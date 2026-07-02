"""Цель недели фракции: ротация, прогресс, пир, идемпотентность награды."""

import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import fgoal  # noqa: E402


def _reset():
    fgoal._pending.clear()
    fgoal._feast_until = 0.0


def test_goal_rotates_by_week():
    a = fgoal.current_goal(datetime(2026, 7, 1, tzinfo=timezone.utc))
    b = fgoal.current_goal(datetime(2026, 7, 8, tzinfo=timezone.utc))
    assert a["fac"] != b["fac"] and a["week"] != b["week"]
    assert "{target}" not in a["text"]                 # текст отрендерен


def test_progress_reward_and_idempotent_feast():
    _reset()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    goal = fgoal.current_goal(now)
    w = NS(market={})
    fgoal.note(goal["kind"], goal["target"] - 5)
    assert fgoal.flush(w, now) is None                 # ещё не добили
    st = w.market["fgoal"]
    assert st["done"] == goal["target"] - 5 and not st["rewarded"]
    fgoal.note(goal["kind"], 10)
    ann = fgoal.flush(w, now)
    assert ann and "ЦЕЛЬ НЕДЕЛИ ВЗЯТА" in ann          # анонс один раз
    assert fgoal.feast_mult() == fgoal.FEAST_RETAIL_MULT
    fgoal.note(goal["kind"], 100)
    assert fgoal.flush(w, now) is None                 # награда идемпотентна
    _reset()


def test_new_week_resets_progress():
    _reset()
    w = NS(market={})
    d1 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    g1 = fgoal.current_goal(d1)
    fgoal.note(g1["kind"], 50)
    fgoal.flush(w, d1)
    d2 = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    fgoal.flush(w, d2)
    assert w.market["fgoal"]["week"] == fgoal.week_key(d2)
    assert w.market["fgoal"]["done"] == 0
    _reset()


def test_hydrate_restores_feast():
    _reset()
    until = time.time() + 3600
    w = NS(market={"fgoal": {"feast_until": until}})
    fgoal.hydrate(w)
    assert fgoal.feast_mult() > 1.0
    _reset()


def test_state_for_ui():
    _reset()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    g = fgoal.current_goal(now)
    w = NS(market={})
    fgoal.note(g["kind"], g["target"] // 2)
    fgoal.flush(w, now)
    st = fgoal.state(w, now)
    assert st["pct"] == 50 and st["done"] == g["target"] // 2
    assert st["fac"] == g["fac"] and not st["feast"]
    _reset()
