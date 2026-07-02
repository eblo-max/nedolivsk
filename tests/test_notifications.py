"""Уведомления: типизация ленты (kind), guard чатов, троттл touch_seen."""

import os

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.db import repo  # noqa: E402


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def test_feed_push_carries_kind_and_truncates():
    s = _FakeSession()
    repo.feed_push(s, 42, "Постройка готова", kind="build" + "x" * 40)
    assert len(s.added) == 1
    n = s.added[0]
    assert n.user_id == 42 and n.kind == ("build" + "x" * 40)[:32]


def test_feed_push_skips_group_echo():
    """Эхо в группу идёт через queue_notify(chat_id<0) — в личную ленту не пишем."""
    s = _FakeSession()
    repo.feed_push(s, -1001234567, "эхо в чат")
    assert s.added == []


def test_queue_notify_mirrors_kind_to_feed():
    s = _FakeSession()
    repo.queue_notify(s, 7, "Лот ушёл", kind="auction")
    kinds = sorted(type(o).__name__ for o in s.added)
    assert kinds == ["NotifFeed", "Notification"]
    feed = next(o for o in s.added if type(o).__name__ == "NotifFeed")
    assert feed.kind == "auction"


def test_touch_seen_throttles(monkeypatch):
    from bot.webapi import core
    calls = []

    class _S:
        async def execute(self, stmt):
            calls.append(1)

    core._SEEN_AT.clear()
    import asyncio
    asyncio.run(core.touch_seen(_S(), 99))
    asyncio.run(core.touch_seen(_S(), 99))     # в окне троттла — не пишет
    assert len(calls) == 1
    core._SEEN_AT[99] = 0.0                     # окно «прошло»
    asyncio.run(core.touch_seen(_S(), 99))
    assert len(calls) == 2
    core._SEEN_AT.clear()
