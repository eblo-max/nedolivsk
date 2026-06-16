"""Мировые события: множители каналов, щит новичка, трейд-оффы, баланс набора."""

import random

from bot.game import worldevent
from conftest import make_player


def teardown_function():
    worldevent.set_active(None)


def test_no_event_is_neutral():
    worldevent.set_active(None)
    p = make_player(level=10)
    assert worldevent.income_mult(p) == 1.0
    assert worldevent.harvest_mult(p) == 1.0
    assert worldevent.sale_mult(p) == 1.0
    assert worldevent.exp_speed_mult(p) == 1.0
    assert worldevent.prod_speed_mult(p) == 1.0


def test_buff_applies_to_everyone_incl_newbie():
    worldevent.set_active("harvest")                       # +20% добыча
    assert worldevent.harvest_mult(make_player(level=10)) == 1.20
    assert worldevent.harvest_mult(make_player(level=1)) == 1.20   # бафф — всем


def test_debuff_shields_newbie():
    worldevent.set_active("plague")                        # −15% доход (дебафф)
    assert worldevent.income_mult(make_player(level=10)) == 0.85
    assert worldevent.income_mult(make_player(level=1)) == 1.0     # новичок защищён


def test_tradeoff_newbie_keeps_only_upside():
    worldevent.set_active("frost")                         # добыча −15%, доход +15%
    new = make_player(level=1)
    assert worldevent.harvest_mult(new) == 1.0             # минус снят щитом
    assert worldevent.income_mult(new) == 1.15             # плюс остаётся
    vet = make_player(level=10)
    assert worldevent.harvest_mult(vet) == 0.85
    assert worldevent.income_mult(vet) == 1.15


def test_speed_tradeoff_shield_direction():
    worldevent.set_active("rain")                          # вылазки медленнее, варка быстрее
    new = make_player(level=1)
    assert worldevent.exp_speed_mult(new) == 1.0           # замедление снято щитом
    assert worldevent.prod_speed_mult(new) == 0.80         # ускорение варки остаётся
    assert worldevent.exp_speed_mult(make_player(level=10)) == 1.25


def test_roll_valid_and_set_balanced():
    r = random.Random(1)
    assert {worldevent.roll(r) for _ in range(500)} <= set(worldevent.EVENTS)
    buffs = [e for e in worldevent.EVENTS.values()
             if e.income > 1 or e.harvest > 1 or e.sale > 1 or e.exp_speed < 1]
    debuffs = [e for e in worldevent.EVENTS.values()
               if e.income < 1 or e.harvest < 1 or e.sale < 1
               or e.exp_speed > 1 or e.prod_speed > 1]
    assert buffs and debuffs                               # есть и добро, и зло
    assert all(0.7 <= v <= 1.3 for e in worldevent.EVENTS.values()
               for v in (e.income, e.harvest, e.sale, e.exp_speed, e.prod_speed))  # мягко
