"""Доска почёта: рейтинги (ВВП/Слава/Уровень), тренд мест в реальном времени,
короны лидеров и аватарки из Telegram-профиля. Перенесено из bot/webapp.py
дословно (move-only)."""

import asyncio
import hashlib
import hmac
import time

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap
from bot.webapi.core import _auth, get_bot

_RATING_METRICS = ("gdp", "rep", "level")   # ключи метрик доски (по ним же ранжируем)
_RATING_TOP = 50                              # длина каждой доски


def _rating_entries(rows: list) -> tuple[list[dict], int]:
    """Сводка по всем тавернам: id/имя/владелец/уровень/локация + метрики gdp/rep.
    ВВП считается ОДИН раз (как «рп топ» в боте) — дальше сортируем по любой метрике."""
    from bot.game import artel_shop, fame
    from bot.game import buildings as bld
    from bot.game import items as it
    from bot.game import production as prodmod
    entries: list[dict] = []
    for tavern, player in rows:
        gdp = balance.tavern_gdp(
            inventory=player.inventory, gold=player.gold, level=tavern.level,
            income_rate=tavern.income_rate, reputation=tavern.reputation)
        gdp += it.gear_value(getattr(player, "equipment", None))
        gdp += bld.invested_value(tavern)
        gdp += prodmod.products_value(tavern)
        entries.append({
            "id": int(player.id), "name": tavern.name or "Таверна",
            "owner": player.first_name or "Кабатчик", "level": int(tavern.level),
            "loc": worldmap.continent_name(player.region, player.id),
            "gdp": int(gdp), "rep": int(tavern.reputation or 0),
            "cap": int(tavern.capacity or 0), "comfort": int(tavern.comfort or 0),
            "builds": len(tavern.buildings or []),   # для мини-профиля таверны
            "ava": f"{player.id}.{_ava_sig(int(player.id))}",   # подписанная ссылка на аватар
            "atitle": artel_shop.top_title(player),   # артель-титул зодчего (у имени)
            "fame": fame.badge(tavern.reputation),    # 🏆 престиж-ранг славы заведения
        })
    return entries, sum(e["gdp"] for e in entries)


def _rating_leaders(entries: list[dict]) -> dict[int, list[str]]:
    """Короны: id топ-1 по каждой метрике → список его титулов (gdp/rep/level)."""
    crowns: dict[int, list[str]] = {}
    for k in _RATING_METRICS:
        ranked = _ranked(entries, k)
        if ranked:
            crowns.setdefault(ranked[0]["id"], []).append(k)
    return crowns


# ── Тренд мест в реальном времени ──
# Катящиеся снимки рангов: рабочая копия в памяти, персист — в rank_snaps (пишет
# нотифаер раз в минуту). После деплоя гидрируемся из БД → тренд ПЕРЕЖИВАЕТ рестарт.
# Тренд строки = ранг в снимке ~_TREND_WINDOW назад − текущий ранг (живой).
# +N = поднялся на N мест, −N = опустился, 0 = на месте, None = новичок/нет базы.
from collections import deque as _deque   # noqa: E402

_RANK_SNAPS: "_deque[tuple[float, dict[str, dict[int, int]]]]" = _deque(maxlen=60)
_TREND_WINDOW = 600.0   # целевой возраст базлайна (~10 мин «реального времени»)
_SNAP_MIN = 60.0        # снимок не чаще раза в минуту
_TREND_HYDRATED = False  # снимки из БД уже подняты в память (один раз на процесс)
_OVERTAKEN_AT: dict[int, float] = {}   # анти-спам «тебя подвинули» (uid → epoch)


async def _trend_hydrate(session) -> None:
    """Поднять снимки рангов из БД в память (после рестарта). JSONB возвращает
    ключи-строки — приводим player_id обратно к int."""
    global _TREND_HYDRATED
    if _TREND_HYDRATED:
        return
    _TREND_HYDRATED = True                     # и при пустой БД второй раз не ходим
    now = time.time()
    try:
        rows = await repo.rank_snaps_load(session, since_ts=now - 2 * _TREND_WINDOW)
    except Exception:   # noqa: BLE001 — таблица могла ещё не создаться; тренд не критичен
        return
    for ts, data in rows:
        snap = {k: {int(pid): r for pid, r in (v or {}).items()}
                for k, v in (data or {}).items()}
        _RANK_SNAPS.append((ts, snap))


def _ranked(entries: list[dict], metric: str) -> list[dict]:
    """Все таверны по убыванию метрики (тай-брейк — имя)."""
    return sorted(entries, key=lambda e: (-e[metric], e["name"].lower()))


def _trend_baseline(now: float) -> dict[str, dict[int, int]] | None:
    """Снимок-база: самый свежий ИЗ тех, что старше окна; иначе — самый старый."""
    if not _RANK_SNAPS:
        return None
    for ts, snap in reversed(_RANK_SNAPS):
        if now - ts >= _TREND_WINDOW:
            return snap
    return _RANK_SNAPS[0][1]


def _trend_record(now: float, cur_ranks: dict[str, dict[int, int]]) -> None:
    """Запомнить текущие ранги (не чаще _SNAP_MIN); подрезать старьё."""
    if _RANK_SNAPS and now - _RANK_SNAPS[-1][0] < _SNAP_MIN:
        return
    _RANK_SNAPS.append((now, cur_ranks))
    while len(_RANK_SNAPS) > 1 and now - _RANK_SNAPS[0][0] > 2 * _TREND_WINDOW:
        _RANK_SNAPS.popleft()


def _rating_board(ranked: list[dict], uid: int, base: dict[int, int] | None) -> dict:
    """Доска из уже отсортированного списка: место + тренд vs базовый снимок."""
    out = []
    for i, e in enumerate(ranked, 1):
        trend = None
        if base is not None:
            br = base.get(e["id"])
            trend = (br - i) if br is not None else None   # +вверх / −вниз / None=новичок
        out.append({**e, "place": i, "mine": bool(uid) and e["id"] == uid, "trend": trend})
    top = out[:_RATING_TOP]
    me = None
    if uid and not any(r["mine"] for r in top):
        me = next((r for r in out if r["id"] == uid), None)
    return {"rows": top, "me": me}


async def _api_rating(request: web.Request) -> web.Response:
    """Доска почёта: ТРИ честно ранжированные доски (ВВП/Слава/Уровень) + тренд мест
    в реальном времени, в одном ответе. Открыта всем игрокам."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        await _trend_hydrate(s)                 # после деплоя поднять снимки из БД
        rows = await repo.get_map_taverns(s)
    entries, total_gdp = _rating_entries(rows)
    now = time.time()
    base = _trend_baseline(now)
    cur_ranks: dict[str, dict[int, int]] = {}
    boards: dict[str, dict] = {}
    for k in _RATING_METRICS:
        ranked = _ranked(entries, k)
        cur_ranks[k] = {e["id"]: i for i, e in enumerate(ranked, 1)}
        boards[k] = _rating_board(ranked, uid, base.get(k) if base else None)
    _trend_record(now, cur_ranks)
    return web.json_response(
        {"ok": True, "boards": boards, "total_gdp": int(total_gdp),
         "total": len(entries)}, headers={"Cache-Control": "no-store"})


async def snapshot_rating_ranks(session) -> None:
    """Снимок рангов всех таверн для тренда лидерборда. Зовётся периодически из
    нотифаера (раз в минуту), чтобы тренд считался ВСЕГДА, а не только при открытии
    доски. Делит общий _RANK_SNAPS с /api/rating (один процесс/event-loop) и
    персистит снимок в rank_snaps — тренд переживает деплой (коммитит вызывающий)."""
    await _trend_hydrate(session)
    rows = await repo.get_map_taverns(session)
    entries, _total = _rating_entries(rows)
    if not entries:
        return
    now = time.time()
    cur_ranks = {k: {e["id"]: i for i, e in enumerate(_ranked(entries, k), 1)}
                 for k in _RATING_METRICS}
    # «Тебя подвинули»: вылетел из топ-3 по ВВП со времени прошлого снимка →
    # весть в ленту (kind=rating). Анти-спам: не чаще раза в 6ч на игрока.
    prev = _RANK_SNAPS[-1][1] if _RANK_SNAPS else None
    if prev and prev.get("gdp"):
        old_top3 = {pid for pid, r in prev["gdp"].items() if r <= 3}
        new_ranks = cur_ranks["gdp"]
        for pid in old_top3:
            new_r = new_ranks.get(pid)
            if new_r is not None and new_r > 3 and                now - _OVERTAKEN_AT.get(pid, 0.0) > 6 * 3600:
                _OVERTAKEN_AT[pid] = now
                repo.feed_push(session, int(pid),
                               f"🏆 Тебя подвинули с пьедестала — теперь #{new_r}. "
                               "Пора напомнить, чей это город!", kind="rating")

    before = len(_RANK_SNAPS)
    _trend_record(now, cur_ranks)
    if len(_RANK_SNAPS) > before or (_RANK_SNAPS and _RANK_SNAPS[-1][0] == now):
        # снимок реально записан (не отброшен троттлингом) → зеркалим в БД.
        # JSONB сам превратит int-ключи в строки; гидрация приводит обратно.
        await repo.rank_snap_add(session, now, cur_ranks,
                                 prune_before=now - 2 * _TREND_WINDOW)


# Аватарки игроков из Telegram-профиля (для лидерборда). Кэш в памяти: фото меняют
# редко, а getUserProfilePhotos+getFile+download — 3 вызова Bot API на игрока.
# Эндпоинт публичный, поэтому ссылка ПОДПИСАНА (/avatar/<uid>.<sig>): без валидной
# подписи 404 — нельзя перебирать чужие tg_id через нашего бота.
def _ava_sig(uid: int) -> str:
    from bot.config import settings
    key = hashlib.sha256(f"ava:{settings.bot_token}".encode()).digest()
    return hmac.new(key, str(uid).encode(), hashlib.sha256).hexdigest()[:16]


_AVATAR_CACHE: dict[int, tuple[bytes | None, float]] = {}
_AVA_TTL = 12 * 3600        # положительный кэш (есть фото)
_AVA_NEG_TTL = 3600         # негативный кэш (нет фото/приват) — реже дёргаем API
_AVA_MAX = 4000             # потолок записей: эндпоинт публичный, иначе кэш набьют запросами
_AVA_LOCKS: dict[int, asyncio.Lock] = {}   # дедуп: N параллельных <img> одного uid = 1 фетч


def _ava_cached(uid: int, now: float) -> web.Response | None:
    """Ответ из кэша (200/404), если запись свежая; иначе None (нужен фетч)."""
    hit = _AVATAR_CACHE.get(uid)
    if hit is None:
        return None
    data, ts = hit
    if now - ts >= (_AVA_TTL if data else _AVA_NEG_TTL):
        return None
    if not data:
        return web.Response(status=404)
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=43200"})


async def _api_avatar(request: web.Request) -> web.Response:
    """Фото профиля игрока по подписанной ссылке <uid>.<sig>. 404 → фронт рисует инициал."""
    spec = request.match_info.get("uid", "")
    uid_s, _, sig = spec.partition(".")
    try:
        uid = int(uid_s)
    except ValueError:
        return web.Response(status=404)
    if not sig or not hmac.compare_digest(sig, _ava_sig(uid)):
        return web.Response(status=404)
    cached = _ava_cached(uid, time.time())
    if cached is not None:
        return cached
    # Лидерборд рисует десятки <img> разом — без замка каждый промах кэша дал бы
    # свой тройной вызов Bot API. Замок на uid: первый фетчит, остальные ждут кэш.
    lock = _AVA_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        cached = _ava_cached(uid, time.time())   # пока ждали замок — мог наполниться
        if cached is not None:
            return cached
        data: bytes | None = None
        _bot = get_bot()
        if _bot is not None:
            try:
                photos = await _bot.get_user_profile_photos(user_id=uid, limit=1)
                if photos.total_count and photos.photos:
                    size = photos.photos[0][0]    # самый мелкий размер — для кружка хватает
                    f = await _bot.get_file(size.file_id)
                    buf = await _bot.download_file(f.file_path)
                    data = buf.read() if hasattr(buf, "read") else bytes(buf)
            except Exception:   # noqa: BLE001 — нет фото/приват/ошибка → фолбэк на инициалы
                data = None
        _AVATAR_CACHE[uid] = (data, time.time())
    if len(_AVA_LOCKS) > 512:                # редкая уборка; гонка = лишний фетч, не беда
        _AVA_LOCKS.clear()
    if len(_AVATAR_CACHE) > _AVA_MAX:        # выкинуть самые старые (порядок вставки)
        for k in list(_AVATAR_CACHE)[:len(_AVATAR_CACHE) - _AVA_MAX]:
            _AVATAR_CACHE.pop(k, None)
    if not data:
        return web.Response(status=404)
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=43200"})

