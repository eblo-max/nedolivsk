"""Ночная ходка: движок push-your-luck (чистая логика)."""

import random
from types import SimpleNamespace


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


def test_nr_flavor_covers_all_kinds():
    """Каждый тип ноды из движка ОБЯЗАН иметь флавор развилки (иначе KeyError)."""
    from bot import texts
    missing = set(nightrun.KINDS) - set(texts._NR_FLAVOR)
    assert not missing, f"нет флавора развилки для нод: {missing}"


def test_meet_encounters_well_formed():
    from bot.game import factions
    for enc in nightrun.MEET_ENCOUNTERS.values():
        assert enc["npc"] and enc["scene"] and len(enc["options"]) == 2
        for _id, label, mult, facs in enc["options"]:
            assert label and mult > 0
            for fac, sign in facs:
                assert fac in factions.NAMES and sign in (-1, 1)


def test_riddles_well_formed():
    for rd in nightrun.RIDDLES:
        assert rd["q"] and 2 <= len(rd["options"]) <= 4
        assert 0 <= rd["correct"] < len(rd["options"])
        assert all(o for o in rd["options"])


def test_result_renders_every_kind(monkeypatch):
    """nightrun_result не должен падать ни на одном исходе ноды."""
    from bot import texts
    _stub(monkeypatch)
    p = _player()
    base = nightrun.start(p, "green_valleys", seed=3)
    samples = [
        {"kind": "find", "busted": False, "loot": {"gold": 5}},
        {"kind": "rest", "busted": False, "loot": {}, "healed": 8},
        {"kind": "fight", "busted": False, "loot": {"gold": 9}, "hp_cost": 6},
        {"kind": "sneak", "busted": False, "loot": {"gold": 7}},
        {"kind": "gamble", "busted": False, "loot": {"gold": 12}, "roll": 5},
        {"kind": "meet", "busted": False, "loot": {"gold": 8}, "npc": "🥷 Тест",
         "factions": [("thieves", 4)]},
        {"kind": "quiz", "busted": False, "loot": {"gold": 10}, "correct": True},
        {"kind": "quiz", "busted": False, "loot": {}, "correct": False},
    ]
    for out in samples:
        texts.nightrun_result(p, dict(base, leg=3), out)


def test_fork_renders_every_node_type(monkeypatch):
    """Развилка должна РИСОВАТЬСЯ при любом типе ноды (meet/quiz/rest/find/...).
    Регресс: _NR_FLAVOR без meet/quiz → KeyError → «ходка сбилась»."""
    from bot import texts
    _stub(monkeypatch)
    p = _player()
    for seed in range(1, 60):
        for leg in range(1, balance.NIGHTRUN_LEGS + 1):
            run = nightrun.start(p, "green_valleys", seed=seed)
            run["leg"] = leg
            texts.nightrun_fork(p, run)        # не должно падать ни на одном типе
            kb_mod = __import__("bot.keyboards.inline", fromlist=["nightrun_fork_kb"])
            kb_mod.nightrun_fork_kb(run)


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


# ── 🗣 Встреча (фаза 3): фракц-хук ───────────────────────────────────────────
def test_meet_enters_subchoice(monkeypatch):
    _stub(monkeypatch)
    r = nightrun.start(_player(), "green_valleys", seed=5)
    r["leg"] = 3
    out = nightrun.attempt(r, _player(), "meet", FakeRNG())
    assert r["state"] == "meet" and r.get("meet") in nightrun.MEET_ENCOUNTERS
    assert not out["busted"] and nightrun.is_active(r)


def test_meet_resolve_loot_and_faction(monkeypatch):
    _stub(monkeypatch)
    p = _player()
    r = nightrun.start(p, "green_valleys", seed=5)
    r["leg"] = 3
    nightrun.attempt(r, p, "meet", FakeRNG())
    opt_id = nightrun.MEET_ENCOUNTERS[r["meet"]]["options"][0][0]
    out = nightrun.meet_resolve(r, p, opt_id, FakeRNG())
    assert r["state"] == "crossroad" and "meet" not in r
    assert out["loot"] and out["factions"]
    _fac, delta = out["factions"][0]
    assert abs(delta) == balance.NIGHTRUN_FACTION_NUDGE      # сдвиг ровно на NUDGE


# ── реактивность городской ситуации ──────────────────────────────────────────
def test_situation_lowers_success(monkeypatch):
    _stub(monkeypatch)
    p = _player()
    base = nightrun.start(p, "green_valleys")
    curfew = dict(base, situation="curfew")
    assert nightrun.success_p(curfew, p, "sneak") < nightrun.success_p(base, p, "sneak")


def test_situation_loot_bonus():
    plain = nightrun._bundle(100, "green_valleys", None, random.Random(1))
    boom = nightrun._bundle(100, "green_valleys", "merchant_boom", random.Random(1))
    assert nightrun.satchel_value(boom) > nightrun.satchel_value(plain)


# ── ❓ Загадка (квиз) ─────────────────────────────────────────────────────────
def test_quiz_enters_state(monkeypatch):
    _stub(monkeypatch)
    r = nightrun.start(_player(), "green_valleys", seed=9)
    r["leg"] = 4
    nightrun.attempt(r, _player(), "quiz", FakeRNG())
    assert r["state"] == "quiz" and "riddle" in r and nightrun.is_active(r)
    assert nightrun.current_riddle(r) in nightrun.RIDDLES


def test_quiz_correct_loots_wrong_empty(monkeypatch):
    _stub(monkeypatch)
    p = _player()
    r = nightrun.start(p, "green_valleys", seed=9)
    r["leg"] = 4
    nightrun.attempt(r, p, "quiz", FakeRNG())
    ok = nightrun.quiz_resolve(r, p, True, FakeRNG())
    assert ok["correct"] and ok["loot"] and r["state"] == "crossroad" and "riddle" not in r
    r2 = nightrun.start(p, "green_valleys", seed=9)
    r2["leg"] = 4
    nightrun.attempt(r2, p, "quiz", FakeRNG())
    bad = nightrun.quiz_resolve(r2, p, False, FakeRNG())
    assert not bad["correct"] and not bad["loot"] and r2["state"] == "crossroad"
