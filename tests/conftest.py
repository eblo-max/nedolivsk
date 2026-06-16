"""Фабрики-заглушки для чистых юнит-тестов (без БД/сети).

Игрок/босс/мир — это SimpleNamespace с нужными полями; тестируем чистую
игровую логику (settle, mitigate, бой, экономика, баланс) детерминированно.
"""

from types import SimpleNamespace


def make_player(level=5, equipment=None, gold=0, inventory=None, pid=1, name="Тест"):
    return SimpleNamespace(
        id=pid, first_name=name, level=level, equipment=equipment or {},
        gold=gold, inventory=inventory or {},
        buff_kind=None, buff_until=None, hp=35, hp_at=None,
    )


def make_boss(boss_key="bog_troll", hp=None, max_hp=None, status="active",
              contributions=None, state=None, ends_at=None, started_at=None):
    from bot.game import raid
    spec = raid.BOSSES[boss_key]
    mx = max_hp if max_hp is not None else spec.min_hp
    return SimpleNamespace(
        id=1, boss_key=boss_key, hp=hp if hp is not None else mx, max_hp=mx,
        status=status, contributions=contributions or {}, messages={},
        state=state or {}, ends_at=ends_at, started_at=started_at,
    )


def make_world(market=None, scale=1):
    return SimpleNamespace(market=market or {}, market_scale=scale)
