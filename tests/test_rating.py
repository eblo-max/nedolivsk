"""Юнит-тесты доски почёта: сортировка, места, тренд, короны, подпись аватарок.

Всё — чистые функции webapp (без БД/сети); гидрация тренда — с подменой repo.
"""

import asyncio
import os
import time

os.environ.setdefault("BOT_TOKEN", "test:test")   # webapp тянет config при импорте

from bot import webapp as w  # noqa: E402


def _e(pid, name="T", gdp=0, rep=0, level=1):
    return {"id": pid, "name": name, "owner": "o", "loc": "L",
            "gdp": gdp, "rep": rep, "level": level}


def _snaps_reset():
    w._RANK_SNAPS.clear()


# ── сортировка ──────────────────────────────────────────────────────────

def test_ranked_sorts_desc_with_name_tiebreak():
    entries = [_e(1, "Б", gdp=100), _e(2, "А", gdp=100), _e(3, "В", gdp=200)]
    ranked = w._ranked(entries, "gdp")
    assert [r["id"] for r in ranked] == [3, 2, 1]   # 200, затем 100-е по имени (А < Б)


def test_ranked_independent_per_metric():
    entries = [_e(1, gdp=100, rep=1), _e(2, gdp=50, rep=9)]
    assert w._ranked(entries, "gdp")[0]["id"] == 1
    assert w._ranked(entries, "rep")[0]["id"] == 2


# ── доска: места, mine, «моё место» ниже топа ──────────────────────────

def test_board_places_and_mine():
    ranked = w._ranked([_e(1, gdp=10), _e(2, gdp=30), _e(3, gdp=20)], "gdp")
    board = w._rating_board(ranked, uid=3, base=None)
    assert [(r["id"], r["place"]) for r in board["rows"]] == [(2, 1), (3, 2), (1, 3)]
    assert [r["mine"] for r in board["rows"]] == [False, True, False]
    assert board["me"] is None                      # я в топе — отдельная строка не нужна


def test_board_me_below_top_gets_true_place():
    entries = [_e(i, gdp=1000 - i) for i in range(1, w._RATING_TOP + 6)]
    ranked = w._ranked(entries, "gdp")
    uid = w._RATING_TOP + 3                          # заведомо ниже топ-50
    board = w._rating_board(ranked, uid=uid, base=None)
    assert len(board["rows"]) == w._RATING_TOP
    assert board["me"] is not None and board["me"]["place"] == uid   # настоящее место


# ── тренд ───────────────────────────────────────────────────────────────

def test_trend_vs_baseline_and_newcomer_none():
    ranked = w._ranked([_e(1, gdp=100), _e(2, gdp=200), _e(9, gdp=50)], "gdp")
    base = {1: 1, 2: 2}                              # раньше: 1-й был №1, 2-й — №2; 9 — новичок
    rows = w._rating_board(ranked, uid=0, base=base)["rows"]
    by = {r["id"]: r["trend"] for r in rows}
    assert by[2] == 1 and by[1] == -1                # поменялись местами
    assert by[9] is None                             # новичку стрелку не рисуем


def test_trend_record_throttled_and_baseline_prefers_old():
    _snaps_reset()
    now = time.time()
    w._trend_record(now - 700, {"gdp": {1: 1}})      # старше окна (600с)
    w._trend_record(now - 10, {"gdp": {1: 2}})       # свежий
    w._trend_record(now, {"gdp": {1: 3}})            # < _SNAP_MIN после предыдущего → отброшен
    assert len(w._RANK_SNAPS) == 2
    assert w._trend_baseline(now)["gdp"] == {1: 1}   # база — самый свежий из СТАРШЕ окна
    _snaps_reset()
    w._trend_record(now - 30, {"gdp": {1: 5}})       # только свежие → берём самый старый
    assert w._trend_baseline(now)["gdp"] == {1: 5}
    _snaps_reset()
    assert w._trend_baseline(now) is None            # пусто → тренда нет


def test_trend_hydrate_restores_from_db_with_int_keys(monkeypatch):
    _snaps_reset()
    w._TREND_HYDRATED = False
    ts = time.time() - 650
    async def fake_load(session, since_ts, limit=40):
        return [(ts, {"gdp": {"7": 2}, "rep": {"7": 1}})]   # JSONB отдаёт ключи-строки
    monkeypatch.setattr(w.repo, "rank_snaps_load", fake_load)
    asyncio.run(w._trend_hydrate(None))
    assert w._TREND_HYDRATED
    assert w._RANK_SNAPS[0][1]["gdp"] == {7: 2}      # ключи снова int
    asyncio.run(w._trend_hydrate(None))              # повторно в БД не ходит (флаг)
    assert len(w._RANK_SNAPS) == 1
    _snaps_reset()
    w._TREND_HYDRATED = False


# ── короны ──────────────────────────────────────────────────────────────

def test_leaders_one_per_metric_merged_by_player():
    entries = [_e(1, gdp=100, rep=5, level=3), _e(2, gdp=200, rep=9, level=3),
               _e(3, gdp=50, rep=1, level=7)]
    assert w._rating_leaders(entries) == {2: ["gdp", "rep"], 3: ["level"]}
    assert w._rating_leaders([]) == {}


# ── подпись аватарок ────────────────────────────────────────────────────

def test_ava_sig_deterministic_and_unique():
    a, b = w._ava_sig(123), w._ava_sig(124)
    assert a == w._ava_sig(123) and a != b
    assert len(a) == 16 and all(c in "0123456789abcdef" for c in a)
