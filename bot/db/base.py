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
