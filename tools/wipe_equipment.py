"""Разовая зачистка экипировки у ВСЕХ игроков.

Нужна после тестов с бесплатной кузницей: снимает все надетые вещи и
отменяет незавершённые заказы кузнеца. Золото/ресурсы не трогает —
при тесте крафт был бесплатным, возвращать нечего.

Работает с той базой, что в DATABASE_URL (.env). Чтобы зачистить прод —
подставь его DATABASE_URL в окружение перед запуском.

    python tools/wipe_equipment.py            # покажет, скольких затронет, и спросит
    python tools/wipe_equipment.py --yes      # без вопроса (для CI/прод)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, update

from bot.db.base import engine, session_factory
from bot.db.models import Player

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def wipe(confirm: bool) -> int:
    async with session_factory() as session:
        with_gear = await session.scalar(
            select(func.count())
            .select_from(Player)
            .where(Player.equipment != {})
        )
        with_craft = await session.scalar(
            select(func.count())
            .select_from(Player)
            .where(Player.craft_item.is_not(None))
        )
        print(f"С экипировкой: {with_gear} · с активным заказом кузнеца: {with_craft}")

        if not confirm:
            ans = input("Стереть всё это? Введи 'yes' для подтверждения: ").strip()
            if ans.lower() != "yes":
                print("Отменено. Ничего не тронуто.")
                return 0

        await session.execute(
            update(Player).values(
                equipment={},
                craft_item=None,
                craft_ends_at=None,
                craft_notified=False,
            )
        )
        await session.commit()
        print(f"✅ Готово. Экипировка снята у всех, заказы кузнеца отменены.")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    confirm = "--yes" in sys.argv[1:]
    sys.exit(asyncio.run(wipe(confirm)))
