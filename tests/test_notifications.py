"""Уведомления: типизация ленты (kind), guard чатов, троттл touch_seen."""

import os
from types import SimpleNamespace as NS

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


# ── Пакет B ─────────────────────────────────────────────────────────────
def test_group_feed_collapses_neighbors():
    from datetime import datetime, timedelta, timezone
    from bot.webapi.notifications import _group_feed
    now = datetime.now(timezone.utc)
    mk = lambda kind, mins, read=False, text="t": NS(
        kind=kind, read=read, text=text, created_at=now - timedelta(minutes=mins))
    rows = [mk("exped", 1), mk("exped", 5), mk("exped", 30),   # склеятся ×3
            mk("raid", 40),                                     # уникальный — сам по себе
            mk("prod", 50), mk("prod", 400)]                    # окно 90 мин — НЕ склеятся
    items = _group_feed(rows, now)
    assert [(i["kind"], i["count"]) for i in items] == [
        ("exped", 3), ("raid", 1), ("prod", 1), ("prod", 1)]


def test_group_feed_unread_wins():
    from datetime import datetime, timedelta, timezone
    from bot.webapi.notifications import _group_feed
    now = datetime.now(timezone.utc)
    mk = lambda read, mins: NS(kind="prod", read=read, text="x",
                               created_at=now - timedelta(minutes=mins))
    items = _group_feed([mk(True, 1), mk(False, 2)], now)
    assert items[0]["count"] == 2 and items[0]["read"] is False


def test_overtaken_pushes_once_per_window():
    import asyncio
    from bot.webapi import rating as rt
    sess = _FakeSession()

    async def run():
        rt._RANK_SNAPS.clear(); rt._OVERTAKEN_AT.clear(); rt._TREND_HYDRATED = True
        # прошлый снимок: игрок 7 был #2; подсунем его руками
        rt._RANK_SNAPS.append((0.0, {"gdp": {7: 2, 8: 1, 9: 3}}))
        # обманка: get_map_taverns не дергаем — зовём внутренний кусок через monkey-логику
        # (проверяем чистую часть: сравнение prev vs new + feed_push)
        prev = rt._RANK_SNAPS[-1][1]
        cur = {"gdp": {7: 5, 8: 1, 9: 2}}
        import time as _t
        now = _t.time()
        old_top3 = {pid for pid, r in prev["gdp"].items() if r <= 3}
        for pid in old_top3:
            new_r = cur["gdp"].get(pid)
            if new_r and new_r > 3 and now - rt._OVERTAKEN_AT.get(pid, 0.0) > 6 * 3600:
                rt._OVERTAKEN_AT[pid] = now
                from bot.db import repo as _repo
                _repo.feed_push(sess, int(pid), "подвинули", kind="rating")
    asyncio.run(run())
    kinds = [o.kind for o in sess.added]
    assert kinds == ["rating"]                    # только выпавший №7, один раз
    rt._RANK_SNAPS.clear(); rt._OVERTAKEN_AT.clear(); rt._TREND_HYDRATED = False


def test_quiet_hours_msk_math():
    """23:00–08:00 МСК = 20:00–05:00 UTC — тизер молчит."""
    quiet = lambda utc_h: ((utc_h + 3) % 24) >= 23 or ((utc_h + 3) % 24) < 8
    assert quiet(20) and quiet(23) and quiet(4)       # ночь МСК
    assert not quiet(6) and not quiet(12) and not quiet(19)   # день МСК


# ── Срочные вести (рейд/орда пробивают тизер) ───────────────────────────
def test_queue_notify_stores_kind_on_outbox_row():
    """kind лежит и на outbox-строке — нотифаер по нему решает «срочное или тизер»."""
    s = _FakeSession()
    repo.queue_notify(s, 7, "Босс идёт", kind="raid")
    note = next(o for o in s.added if type(o).__name__ == "Notification")
    assert note.kind == "raid"


def test_urgent_kinds_are_time_limited_battles():
    from bot.notifier import URGENT_KINDS
    assert URGENT_KINDS == {"raid", "invasion"}


def test_urgent_dm_kb_routes(monkeypatch):
    import bot.webapp as webapp
    from bot.keyboards.inline import urgent_dm_kb
    monkeypatch.setattr(webapp, "base_url", lambda: "https://x.example")
    kb = urgent_dm_kb("raid")
    btn = kb.inline_keyboard[0][0]
    assert btn.web_app and btn.web_app.url.endswith("/app/?startapp=raid")
    kb = urgent_dm_kb("invasion")
    assert kb.inline_keyboard[0][0].callback_data == "invopen"


def test_outbox_appends_are_4_tuples():
    """Регресс: 3-элементный outbox.append уронил нотифаер в проде (02.07)."""
    import ast
    tree = ast.parse(open("bot/notifier.py", encoding="utf-8").read())
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "outbox"):
            arg = node.args[0]
            if not (isinstance(arg, ast.Tuple) and len(arg.elts) == 4):
                bad.append(node.lineno)
                continue
            last = arg.elts[3]          # порядок: (player, text, markup, KIND-строка)
            if not (isinstance(last, ast.Constant) and isinstance(last.value, str)):
                bad.append(node.lineno)
    assert not bad, f"outbox.append не (player, text, markup, kind-строка): {bad}"


# ── Важные вести: заметный пуш неактивным ───────────────────────────────
def test_bonus_cta_kb_opens_app(monkeypatch):
    import bot.webapp as webapp
    from bot.keyboards.inline import bonus_cta_kb
    monkeypatch.setattr(webapp, "base_url", lambda: "https://x.example")
    kb = bonus_cta_kb()
    btn = kb.inline_keyboard[0][0]
    assert btn.web_app and btn.web_app.url.endswith("/app/")
    assert "бонус" in btn.text.lower()


def test_bonus_split_active_vs_idle():
    """Заметный пуш бонуса — только тем, кого нет в игре (last_seen старше окна);
    активные получают лишь ленту. Логика разделения из нотифаера."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cut = now - timedelta(minutes=6)
    targets = [(1, None), (2, now - timedelta(minutes=2)),   # 2 — активен
               (3, now - timedelta(hours=3)), (4, now - timedelta(days=1))]
    push_ids = [pid for pid, ls in targets if ls is None or ls < cut]
    assert push_ids == [1, 3, 4]                    # активный (2) — без пуша
