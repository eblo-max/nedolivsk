"""Черты зверей (фаза C): каждая — реальный эффект + работающий контрпик.
Сравниваем винрейт против зверя с чертой и без неё (или с контрпиком и без)."""

import os
import random
from dataclasses import replace

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, combat  # noqa: E402


def _w(stats, enemy, hp=70, n=600, seed=1):
    return combat.forecast(dict(stats), enemy, hp, n=n, rng=random.Random(seed))[0]


def _plain(eid):
    return replace(combat.ENEMY[eid], traits=())


def test_charge_hurts_early_and_hp_buffers():
    base = _plain("olen")
    charge = replace(base, traits=("charge",))
    st = {"damage": 16, "armor": 18}
    assert _w(st, charge, hp=60) < _w(st, base, hp=60) - 20   # наскок реально больнее
    # запас HP (жаркое/vitality) — прямой контрпик раннему навалу
    assert _w(st, charge, hp=85) > _w(st, charge, hp=60) + 20


def test_enrage_punishes_slow_kills():
    base = _plain("kaban")
    enr = replace(base, traits=("enrage",))
    slow = {"damage": 16, "armor": 25}
    fast = {"damage": 30, "armor": 25}
    # у медленного билда ярость отъедает больше винрейта, чем у бурстового
    drop_slow = _w(slow, base) - _w(slow, enr)
    drop_fast = _w(fast, base) - _w(fast, enr)
    assert drop_slow > drop_fast

def test_lifesteal_heals_and_dodge_counters():
    base = _plain("upyr")
    ls = replace(base, traits=("lifesteal",))
    st = {"damage": 24, "armor": 20}
    assert _w(st, ls) < _w(st, base) - 5              # кровосос живучее
    # уворот запрещает лечение → против кровососа даёт больше, чем против обычного
    gain_vs_ls = _w({**st, "luck": 25}, ls) - _w(st, ls)
    gain_vs_base = _w({**st, "luck": 25}, base) - _w(st, base)
    assert gain_vs_ls >= gain_vs_base


def test_plated_negates_crit_build():
    base = _plain("vozhak")
    pl = replace(base, traits=("plated",))
    crit_build = {"damage": 30, "crit": 60, "armor": 30}
    flat_build = {"damage": 42, "crit": 0, "armor": 30}
    # против обычного крит-билд роскошен, против латника — беспомощнее плоского
    assert _w(crit_build, base, hp=90) > _w(flat_build, base, hp=90) - 5
    assert _w(flat_build, pl, hp=90) >= _w(crit_build, pl, hp=90)


def test_volley_hits_harder():
    base = _plain("tusker")
    vl = replace(base, traits=("volley",))
    st = {"damage": 40, "armor": 50}
    assert _w(st, vl, hp=100) < _w(st, base, hp=100) - 20   # дуплет реально страшен


def test_stoneskin_dampens_crit():
    base = _plain("medved")
    st_ = replace(base, traits=("stoneskin",))
    crit_build = {"damage": 40, "crit": 60, "armor": 60}
    drop = _w(crit_build, base, hp=110) - _w(crit_build, st_, hp=110)
    assert drop >= 8                                   # криты не множатся — больно

def test_burn_pierces_and_speed_counters():
    base = _plain("ataman")
    br = replace(base, traits=("burn",))
    st = {"damage": 110, "armor": 120}
    assert _w(st, br, hp=160) < _w(st, base, hp=160) - 20   # жар ощутимо жжёт
    # контрпик — скорость: больше урона (короче бой) → меньше ожогов → выше шанс
    assert _w({**st, "damage": 130}, br, hp=160) > _w(st, br, hp=160)


def test_stun_skips_player_hit_and_dodge_counters():
    base = _plain("ogr")
    stn = replace(base, traits=("stun",))
    st = {"damage": 120, "armor": 120}
    assert _w(st, stn, hp=160) < _w(st, base, hp=160) - 20   # сотрясение калечит
    # контрпик — уворот: увернулся от 4-го удара → не оглушён (огромная разница)
    gain = _w({**st, "luck": 30}, stn, hp=160) - _w(st, stn, hp=160)
    assert gain >= 30


def test_chill_stacks_and_burst_counters():
    base = _plain("lich")
    ch = replace(base, traits=("chill",))
    st = {"damage": 100, "armor": 120}
    assert _w(st, ch, hp=160) <= _w(st, base, hp=160)  # стужа не в плюс игроку
    # пол стужи: урон не падает ниже доли от базы
    f = combat.resolve({"damage": 20, "armor": 0}, ch, 200, random.Random(2))
    min_pd = min(r["pd"] for r in f.log if r["pd"] > 0 and not r["crit"])
    assert min_pd >= int(20 * balance.TRAIT_CHILL_MAX_FRAC) * 0.6   # с учётом брони/разброса


def test_pickpocket_gold_swing():
    from types import SimpleNamespace as NS
    assert "pickpocket" in combat.ENEMY["razboy"].traits
    # победа над карманником: золото с наваром (+25%)
    p = NS(level=10, equipment={"weapon": "dragon_fang:3", "chest": "dragon_scale:3"},
           buff_kind=None, buff_until=None, hp=None, hp_at=None,
           gold=0, inventory={}, hunt_ready_at=None, reputation=0,
           tavern=NS(products={}, reputation=0))
    res = combat.hunt(p, "razboy", rng=random.Random(4))
    if res.fight.win:                       # BiS против Т3 — почти всегда победа
        base_hi = combat.ENEMY["razboy"].gold[1]
        assert res.loot["gold"] <= int(base_hi * (1 + balance.TRAIT_PICKPOCKET_WIN_BONUS))
        assert res.loot["gold"] > 0
    assert balance.TRAIT_PICKPOCKET_LOSE_MULT == 2


def test_all_bestiary_traits_have_ui_meta():
    """У каждой черты в бестиарии есть машинное имя из известного набора —
    фронт покажет бейдж и подсказку (словари TRAIT/TRAIT_HINT)."""
    known = {"venom", "evasive", "charge", "enrage", "lifesteal", "plated",
             "volley", "stoneskin", "pickpocket", "burn", "stun", "chill"}
    for e in combat.ENEMIES:
        for t in e.traits:
            assert t in known, f"{e.id}: неизвестная черта {t}"
