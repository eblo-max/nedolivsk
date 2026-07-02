"""Сарафанное радио: пороги, кулдауны, троттлинг выпуска."""

import asyncio
import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import rumors  # noqa: E402


def _pl(pid=1, chat=-100500, tavern="Кривая Кружка"):
    return NS(id=pid, chat_id=chat, tavern=NS(name=tavern))


def _reset():
    rumors._pending.clear()
    rumors._last_by_player.clear()
    rumors._last_flush = 0.0


def test_note_threshold_and_cooldown():
    _reset()
    assert not rumors.note("auction", _pl(), 50)          # ниже порога
    assert rumors.note("auction", _pl(), 500)             # прошёл
    assert not rumors.note("auction", _pl(), 500)         # кулдаун игрока 6ч
    assert rumors.note("auction", _pl(pid=2), 500)        # другой игрок — можно
    assert len(rumors._pending) == 2


def test_note_needs_chat_and_tavern():
    _reset()
    assert not rumors.note("night", NS(id=3, chat_id=None, tavern=NS(name="X")), 999)
    assert not rumors.note("night", NS(id=4, chat_id=-1, tavern=None), 999)


def test_flush_throttles():
    _reset()
    rumors.note("trade", _pl(pid=5), 400)
    rumors.note("trade", _pl(pid=6), 400)

    lines: list = []

    class _Repo:
        @staticmethod
        async def add_chronicle(_s, chat_id, text):
            lines.append((chat_id, text))

    out1 = asyncio.run(rumors.flush(None, _Repo))
    out2 = asyncio.run(rumors.flush(None, _Repo))          # сразу второй — молчит
    assert out1 and "Кривая Кружка" in out1
    assert out2 is None
    assert len(lines) == 1 and len(rumors._pending) == 1
    _reset()
