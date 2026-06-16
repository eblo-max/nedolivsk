"""Регресс: урон по рейд-боссу обязан СОХРАНЯТЬСЯ в БД (а не теряться при коммите).

Прод-баг 16.06.2026: hp босса доходил до 0, но в contributions у всех dmg=0 —
награды получал «никто/один». Причина: apply_hit менял вложенный rec «на месте»,
портя снимок SQLAlchemy → колонка contributions не записывалась. Тест гоняет
apply_hit через настоящие сессии (как в боте) и проверяет, что урон в базе есть.
"""

import asyncio
from types import SimpleNamespace

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from bot.db.models import Base, RaidBoss
from bot.game import raid
from conftest import make_player


@compiles(JSONB, "sqlite")  # SQLite не знает JSONB — мапим в JSON для теста
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


async def _run_fight() -> SimpleNamespace:
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sf() as s:
            boss = RaidBoss(
                boss_key="rat_king", status="active", hp=100, max_hp=100,
                contributions={"1": {"dmg": 0, "hits": 0, "name": "A"},
                               "2": {"dmg": 0, "hits": 0, "name": "B"}},
                messages={}, state={})
            s.add(boss)
            await s.commit()
            bid = boss.id
        p1, p2 = make_player(pid=1, name="A"), make_player(pid=2, name="B")
        # Чередуем удары двух бойцов, КАЖДЫЙ — отдельной сессией + commit (как в боте).
        for who in (p1, p2, p1, p1, p2):
            async with sf() as s:
                boss = await s.get(RaidBoss, bid)
                raid.apply_hit(boss, who, 7)
                await s.commit()
        # Перечитываем из БД свежей сессией и снимаем чистые значения (без ORM).
        async with sf() as s:
            boss = await s.get(RaidBoss, bid)
            return SimpleNamespace(boss_key=boss.boss_key, hp=boss.hp,
                                   contributions=dict(boss.contributions))
    finally:
        await eng.dispose()


def test_apply_hit_persists_damage_across_sessions():
    boss = asyncio.run(_run_fight())
    c = boss.contributions
    assert boss.hp == 65                       # 5 ударов по 7 сняли 35 hp
    assert c["1"]["dmg"] == 21 and c["1"]["hits"] == 3   # урон бойца №1 сохранён
    assert c["2"]["dmg"] == 14 and c["2"]["hits"] == 2   # урон бойца №2 сохранён
    # settle награждает только dmg>0 — оба должны попасть
    plan = raid.settle(boss)
    assert set(plan["gold"]) == {1, 2}         # оба в раздаче золота
    assert plan["winner"] in (1, 2)
