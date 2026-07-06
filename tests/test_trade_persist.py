"""Регресс: изменения оффера купца (counter/вилка) обязаны СОХРАНЯТЬСЯ в БД.

Прод-баг 06.07.2026 (пойман живым вызовом /api/trade на проде): accept считал
вилку и отдавал её в ответе, но `offer['choice']` НЕ писался в базу → take читал
оффер без choice → result='stale', продажа не проходила. Причина — та же, что в
рейде: мутация ВЛОЖЕННОГО оффера «на месте» (offer = get_trade — ссылка внутрь
story) + shallow-copy в _save → SQLAlchemy не видел разницы, UPDATE не слал.
Фикс: flag_modified(player, 'story'). Тест гоняет мутацию через настоящие сессии.
"""
import asyncio

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from bot.db.models import Base, Player
from bot.game import story_state as ss


@compiles(JSONB, "sqlite")  # SQLite не знает JSONB — мапим в JSON для теста
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


async def _run() -> dict | None:
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sf() as s:
            s.add(Player(id=1, first_name="Тест", story={}))
            await s.commit()
        # A: заезжает купец — кладём начальный оффер
        async with sf() as s:
            p = await s.get(Player, 1)
            ss.set_trade(p, {"good": "ale1", "qty": 5, "max_unit": 6.0, "prices": [5, 6, 8]})
            await s.commit()
        # B: как op=accept — берём оффер (ссылка внутрь story) и мутируем ВЛОЖЕННО
        async with sf() as s:
            p = await s.get(Player, 1)
            offer = ss.get_trade(p)
            offer["counter"] = 6
            offer["choice"] = {"mine": {"unit": 6, "qty": 3}, "full": {"unit": 5, "qty": 5}}
            ss.set_trade(p, offer)
            await s.commit()
        # C: свежая сессия — что реально в БД
        async with sf() as s:
            p = await s.get(Player, 1)
            return ss.get_trade(p)
    finally:
        await eng.dispose()


def test_offer_nested_mutation_persists_across_sessions():
    offer = asyncio.run(_run())
    assert offer is not None
    assert offer.get("counter") == 6, "дожатая цена (counter) не сохранилась в БД"
    assert offer.get("choice"), "вилка (choice) не сохранилась → take даёт stale (продажа не проходит)"
    assert offer["choice"]["full"]["qty"] == 5 and offer["choice"]["mine"]["unit"] == 6
