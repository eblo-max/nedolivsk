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


def test_advance_full_lifecycle():
    """Полный цикл: пауза → старт → активно → истечение → пауза → новый старт."""
    import random as _r
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from bot.game import worldevent as we

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    world = SimpleNamespace(event_kind=None, event_until=None, event_next_at=None)
    rng = _r.Random(1)

    # 1) первый тик — не палит сразу, ставит кулдаун
    assert we.advance(world, now, rng) is None
    assert world.event_kind is None and world.event_next_at is not None

    # 2) до конца кулдауна — тишина
    assert we.advance(world, now + timedelta(hours=1), rng) is None
    assert world.event_kind is None

    # 3) кулдаун прошёл — стартует событие
    t = world.event_next_at + timedelta(minutes=1)
    started = we.advance(world, t, rng)
    assert started is not None and world.event_kind == started.id
    assert world.event_until > t and world.event_next_at is None

    # 4) пока активно — то же событие, не сбрасывается
    assert we.advance(world, world.event_until - timedelta(minutes=1), rng) is None
    assert world.event_kind == started.id

    # 5) истекло — снимается, ставится новый кулдаун
    assert we.advance(world, world.event_until + timedelta(seconds=1), rng) is None
    assert world.event_kind is None and world.event_next_at is not None

    # 6) следующий кулдаун прошёл — новое событие
    again = we.advance(world, world.event_next_at + timedelta(minutes=1), rng)
    assert again is not None and world.event_kind == again.id


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
