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
def _result(won, dealt):                # минимальный результат симуляции для settle
    return {"won": won, "dealt": dealt, "n": len(dealt)}


def test_settle_win_rewards_by_contribution():
    plan = inv.settle(_inv(_reg(10, 40)), _result(True, {1: 100, 2: 400}), random.Random(1))
    assert plan["won"] is True
    # больше НАНЕСЁННЫЙ УРОН — больше золота; репутация всем фикс
    assert plan["gold"][2] > plan["gold"][1] > 0
    assert plan["rep"][1] == plan["rep"][2] == inv.WIN_REP
    assert set(plan["res"][1]) == set(inv.HAUL_RES)
    # трофей — лучшему по урону (MVP = pid 2)
    assert plan["trophy"] is not None and plan["trophy"]["pid"] == 2
    assert plan["trophy"]["drop"]["kind"] in ("gold", "res")


def test_settle_loss_penalizes_registered_no_trophy():
    plan = inv.settle(_inv(_reg(5, 5)), _result(False, {1: 0, 2: 0}), random.Random(1))
    assert plan["won"] is False and plan["trophy"] is None
    assert all(g == -inv.LOSS_GOLD for g in plan["gold"].values())
    assert all(r == -inv.LOSS_REP for r in plan["rep"].values())
    assert plan["res"] == {}


def test_settle_empty_roster_is_loss_no_payouts():
    plan = inv.settle(_inv({}), _result(False, {}), random.Random(1))
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


# ── тактическая симуляция: роли, профиль, исход по композиции ────────────────
def _gear(d=0, c=0, a=0, l=0):
    return {"damage": d, "crit": c, "armor": a, "luck": l}


def test_role_from_build():
    assert inv.role_of(_gear(a=14)) == "tank"          # броня → авангард
    assert inv.role_of(_gear(d=18, c=25)) == "archer"  # урон/крит → стрелок
    assert inv.role_of(_gear(l=16)) == "scout"         # удача → разведка
    assert inv.role_of(_gear(d=1, c=1, a=1, l=1)) == "ratnik"  # слабый билд → линия


def test_battle_profile_from_gear_and_might():
    p = inv.battle_profile(_gear(d=10, c=20, a=8, l=10), might=40)
    assert p["dmg"] > 10                       # мощь + снаряга в урон
    assert 0 < p["crit"] <= 0.75 and p["armor"] == 8 and 0 < p["dodge"] <= 0.30
    assert p["hp"] > inv.WB_HP_BASE            # мощь даёт живучесть


_GEAR = {"tank": _gear(4, 5, 13, 4), "archer": _gear(17, 28, 2, 4),
         "scout": _gear(6, 8, 3, 15)}


def _army(comp, might=30):
    out, pid = [], 1
    for kind, cnt in comp.items():
        for _ in range(cnt):
            p = inv.battle_profile(_GEAR[kind], might); p["pid"] = pid
            out.append(p); pid += 1
    return out


def test_simulate_deterministic():
    a = _army({"tank": 2, "archer": 4, "scout": 2})
    r1, r2 = inv.simulate(a, seed=7), inv.simulate(a, seed=7)
    assert r1["won"] == r2["won"] and r1["dealt"] == r2["dealt"]


def test_front_line_and_turnout_decide():
    # достаточная армия с линией фронта (танки/ратники держат) — победа
    assert inv.simulate(_army({"tank": 8, "archer": 8, "scout": 3}), 1)["won"] is True
    # совсем нет линии фронта (одни рубаки) — орда прорывается и фокусит → провал
    assert inv.simulate(_army({"archer": 8}), 1)["won"] is False
    # крошечная явка — фронта мало, выкосят → провал
    assert inv.simulate(_army({"tank": 1, "archer": 2}), 1)["won"] is False


def test_simulate_empty_and_tracks_contribution():
    r0 = inv.simulate([], seed=1)
    assert r0["won"] is False and r0["n"] == 0 and r0["dealt"] == {}
    # ВСЕ ключи должны быть и у пустого ростера (иначе KeyError на /api/taverns)
    need = {"timeline", "stats", "dealt", "fell", "events", "won", "rounds",
            "orc_hp_max", "orc_hp_left", "n"}
    assert need <= set(r0) and r0["timeline"] == [] and r0["stats"] == {}
    a = _army({"archer": 8})
    r = inv.simulate(a, seed=3)
    assert set(r["dealt"]) == {p["pid"] for p in a}     # вклад посчитан всем
    assert len(r["fell"]) > 0                            # были павшие


def test_simulate_full_stats_and_roles():
    a = _army({"tank": 2, "archer": 4, "scout": 2})
    r = inv.simulate(a, seed=1)
    assert set(r["stats"]) == {p["pid"] for p in a}
    for st in r["stats"].values():
        assert set(st) == {"dmg", "crit", "blocked", "fell"}
    tanks = [p["pid"] for p in a if p["role"] == "tank"]
    archers = [p["pid"] for p in a if p["role"] == "archer"]
    # танк блокирует больше; стрелок наносит больше крита
    assert max(r["stats"][t]["blocked"] for t in tanks) > max(r["stats"][x]["blocked"] for x in archers)
    assert max(r["stats"][x]["crit"] for x in archers) > max(r["stats"][t]["crit"] for t in tanks)


def test_timeline_real_hp_armor_buffs():
    r = inv.simulate(_army({"tank": 6, "archer": 10}), 1)
    tl = r["timeline"]
    assert tl and len(tl) == r["rounds"]
    # в каждом раунде — полное состояние для карты
    assert all(set(s) >= {"hp", "armor", "ward", "curse", "adds", "enraged"} for s in tl)
    # под щитом (ward) броня выше базовой
    if any(s["ward"] for s in tl):
        assert max(s["armor"] for s in tl if s["ward"]) > inv.ORC_ARMOR
    # на победе HP добит в ноль; иначе — остался
    assert (tl[-1]["hp"] == 0) == r["won"]


def test_build_report_rows_sorted_with_rewards():
    i = _inv(_reg(10, 40))
    sim = {"won": True, "dealt": {1: 100, 2: 400}, "n": 2,
           "stats": {1: {"dmg": 100, "crit": 10, "blocked": 50, "fell": False},
                     2: {"dmg": 400, "crit": 200, "blocked": 5, "fell": True}}}
    plan = inv.settle(i, sim, random.Random(1))
    rep = inv.build_report(i, sim, plan)
    assert rep[0]["dmg"] >= rep[1]["dmg"]                 # сорт по урону
    assert any(r["trophy"] for r in rep)                 # у MVP — трофей
    need = {"name", "role", "dmg", "crit", "blocked", "fell", "gold", "rep", "trophy", "pid"}
    assert all(need <= set(r) for r in rep)


def test_army_hp_timeline_and_readiness():
    # HP дружины есть в результате и в каждом снимке таймлайна, не растёт по ходу боя
    a = _army({"tank": 3, "archer": 4, "scout": 2})
    r = inv.simulate(a, seed=1)
    assert r["army_hp_max"] > 0 and "army_hp_left" in r
    tl = r["timeline"]
    assert all("army" in s for s in tl)
    assert tl[0]["army"] >= tl[-1]["army"]               # дружина только убывает
    # пустой ростер — ключи на месте (иначе KeyError на /api/taverns)
    e = inv.simulate([], seed=1)
    assert e["army_hp_max"] == 0 and e["army_hp_left"] == 0
    # «готовность»: победный состав — в зелёной зоне (≥ рубежа), проигрышный — ниже
    win = inv.simulate(_army({"tank": 8, "archer": 8, "scout": 3}), 1)
    lose = inv.simulate(_army({"tank": 1, "archer": 2}), 1)
    assert win["won"] and inv.readiness(win) >= inv.VICTORY_LINE
    assert not lose["won"] and 0.0 <= inv.readiness(lose) < inv.VICTORY_LINE
    assert inv.readiness(e) == 0.0


# ── Прогрессия орды: урон-от-силы + эскалация между нашествиями ───────────────
def test_escalation_curve_and_snapshot():
    assert inv.escalation(0) == 1.0                       # первое нашествие — без усиления
    assert abs(inv.escalation(3) - (1 + inv.ESCAL_PER_WIN * 3)) < 1e-9
    assert inv.escalation(10_000) == inv.ESCAL_CAP        # потолок (анти-runaway)
    assert inv.escalation(-5) == 1.0                      # мусор → пол

    class _Obj:
        pass
    o = _Obj()
    assert inv.escal_of(o) == 1.0                         # старая запись без поля → 1.0
    o.escal = 1.5
    assert inv.escal_of(o) == 1.5
    o.escal = None
    assert inv.escal_of(o) == 1.0                         # NULL → 1.0
    o.escal = 0.3
    assert inv.escal_of(o) == 1.0                         # не ниже 1.0


def test_escalation_makes_orc_tougher():
    a = _army({"tank": 8, "archer": 8, "scout": 3})
    base = inv.simulate(a, seed=1)
    esc = inv.simulate(a, seed=1, escal=2.0)
    assert esc["orc_hp_max"] > base["orc_hp_max"]         # эскалация: орда толще
    # та же армия против усиленной орды — не легче (меньше выживших ИЛИ потеря победы)
    assert (esc["won"], esc["army_hp_left"]) <= (base["won"], base["army_hp_left"])


def test_escalation_can_flip_marginal_win_to_loss():
    # достаточная армия побеждает обычную орду, но сильная эскалация ломает победу
    a = _army({"tank": 6, "archer": 6, "scout": 2})
    assert inv.simulate(a, seed=1)["won"] is True
    assert inv.simulate(a, seed=1, escal=inv.ESCAL_CAP)["won"] is False


def test_weak_turnout_attack_unchanged_floor():
    # слабая малая явка (мощь < ATK_REF_POWER) — урон орды зафлорен на ORC_ATK:
    # тонкий баланс «5-7 слабых» не трогаем. Проверяем через инвариант: эскалация=1
    # и состав совпадает с тем, что тестируется в test_front_line_and_turnout_decide.
    weak = [dict(inv.battle_profile(_gear(1, 1, 1, 1), 26), pid=i + 1) for i in range(3)]
    assert all(p["role"] == "ratnik" for p in weak)      # слабый билд → линия
    power = sum(inv._unit_output(p, inv.ORC_ARMOR) for p in weak)
    assert power < inv.ATK_REF_POWER                      # действительно «слабая» зона
    # детерминизм с эскалацией сохраняется
    r1 = inv.simulate(weak, seed=7, escal=1.0)
    r2 = inv.simulate(weak, seed=7, escal=1.0)
    assert r1["dealt"] == r2["dealt"] and r1["won"] == r2["won"]


# ── Орочий сет: обрывки чертежа с победы + крафт + сет-бонус ──────────────────
def test_orc_scrap_drops_on_win_deterministic():
    reg = {str(i): {"name": f"p{i}", "might": 30, "role": "ratnik"} for i in range(1, 8)}
    iv = _inv(reg)
    sim = {"won": True, "dealt": {i: 100 for i in range(1, 8)}, "n": 7}
    p1 = inv.settle(iv, sim, random.Random(42))
    p2 = inv.settle(iv, sim, random.Random(42))
    assert p1["res"] == p2["res"]                         # детерминизм
    got = [pid for pid, r in p1["res"].items() if r.get("orc_scrap")]
    assert got and all(p1["res"][pid]["orc_scrap"] == 1 for pid in got)  # кто-то получил по 1
    # проигрыш — обрывков нет
    lose = inv.settle(iv, {"won": False, "dealt": {}, "n": 7}, random.Random(42))
    assert lose["res"] == {}


def test_orc_set_craftable_needs_scrap():
    from bot.game import items as itm
    for iid in itm.ORC_SET:
        item = itm.CATALOG[iid]
        assert item.craftable                              # куётся (в отличие от боссовых)
        assert item.cost.get("orc_scrap", 0) > 0           # но нужен обрывок чертежа
        assert "orc_scrap" in itm.tier_cost(item, 1)       # обрывок в реальной цене


def test_orc_set_bonus_only_when_complete():
    from bot.game import items as itm
    full = {"head": "orc_helm:1", "chest": "orc_plate:1", "weapon": "orc_axe:1"}
    part = {"head": "orc_helm:1", "weapon": "orc_axe:1"}
    assert itm.orc_set_complete(full) and not itm.orc_set_complete(part)
    base = itm.combat_stats(part)
    bonus = itm.combat_stats(full)
    # полный сет добавляет ровно ORC_SET_BONUS поверх суммы предметов
    assert bonus["armor"] == base["armor"] + itm.CATALOG["orc_plate"].armor + itm.ORC_SET_BONUS["armor"]
    assert bonus["damage"] - (base["damage"]) == itm.ORC_SET_BONUS["damage"]
    assert bonus["luck"] == itm.ORC_SET_BONUS["luck"]


# ── ФАЗА 1: стойки (выбор роли), варлорд-трейт орды, доска готовности ────────
def test_stance_sets_role_and_tilt():
    base = inv.battle_profile(_gear(a=2), 30)                  # слабый билд → ratnik авто
    assert base["stance"] == ""
    front = inv.battle_profile(_gear(a=2), 30, "front")
    assert front["role"] == "tank" and front["stance"] == "front"
    assert front["armor"] == base["armor"] + 6                # уклон брони за стойку
    strike = inv.battle_profile(_gear(a=2), 30, "strike")
    assert strike["role"] == "archer" and strike["dmg"] > base["dmg"]   # +урон
    flank = inv.battle_profile(_gear(a=2), 30, "flank")
    assert flank["role"] == "scout" and flank["dodge"] > base["dodge"]  # +уворот
    assert inv.battle_profile(_gear(a=2), 30, "line")["role"] == "ratnik"


def test_trait_deterministic_and_varied():
    ids = [SimpleNamespace(id=i) for i in range(1, 40)]
    for x in ids:
        assert inv.trait_of(x) in inv.TRAITS
        assert inv.trait_of(x)[0] == inv.trait_of(SimpleNamespace(id=x.id))[0]   # стабильно по id
    assert len({inv.trait_of(x)[0] for x in ids}) >= 3        # разнообразие трейтов


def test_trait_changes_the_fight_directionally():
    a = _army({"tank": 4, "archer": 3})                       # маргинальная — исход чувствителен
    plain = inv.simulate(a, 1)
    armored = inv.simulate(a, 1, trait="armored")
    siege = inv.simulate(a, 1, trait="siege")
    # трейт РЕАЛЬНО что-то меняет (не no-op)
    key = lambda r: (r["rounds"], r["orc_hp_left"], r["army_hp_left"])
    assert key(armored) != key(plain) or key(siege) != key(plain)
    assert armored["orc_hp_left"] >= plain["orc_hp_left"]     # латная — свалить труднее
    assert siege["army_hp_left"] <= plain["army_hp_left"]     # осадная — бьёт больнее


def test_composition_and_need_hint():
    c = inv.composition(_army({"tank": 2, "archer": 3, "scout": 1}))
    assert c["tank"] == 2 and c["archer"] == 3 and c["scout"] == 1
    assert c["front"] == 2 and c["n"] == 6                    # фронт = танки+ратники
    assert "ФРОНТ" in inv.need_hint(_army({"archer": 5}), None)   # нет строя → тревога
    armored = next(t for t in inv.TRAITS if t[0] == "armored")
    hint = inv.need_hint(_army({"tank": 3}), armored)         # против латной нет рубак
    assert "атаку" in hint.lower()
    assert inv.need_hint([], None) and inv.need_hint(_army({"tank": 3, "archer": 2}), armored)
