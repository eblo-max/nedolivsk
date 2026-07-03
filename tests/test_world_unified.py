"""Единый мир: община (город/фракции/летопись) — одна на всех. chat_id больше
НЕ определяет общину (он только маршрут уведомлений). Тесты фиксируют инвариант,
чтобы пер-чат-скоуп не пролез обратно."""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.db import repo  # noqa: E402


def test_player_city_id_always_world():
    # у всех — один мировой город, независимо от домашнего чата
    assert repo.player_city_id(NS(chat_id=None)) == repo.GLOBAL_CITY_ID
    assert repo.player_city_id(NS(chat_id=-1001234567)) == repo.GLOBAL_CITY_ID
    assert repo.player_city_id(NS(chat_id=0)) == repo.GLOBAL_CITY_ID
    assert repo.GLOBAL_CITY_ID == 0


def test_no_per_chat_city_lookups_in_source():
    """Community-город берётся ТОЛЬКО через get_world_city. Прямые
    get_or_create_city(p.chat_id) для общины — регресс к пер-чат-миру."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "bot"
    offenders = []
    for f in root.rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if "get_or_create_city(" in s and "chat_id" in s and "def " not in s:
                offenders.append(f"{f.name}:{i}: {s}")
    assert not offenders, "община должна идти через get_world_city:\n" + "\n".join(offenders)
