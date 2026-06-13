"""Read-only верификация ярмарки (этапы 1-2) на боевой БД.

Ничего не пишет: проверяет применённые миграции, состояние мира, чаты и
рабочие read-пути (get_or_create_world, all_chat_ids). В конце rollback.
Подключение берётся из DATABASE_URL/.env через bot.config.
"""

import asyncio
from urllib.parse import urlparse

from sqlalchemy import text

from bot.config import settings
from bot.db import repo
from bot.db.base import engine, session_factory


def _host() -> str:
    return urlparse(settings.database_url.replace("+asyncpg", "")).hostname or "?"


async def main() -> None:
    print("Хост БД:", _host())
    async with engine.connect() as conn:
        tabs = [r[0] for r in await conn.execute(text(
            "select table_name from information_schema.tables "
            "where table_schema='public' order by table_name"))]
        print("Таблицы:", tabs)
        print("  world:", "world" in tabs, "| chats:", "chats" in tabs)

        wcols = [r[0] for r in await conn.execute(text(
            "select column_name from information_schema.columns "
            "where table_name='world' order by ordinal_position"))]
        print("Колонки world:", wcols)
        print("  fair_pre_announced:", "fair_pre_announced" in wcols)

        for r in await conn.execute(text(
                "select id, fair_until, next_fair_at, fair_pre_announced from world")):
            print("Строка world:", dict(r._mapping))

        chats = list(await conn.execute(text("select chat_id, title from chats")))
        print("Чатов:", len(chats))
        for r in chats:
            cid = r._mapping["chat_id"]
            print(f"  {str(cid)[:4]}***  «{r._mapping['title']}»")

    async with session_factory() as s:
        w = await repo.get_or_create_world(s)
        print("get_or_create_world -> id", w.id,
              "| fair_pre_announced:", w.fair_pre_announced)
        ids = await repo.all_chat_ids(s)
        print("all_chat_ids ->", len(ids), "шт")
        await s.rollback()  # на прод НИЧЕГО не пишем

    await engine.dispose()
    print("OK — read-only проверка завершена, прод не изменён.")


if __name__ == "__main__":
    asyncio.run(main())
