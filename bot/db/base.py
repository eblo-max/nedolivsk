from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables() -> None:
    """Создаёт таблицы при старте (для MVP; позже заменить на Alembic)."""
    from sqlalchemy import text

    from bot.db import models  # noqa: F401 — регистрация моделей

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Мини-миграции для уже существующих таблиц
        await conn.execute(text(
            "ALTER TABLE world ADD COLUMN IF NOT EXISTS "
            "fair_pre_announced BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS chat_id BIGINT"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "story JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE cities ADD COLUMN IF NOT EXISTS "
            "last_situation_end TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE cities ADD COLUMN IF NOT EXISTS "
            "market JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE world ADD COLUMN IF NOT EXISTS "
            "season INTEGER NOT NULL DEFAULT -1"
        ))
        await conn.execute(text(
            "ALTER TABLE world ADD COLUMN IF NOT EXISTS holiday VARCHAR(48)"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "expedition_resource VARCHAR(16)"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "expedition_ends_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "expedition_notified BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Переход на 3 зоны карты мира (12.06.2026)
        await conn.execute(text(
            "UPDATE players SET region = 'north_wilds' "
            "WHERE region IN ('north', 'forest')"
        ))
        await conn.execute(text(
            "UPDATE players SET region = 'green_valleys' WHERE region = 'river'"
        ))
        await conn.execute(text(
            "UPDATE players SET region = 'red_wastes' WHERE region = 'trade'"
        ))
        await conn.execute(text(
            "ALTER TABLE taverns ADD COLUMN IF NOT EXISTS map_slot INTEGER UNIQUE"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "equipment JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS craft_item VARCHAR(32)"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS craft_ends_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "craft_notified BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Переход на единый инвентарь (Ярус 0). Колонка nullable: разовый
        # перелив только для ещё не мигрированных строк (inventory IS NULL),
        # чтобы опустошённый инвентарь не «возрождался» из старых колонок.
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS inventory JSONB"
        ))
        await conn.execute(text(
            "UPDATE players SET inventory = jsonb_build_object("
            "'wood', COALESCE(wood, 0), 'grain', COALESCE(grain, 0), "
            "'hops', COALESCE(hops, 0)) WHERE inventory IS NULL"
        ))
        # Мультислот вылазок: одиночная вылазка -> список бригад
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS "
            "expeditions JSONB NOT NULL DEFAULT '[]'::jsonb"
        ))
        await conn.execute(text(
            "UPDATE players SET expeditions = jsonb_build_array(jsonb_build_object("
            "'resource', expedition_resource, 'ends_at', to_jsonb(expedition_ends_at), "
            "'notified', expedition_notified)), expedition_resource = NULL "
            "WHERE expedition_resource IS NOT NULL AND expeditions = '[]'::jsonb"
        ))
        # Слот стройки пристроек
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS build_item VARCHAR(32)"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS build_ends_at TIMESTAMPTZ"
        ))
        # Производство на пристройках (партии зданий)
        await conn.execute(text(
            "ALTER TABLE taverns ADD COLUMN IF NOT EXISTS "
            "production JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE taverns ADD COLUMN IF NOT EXISTS "
            "products JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE taverns ADD COLUMN IF NOT EXISTS "
            "auction JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        # Унификация ключей погреба: '1'/'2'/'3' эля -> 'ale1'/'ale2'/'ale3'
        await conn.execute(text(
            "UPDATE taverns SET products = (products - '1' - '2' - '3') "
            "|| CASE WHEN products ? '1' THEN jsonb_build_object('ale1', products->'1') ELSE '{}'::jsonb END "
            "|| CASE WHEN products ? '2' THEN jsonb_build_object('ale2', products->'2') ELSE '{}'::jsonb END "
            "|| CASE WHEN products ? '3' THEN jsonb_build_object('ale3', products->'3') ELSE '{}'::jsonb END "
            "WHERE products ?| array['1','2','3']"
        ))
