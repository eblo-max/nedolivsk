"""Mini App: интерактивная карта мира (Telegram Web App).

Маленький aiohttp-сервер РЯДОМ с ботом (тот же процесс, слушает $PORT — Railway
выдаёт публичный домен). Отдаёт:
  GET /            — health-check
  GET /map         — HTML-страница карты (Leaflet CRS.Simple + кластеры)
  GET /api/taverns — JSON таверн (норм. координаты слота, имя, уровень, регион)
  /assets/...      — статика (world.png, спрайты)

Карта — 2.5D-«диорама» на PixiJS (WebGL): нарисованный world.png — это «земля»,
а каждая таверна — стоячее здание-спрайт (map_tavern_<уровень>.png) с тенью,
глубиной (depth-sort по Y), плавным pan/zoom (тащить, щипок, колесо) и тапом по
зданию → карточка. Лимита на число таверн нет. Pixi тянется с CDN.
"""

import hashlib
import hmac
import json
import logging
import os
import pathlib
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap
from bot.game import invasion as invmod

ASSETS_DIR = worldmap.ASSETS_DIR
# Собранный React-мини-апп (Vite → miniapp/dist; собирается в Docker, отдаётся под /app).
MINIAPP_DIST = pathlib.Path(__file__).resolve().parent.parent / "miniapp" / "dist"
# Пирамида тайлов мира (генерится в Docker из assets/world25.jpg тайлером worldgen/tiler.py).
WORLD_TILES = pathlib.Path(__file__).resolve().parent.parent / "world_tiles"

# initData живёт сутки — отсекаем устаревшие/реплей.
_INITDATA_MAX_AGE = 24 * 3600

_authlog = logging.getLogger("webapp.auth")

_BOT = None   # aiogram-Bot из main (один event-loop) — для рассылки в чаты из эндпоинтов


def _verify_init_data(init_data: str) -> int | None:
    """Проверить Telegram WebApp initData (HMAC-SHA256 по токену бота). Возвращает
    user_id, если подпись верна и свежая, иначе None. Это аутентификация запросов
    с карты (без неё нельзя доверять, кто регистрируется).

    На каждый отказ — лог с причиной (empty/no-hash/expired/bad-hash) и НЕдоверенным
    uid из user (для диагностики «у игрока пустая initData → видит демо-таверну»)."""
    from bot.config import settings
    if not init_data:
        _authlog.warning("auth fail: empty initData")
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        recv = pairs.pop("hash", None)
        try:                                  # untrusted — только для лога
            _uid_dbg = json.loads(pairs.get("user", "{}")).get("id")
        except (ValueError, TypeError):
            _uid_dbg = None
        if not recv:
            _authlog.warning("auth fail: no hash (uid~%s)", _uid_dbg)
            return None
        age = abs(time.time() - int(pairs.get("auth_date", "0")))
        if age > _INITDATA_MAX_AGE:
            _authlog.warning("auth fail: expired %ss (uid~%s)", int(age), _uid_dbg)
            return None
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv):
            _authlog.warning("auth fail: bad hash (uid~%s)", _uid_dbg)
            return None
        user = json.loads(pairs.get("user", "{}"))
        uid = user.get("id")
        if not uid:
            _authlog.warning("auth fail: no user.id")
            return None
        return int(uid)
    except (ValueError, KeyError, TypeError) as e:
        _authlog.warning("auth fail: parse %r", e)
        return None


def _tavern_norm_pos(player) -> tuple[float, float]:
    """Нормированная позиция таверны на карте (слот, иначе по региону)."""
    tav = player.tavern
    if tav is not None and tav.map_slot is not None:
        p = worldmap.slot_norm_pos(tav.map_slot)
        if p:
            return p
    return worldmap.region_point(player.region or "", player.id) or (0.5, 0.5)


REPORT_WINDOW_SEC = 20 * 60   # сколько сводка доступна на карте после боя


def _invasion_report_event(inv, uid: int = 0) -> dict:
    """Событие-СВОДКА для карты после боя: орда (idle) + полная статистика боя по
    каждому (урон/крит/блок/пал) и НАГРАДА. pid наружу не отдаём — только флаг mine.
    Если сервер ещё не зарезолвил (status=battle, но время вышло) — считаем сводку
    ПРЕДСКАЗАНИЕМ (та же детерминированная симуляция) → результат виден мгновенно."""
    res = inv.result or {}
    report = res.get("report")
    won, rounds = res.get("won"), res.get("rounds")
    n, ohl, ohm = res.get("n"), res.get("orc_hp_left"), res.get("orc_hp_max")
    if not report:                       # ещё не зарезолвлено сервером — предсказываем
        parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
        sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv))
        plan = invmod.settle(inv, sim)
        report = invmod.build_report(inv, sim, plan)
        won, rounds, n = sim["won"], sim["rounds"], sim["n"]
        ohl, ohm = sim["orc_hp_left"], sim["orc_hp_max"]
    rows = [{k: v for k, v in r.items() if k != "pid"}
            | {"mine": bool(uid) and int(r.get("pid", 0)) == uid} for r in report]
    return {
        "id": inv.id, "sprite": inv.sprite, "x": invmod.POS[0], "y": invmod.POS[1],
        "name": invmod.NAME, "blurb": "Итог битвы с ордой орков",
        "report": True, "won": bool(won), "status": inv.status,
        "rounds": int(rounds or 0), "n": int(n or 0),
        "orc_hp_left": int(ohl or 0), "orc_hp_max": int(ohm or 1), "rows": rows,
    }


def _invasion_event(inv, uid: int = 0) -> dict:
    """Живой ивент «Орда орков» для карты: тот же таймлайн-формат, что демо, но
    синхронизирован серверным временем (elapsed — секунды с начала сбора) и с
    реальными войсками (записавшиеся таверны). Фронт крутит анимацию по elapsed."""
    now = datetime.now(timezone.utc)

    def _secs(a, b):
        if not a or not b:
            return 0.0
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return max(0.0, (b - a).total_seconds())

    # Та же детерминированная симуляция (сид=id) → реальный исход + ТАЙМЛАЙН
    # (HP орды/броня/баффы по раундам) для честной анимации полоски и баффов.
    parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
    sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv))
    result = inv.status if inv.status in ("won", "lost") else ("won" if sim["won"] else "lost")
    # тайминги: сбор — из меток; марш фикс.; БОЙ — по реальному числу раундов (полоска
    # тает в темпе симуляции и заканчивается, когда бой реально завершился).
    gather_secs = _secs(inv.started_at, inv.gather_until) or invmod.GATHER_MINUTES * 60
    march_secs = invmod.MARCH_SECONDS
    battle_secs = invmod.battle_secs_for(sim["rounds"])
    troops = [{"x": (r or {}).get("tx", 0.5), "y": (r or {}).get("ty", 0.5),
               "role": (r or {}).get("role", "ratnik")}
              for r in (inv.registered or {}).values()]
    return {
        "id": inv.id, "sprite": inv.sprite, "x": invmod.POS[0], "y": invmod.POS[1],
        "name": invmod.NAME, "blurb": "Орда орков идёт на Недоливск — поднимай войско!",
        "gather_secs": round(gather_secs), "march_secs": round(march_secs),
        "battle_secs": round(battle_secs),
        "elapsed": round(invmod.elapsed_secs(inv, now), 1),
        "result": result, "troops": troops, "status": inv.status,
        "n": invmod.registered_count(inv),
        "me_registered": bool(uid) and str(uid) in (inv.registered or {}),
        "my_role": (inv.registered or {}).get(str(uid), {}).get("role") if uid else None,
        # реальная боевая динамика для карты:
        "orc_hp_max": sim["orc_hp_max"], "timeline": sim["timeline"],
        # полоска дружины: запас HP (для боя) + «готовность к победе» (для сбора)
        "army_hp_max": sim["army_hp_max"], "ready": round(invmod.readiness(sim), 3),
    }

# Самостоятельные анимированные ивент-объекты на карте (НЕ связаны с рейдами).
# Каждый: sprite (орк 1..3), норм. позиция x/y (на суше!), имя и описание.
# Список — чтобы легко добавлять новые ивенты. Полная механика — отдельно, позже.
MAP_EVENTS = [
    {"sprite": 1, "x": 0.62, "y": 0.16,
     "name": "Орда орков",
     "blurb": "Дикая орда встала лагерем в северных снегах. Зреет буря."},
]


def base_url() -> str:
    """Публичный https-адрес Mini App (для кнопки web_app). Из WEBAPP_BASE_URL,
    иначе из RAILWAY_PUBLIC_DOMAIN. Пусто → кнопку карты не показываем."""
    from bot.config import settings
    b = (getattr(settings, "webapp_base_url", "") or "").strip()
    if not b:
        dom = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if dom:
            b = f"https://{dom}"
    return b.rstrip("/")


async def _api_taverns(request: web.Request) -> web.Response:
    # uid — telegram-id зрителя (из initDataUnsafe), чтобы подсветить ЕГО таверну.
    # Чужие id наружу НЕ отдаём (приватность) — только флаг mine у своей.
    try:
        uid = int(request.query.get("uid", "0"))
    except ValueError:
        uid = 0
    mill_state = None
    async with session_factory() as s:
        rows = await repo.get_map_taverns(s)
        latest = await repo.latest_invasion(s)
        if uid:                                  # состояние вылазки телеги для зрителя
            from bot.game import mill as millmod
            me = await repo.get_player(s, uid)
            if me is not None:
                mill_state = millmod.state(me)
    now = datetime.now(timezone.utc)
    live = latest if (latest and latest.status in ("gathering", "battle")) else None
    report_inv = None
    # время боя ВЫШЛО (now ≥ resolve_at) → показываем сводку СРАЗУ (предсказанием),
    # не дожидаясь, пока нотифаер переключит статус/зарезолвит (лаг до тика ~60с).
    # Важно: НЕ только при status=='battle' — нотифаер мог ещё не флипнуть gathering→battle.
    if live is not None:
        # реальный конец боя = сбор + марш + раунды×темп (из той же симуляции, что и
        # анимация). НЕ полагаемся на resolve_at: при спавне он = дефолт, а нотифаер
        # уточняет его лишь на тике (лаг ≤60с) — иначе сводка отставала бы от полоски.
        end = None
        if invmod.registered_count(live) > 0 and live.gather_until:
            gu = (live.gather_until if live.gather_until.tzinfo
                  else live.gather_until.replace(tzinfo=timezone.utc))
            parts = [dict(r, pid=int(pid)) for pid, r in (live.registered or {}).items()]
            rounds = invmod.simulate(parts, seed=live.id, escal=invmod.escal_of(live))["rounds"]
            end = gu + timedelta(seconds=invmod.MARCH_SECONDS + invmod.battle_secs_for(rounds))
        elif live.resolve_at:
            end = (live.resolve_at if live.resolve_at.tzinfo
                   else live.resolve_at.replace(tzinfo=timezone.utc))
        if end is not None and now >= end:
            report_inv, live = live, None
    # уже зарезолвлен и недавно — показываем сводку из снимка
    if live is None and report_inv is None and latest and latest.status in ("won", "lost") and latest.resolve_at:
        ra = latest.resolve_at
        if ra.tzinfo is None:
            ra = ra.replace(tzinfo=timezone.utc)
        if (now - ra).total_seconds() < REPORT_WINDOW_SEC:
            report_inv = latest
    out = []
    for tav, pl in rows:
        # Со слотом — фикс. позиция; без слота (зона полна) — детерминированная
        # по региону: на интерактивной карте лимита нет, видны ВСЕ таверны.
        pos = (worldmap.slot_norm_pos(tav.map_slot) if tav.map_slot is not None
               else worldmap.region_point(pl.region or "", pl.id))
        if pos is None:
            continue
        out.append({
            "x": round(pos[0], 4), "y": round(pos[1], 4),
            "name": tav.name or pl.first_name or "Таверна",
            "level": tav.level, "region": pl.region or "",
            "tier": worldmap.sprite_tier(tav.level),   # какой спрайт-здание рисовать
            "mine": bool(uid) and pl.id == uid,
        })
    # Живой ивент (реальный таймлайн) > свежая сводка боя > статичный маркер орды.
    if live is not None:
        events = [_invasion_event(live, uid)]
    elif report_inv is not None:
        events = [_invasion_report_event(report_inv, uid)]
    else:
        events = MAP_EVENTS
    return web.json_response(
        {"taverns": out, "regions": balance.REGIONS, "events": events, "mill": mill_state},
        headers={"Cache-Control": "no-store"})


async def _api_invasion_join(request: web.Request) -> web.Response:
    """Регистрация на ивент ПРЯМО С КАРТЫ (мини-апп). Аутентификация — Telegram
    initData (HMAC по токену бота). Атомарная запись (repo.invasion_register).
    Возвращает {ok, role, dmg, crit, armor, dodge, hp, x, y} или {ok:False, error}."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    from bot.config import settings
    if invmod.TEST_MODE and uid != settings.admin_id:     # тест-режим: только админ
        return web.json_response({"ok": False, "error": "testing"})
    from bot.game import combat
    async with session_factory() as s:
        player = await repo.get_player(s, uid)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        inv = await repo.get_active_invasion(s)
        if inv is None or inv.status != "gathering":
            return web.json_response({"ok": False, "error": "closed"})
        already = invmod.is_registered(inv, player.id)
        rec = invmod.make_record(player, player.tavern, _tavern_norm_pos(player),
                                 combat.player_stats(player))
        if not already:
            ok = await repo.invasion_register(s, inv.id, player.id, rec)
            if ok:
                repo.add_log(s, "player", player.id, "⚔️ поднял войско (с карты)")
                await s.commit()
            else:
                already = True
        # пересчёт готовности после записи — чтобы полоска дружины долилась сразу
        fresh = await repo.get_active_invasion(s) or inv
        parts = [dict(r, pid=int(pid)) for pid, r in (fresh.registered or {}).items()]
        sim = invmod.simulate(parts, seed=fresh.id, escal=invmod.escal_of(fresh))
    out = {"role": rec["role"], "dmg": round(rec["dmg"]), "crit": rec["crit"],
           "armor": rec["armor"], "dodge": rec["dodge"], "hp": rec["hp"],
           "x": rec["tx"], "y": rec["ty"], "already": already,
           "ready": round(invmod.readiness(sim), 3), "n": invmod.registered_count(fresh)}
    out["ok"] = True
    return web.json_response(out, headers={"Cache-Control": "no-store"})


# ── Рейд-босс (мини-апп): перенос боёвки из чата 1:1 ─────────────────────────
# Жизненный цикл (спавн → сбор → битва → уход) крутит НОТИФАЕР — здесь только
# чтение состояния и действия игрока (записаться/бить). Боевую логику НЕ дублируем:
# зовём raid.resolve_hit/settle и handlers.raid._drop_apply — те же, что и в чате.
RAID_REPORT_SEC = 20 * 60   # сколько сводка победы/ухода висит на экране рейда


def _secs_until(dt, now) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((dt - now).total_seconds()))


def _raid_loot_dto(boss_key: str) -> list[dict]:
    """Витрина добычи: что с туши может пасть и с каким шансом (для экрана рейда)."""
    from bot.game import raid as rd, balance as bal
    spec = rd.BOSSES.get(boss_key)
    if spec is None:
        return []
    total = sum(w for _, w, _ in spec.loot) or 1
    out = []
    for tag, w, payload in spec.loot:
        pct = round(100 * w / total, 1)
        if tag == "gear":
            out.append({"icon": "🛡", "label": "Эксклюзивная снаряга", "pct": pct, "gear": True})
        elif tag == "gold":
            lo, hi = payload
            out.append({"icon": "🪙", "label": f"{lo}–{hi} золота", "pct": pct})
        elif tag == "ingot":
            lo, hi = payload
            out.append({"icon": bal.RESOURCE_EMOJI.get("ingot", "📦"),
                        "label": f"Слитки ×{lo}–{hi}", "pct": pct})
        else:  # res:<name>
            res, lo, hi = payload
            out.append({"icon": bal.RESOURCE_EMOJI.get(res, "📦"),
                        "label": f"{bal.RESOURCE_NAMES.get(res, res)} ×{lo}–{hi}", "pct": pct})
    return out


def _raid_roster(boss, uid: int = 0) -> list[dict]:
    """Бойцы: имя/урон/удары, флаг mine (pid наружу не отдаём — приватность)."""
    rows = [{"name": r.get("name", ""), "dmg": int(r.get("dmg", 0)),
             "hits": int(r.get("hits", 0)), "mine": bool(uid) and pid == str(uid)}
            for pid, r in (boss.contributions or {}).items()]
    rows.sort(key=lambda x: (-x["dmg"], x["name"]))
    return rows[:8]


def _raid_dto(boss, uid: int = 0) -> dict | None:
    """Полное состояние живого босса для экрана рейда: фаза сбора (отсчёт/строй/
    добыча) либо битвы (HP/фаза/активные касты/мой кулдаун)."""
    from bot.game import raid as rd
    spec = rd.BOSSES.get(boss.boss_key)
    if spec is None:
        return None
    now = datetime.now(timezone.utc)
    base = {
        "id": boss.id, "key": boss.boss_key, "name": spec.name, "emoji": spec.emoji,
        "sprite": spec.sprite or "", "blurb": spec.blurb, "armor": spec.armor,
        "status": boss.status, "n": rd.registered_count(boss),
        "me_registered": rd.is_registered(boss, uid) if uid else False,
        "roster": _raid_roster(boss, uid),
        "gear_pct": rd.gear_drop_pct(boss.boss_key), "loot": _raid_loot_dto(boss.boss_key),
    }
    if boss.status == "gathering":
        base["gather_left"] = _secs_until(boss.gather_until, now)
        base["preview_hp"] = rd.boss_start_hp(boss)   # масштаб боя под текущую явку
    elif boss.status == "active":
        adds = rd.adds_hp(boss)
        adds_max = max(1, int(boss.max_hp * rd.SUMMON_HP_PCT))
        base.update({
            "hp": max(0, boss.hp), "max_hp": boss.max_hp,
            "hp_pct": round(100 * max(0, boss.hp) / boss.max_hp) if boss.max_hp else 0,
            "phase": rd.phase(boss), "ends_left": _secs_until(boss.ends_at, now),
            "stun_left": rd.stun_left(boss, now), "ward_left": rd.ward_left(boss, now),
            "curse_left": rd.curse_left(boss, now),
            "adds_hp": adds, "adds_pct": round(100 * adds / adds_max) if adds else 0,
        })
        if uid:
            base["my_cd"] = rd.cooldown_left(boss, uid, now)
            base["my_stunned"] = rd.stunned(boss, uid, now)
    return base


def _raid_summary(boss, uid: int = 0) -> dict | None:
    """Компактная сводка для снапшота Таверны: показать кнопку «⚔️ РЕЙД-БОСС»."""
    from bot.game import raid as rd
    spec = rd.BOSSES.get(boss.boss_key)
    if spec is None:
        return None
    now = datetime.now(timezone.utc)
    out = {"id": boss.id, "name": spec.name, "emoji": spec.emoji, "sprite": spec.sprite or "",
           "status": boss.status, "me_registered": rd.is_registered(boss, uid) if uid else False,
           "n": rd.registered_count(boss)}
    if boss.status == "gathering":
        out["left"] = _secs_until(boss.gather_until, now)
    elif boss.status == "active":
        out["hp_pct"] = round(100 * max(0, boss.hp) / boss.max_hp) if boss.max_hp else 0
        out["phase"] = rd.phase(boss)
        out["left"] = _secs_until(boss.ends_at, now)
    return out


def _raid_report_dto(boss, uid: int = 0) -> dict | None:
    """Пост-боевая сводка (победа/уход) для тех, кто не добил сам. Доля золота
    ДЕТЕРМИНИРОВАНА (пул÷бойцы) — её показываем точно; победителя/трофей не трогаем
    (их рандом уже применён и ушёл пушем-уведомлением)."""
    from bot.game import raid as rd
    spec = rd.BOSSES.get(boss.boss_key)
    if spec is None:
        return None
    now = datetime.now(timezone.utc)
    # окно показа: до ends_at + RAID_REPORT_SEC (убитого досрочно ends_at в будущем →
    # видно сразу; ушедшего/добитого под конец — ещё RAID_REPORT_SEC после ends_at)
    if boss.ends_at:
        ea = boss.ends_at if boss.ends_at.tzinfo else boss.ends_at.replace(tzinfo=timezone.utc)
        if (now - ea).total_seconds() > RAID_REPORT_SEC:
            return None
    won = boss.status == "dead"
    my_gold = 0
    if won and uid:
        try:
            my_gold = int(rd.settle(boss)["gold"].get(uid, 0))   # gold-сплит детерминирован
        except Exception:   # noqa: BLE001 — сводка не должна ронять экран
            my_gold = 0
    return {
        "id": boss.id, "key": boss.boss_key, "name": spec.name, "emoji": spec.emoji,
        "sprite": spec.sprite or "", "status": boss.status, "report": True, "won": won,
        "top": _raid_roster(boss, uid), "my_gold": my_gold,
        "i_fought": bool(uid) and int((boss.contributions or {}).get(str(uid), {}).get("dmg", 0)) > 0,
    }


async def _raid_start_if_due(s, boss, now):
    """Сбор вышел → перевести в БОЙ ПРЯМО СЕЙЧАС (не ждать нотифаер ≤60с — из-за
    него босс «появлялся» через 20-30с после 0:00). Под локом + повторная проверка
    (анти-гонка: первый запрос переводит, остальные видят уже active). Чат-анонсы
    догонит нотифаер на своём тике. Возвращает свежий boss (active/expired)."""
    if boss is None or boss.status != "gathering" or not boss.gather_until:
        return boss
    gu = boss.gather_until if boss.gather_until.tzinfo else boss.gather_until.replace(tzinfo=timezone.utc)
    if now < gu:
        return boss
    from bot.game import raid as rd
    from bot import texts as _t
    locked = await repo.get_raid(s, boss.id, lock=True)
    if locked is None or locked.status != "gathering":
        return locked or boss            # другой запрос/нотифаер уже перевёл
    lgu = locked.gather_until if locked.gather_until.tzinfo else locked.gather_until.replace(tzinfo=timezone.utc)
    if now < lgu:
        return locked
    if rd.registered_count(locked) > 0:
        locked.max_hp = locked.hp = rd.boss_start_hp(locked)
        locked.status = "active"
        locked.ends_at = rd.fight_until(now)
        for pid in list((locked.contributions or {}).keys()):
            repo.queue_notify(s, int(pid), _t.raid_fight_ping())
    else:
        locked.status = "expired"        # никто не пришёл — ушёл
    await s.commit()
    return locked


async def _api_raid(request: web.Request) -> web.Response:
    """Состояние рейд-босса для мини-аппа: живой босс либо свежая сводка боя."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        boss = await repo.get_active_raid(s)
        boss = await _raid_start_if_due(s, boss, now)    # сбор вышел → бой/уход сразу
        if boss is not None and boss.status in ("gathering", "active"):
            dto = _raid_dto(boss, uid)
        elif boss is not None and boss.status in ("dead", "expired"):
            dto = _raid_report_dto(boss, uid)
        else:
            latest = await repo.latest_raid(s)
            dto = (_raid_report_dto(latest, uid)
                   if latest and latest.status in ("dead", "expired") else None)
    return web.json_response({"ok": True, "raid": dto, "admin": _is_admin(uid),
                              "bosses": _raid_boss_list()},
                             headers={"Cache-Control": "no-store"})


def _raid_boss_list() -> list[dict]:
    """Список боссов для админ-призыва (key/имя/эмодзи/спрайт)."""
    from bot.game import raid as rd
    return [{"key": k, "name": b.name, "emoji": b.emoji, "sprite": b.sprite or ""}
            for k, b in rd.BOSSES.items()]


async def _api_raid_join(request: web.Request) -> web.Response:
    """Записаться в рейд (фаза сбора). Калька cb_raid_join: лочим босса, register,
    лог, коммит. Возвращает свежее состояние."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import raid as rd
    async with session_factory() as s:
        player = await repo.get_player(s, uid)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        boss = await repo.get_active_raid(s, lock=True)
        if boss is None or boss.status != "gathering":
            return web.json_response({"ok": False, "error": "closed"})
        if not rd.register(boss, player):
            return web.json_response({"ok": True, "already": True, "raid": _raid_dto(boss, uid)},
                                     headers={"Cache-Control": "no-store"})
        repo.add_log(s, "player", player.id, "⚔️ записался в рейд (мини-апп)")
        await s.commit()
        dto = _raid_dto(boss, uid)
    return web.json_response({"ok": True, "raid": dto}, headers={"Cache-Control": "no-store"})


async def _api_raid_hit(request: web.Request) -> web.Response:
    """Удар по боссу (фаза битвы). Калька cb_raid_hit 1:1: порядок локов босс→игрок,
    проверки записи/кулдауна/оглушения, raid.resolve_hit, при смерти — settle +
    раздача золота + _drop_apply победителю + пуши, коммит ДО любой косметики."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import raid as rd, economy
    from bot.handlers.raid import _drop_apply
    from bot import texts
    async with session_factory() as s:
        boss = await repo.get_active_raid(s, lock=True)
        if boss is None or boss.status == "dead":
            return web.json_response({"ok": False, "error": "gone"})
        if boss.status == "gathering":
            return web.json_response({"ok": False, "error": "not_started"})
        if boss.status != "active":
            return web.json_response({"ok": False, "error": "gone"})
        player = await repo.get_player(s, uid, for_update=True)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not rd.is_registered(boss, player.id):
            return web.json_response({"ok": False, "error": "not_registered"})

        now = datetime.now(timezone.utc)
        left = rd.cooldown_left(boss, player.id, now)
        if left > 0:                                  # рано бить — мягкий ответ (не ошибка)
            return web.json_response(
                {"ok": True, "hit": False, "wait": left,
                 "stunned": rd.stunned(boss, player.id, now), "raid": _raid_dto(boss, uid)},
                headers={"Cache-Control": "no-store"})

        res = rd.resolve_hit(boss, player, now)        # урон + проклятье/щит/толща/миньоны
        repo.add_log(s, "player", player.id, f"⚔️ рейд: −{res['dmg']} HP боссу (мини-апп)")
        second_wind = rd.maybe_second_wind(boss, now)  # хил+рык на 30% HP (один раз)

        if not rd.is_dead(boss):
            push = texts.raid_cast_push(boss, res.get("casts", []))   # «громкие» касты — бойцам
            if push:
                for pid in (boss.contributions or {}):
                    if int(pid) != player.id:
                        repo.queue_notify(s, int(pid), push)
            await s.commit()                            # урон в БД ДО ответа
            toast = ("🐲 ВТОРОЕ ДЫХАНИЕ! Босс воспрял и взревел — все оглушены!"
                     if second_wind else texts.raid_hit_toast(res, boss.hp, boss.max_hp))
            return web.json_response(
                {"ok": True, "hit": True, "toast": toast, "second_wind": second_wind,
                 "crit": bool(res.get("crit")), "casts": res.get("casts", []),
                 "dmg": int(res.get("dmg", 0)), "adds_dmg": int(res.get("adds_dmg", 0)),
                 "adds_hit": bool(res.get("adds_dmg")), "raid": _raid_dto(boss, uid)},
                headers={"Cache-Control": "no-store"})

        # ── Босс повержен: раздача (как в чате) ──
        boss.status = "dead"
        plan = rd.settle(boss)
        for pid in sorted(plan["gold"]):                # единый порядок локов (по возрастанию id)
            pp = await repo.get_player(s, pid, for_update=True)
            if pp is not None:
                pp.gold += plan["gold"][pid]
                economy.record(pp, "raid", int(plan["gold"][pid]))
                repo.queue_notify(s, pid,
                                  f"⚔️ Босс повержен! Твоя доля добычи: +{plan['gold'][pid]} 🪙")
        drop_line, winner_name = "", None
        if plan["winner"] is not None:
            winner = await repo.get_player(s, plan["winner"], for_update=True)
            if winner is not None:
                winner_name = winner.first_name or str(winner.id)
                got = _drop_apply(winner, plan["drop"])
                if got:
                    rarity = rd.RARITY.get((plan["drop"] or {}).get("rarity"), "")
                    drop_line = f"{rarity} — {got}" if rarity else got
                    repo.queue_notify(s, winner.id, f"🎁 С босса тебе выпал {rarity} трофей: {got}")
        top_full = sorted(((pid, r.get("name", pid), int(r.get("dmg", 0)))
                           for pid, r in (boss.contributions or {}).items()
                           if r.get("dmg", 0) > 0), key=lambda x: -x[2])
        # Флаг + данные победы нотифаеру: правь чатовые анонсы на экран «ПОВЕРЖЕН»
        # (килл случился в мини-аппе, не в чате — чат сам не узнает).
        boss.state = dict(boss.state or {}, mini_kill=True,
                          win_name=winner_name or "", win_drop=drop_line or "")
        await s.commit()                                # награды зафиксированы
        rd.set_active(None)                             # убрать кнопку «Рейд-босс» из меню
        spec = rd.BOSSES[boss.boss_key]
        victory = {
            "name": spec.name, "emoji": spec.emoji, "sprite": spec.sprite or "",
            "top": [{"name": n, "dmg": d, "mine": pid == str(player.id)}
                    for pid, n, d in top_full[:8]],
            "my_gold": int(plan["gold"].get(player.id, 0)),
            "winner": winner_name, "drop": drop_line, "i_killed": True,
        }
    return web.json_response({"ok": True, "hit": True, "dead": True, "victory": victory},
                             headers={"Cache-Control": "no-store"})


async def _api_raid_seed(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): призвать демона и сразу запустить битву (записать админа,
    выставить HP), чтобы вживую погонять экран рейда, не дожидаясь сбора/нотифаера."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from bot.game import raid as rd
    key = (body.get("key") or "demon_slime")
    if key not in rd.BOSSES:
        return web.json_response({"ok": False, "error": "no_boss"})
    async with session_factory() as s:
        player = await repo.get_player(s, uid, for_update=True)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        boss = await repo.get_active_raid(s, lock=True)
        if boss is None:                                # призвать нового
            boss = repo.create_raid(s, key, rd.gather_until())
            await s.flush()
        rd.register(boss, player)                       # вписать админа
        if boss.status == "gathering":                  # сразу в бой
            boss.max_hp = boss.hp = rd.boss_start_hp(boss)
            boss.status = "active"
            boss.ends_at = rd.fight_until()
        rd.set_active(boss.id)
        repo.add_log(s, "player", player.id, "🧪 тест: призван рейд-босс (мини-апп)")
        await s.commit()
        dto = _raid_dto(boss, uid)
    return web.json_response({"ok": True, "raid": dto, "admin": True},
                             headers={"Cache-Control": "no-store"})


async def _api_raid_summon(request: web.Request) -> web.Response:
    """НАСТОЯЩИЙ призыв рейд-босса из мини-аппа (только админ) — как чат-админка:
    фаза СБОРА 20 мин, анонс во ВСЕ чаты (через бота), пуш в ЛС активным игрокам
    (через очередь — доставит нотифаер). Не как seed: тут реальный сбор и рассылка."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from sqlalchemy import select as _select
    from bot.db.models import Player as _Player
    from bot.game import raid as rd
    from bot import texts as _t
    from bot.handlers.raid import send_raid_announce
    from bot.keyboards.inline import raid_gather_kb
    from bot.sender import deliver
    key = (body.get("key") or "demon_slime")
    if key not in rd.BOSSES:
        return web.json_response({"ok": False, "error": "no_boss"})
    async with session_factory() as s:
        if await repo.get_active_raid(s) is not None:
            return web.json_response({"ok": False, "error": "busy"})   # уже есть активный
        boss = repo.create_raid(s, key, rd.gather_until())
        await s.flush()                                   # нужен boss.id для кнопок
        repo.add_log(s, "player", uid, f"⚔️ призвал рейд-босса {key} (мини-апп)")
        # 1) анонс во все чаты (видео/текст) — если бот доступен
        text = _t.raid_gather_screen(boss)
        msgs: dict[str, int] = {}
        if _BOT is not None:
            for cid in await repo.all_chat_ids(s):
                sent = await deliver(lambda c=cid: send_raid_announce(
                    _BOT, c, boss, text, raid_gather_kb(boss.id)), what=f"raid→{cid}")
                if sent is not None:
                    msgs[str(cid)] = sent.message_id
            boss.messages = msgs
        # 2) пуш в ЛС активным за 7 дней (очередь — доставит нотифаер)
        cut = datetime.now(timezone.utc) - timedelta(days=7)
        pids = (await s.execute(
            _select(_Player.id).where(_Player.last_seen_at >= cut))).scalars().all()
        for pid in pids:
            repo.queue_notify(s, pid, _t.raid_push_dm(boss))
        rd.set_active(boss.id)                             # кнопка «Рейд-босс» сразу
        await s.commit()
        dto = _raid_dto(boss, uid)
    return web.json_response(
        {"ok": True, "raid": dto, "admin": True, "chats": len(msgs), "pushed": len(pids)},
        headers={"Cache-Control": "no-store"})


async def _api_mill_run(request: web.Request) -> web.Response:
    """Снарядить телегу за зерном (вылазка к мельнице). Auth — Telegram initData.
    Фиксируем отправку + зарезервированный улов; кулдаун с момента отправки."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    import random as _random
    from bot.game import mill as millmod
    async with session_factory() as s:
        player = await repo.get_player(s, uid, for_update=True)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not millmod.send(player, _random):
            return web.json_response({"ok": False, "error": "busy", "mill": millmod.state(player)})
        repo.add_log(s, "player", player.id, "🛒 снарядил телегу за зерном")
        await s.commit()
        st = millmod.state(player)
    return web.json_response({"ok": True, "mill": st}, headers={"Cache-Control": "no-store"})


async def _api_mill_collect(request: web.Request) -> web.Response:
    """Забрать привезённое зерно (если телега уже вернулась)."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    from bot.game import mill as millmod, inventory
    async with session_factory() as s:
        player = await repo.get_player(s, uid, for_update=True)
        if player is None:
            return web.json_response({"ok": False, "error": "no_tavern"})
        base = millmod.base_grain(player)
        grain = millmod.collect(player)
        if grain <= 0:
            return web.json_response({"ok": False, "error": "nothing", "mill": millmod.state(player)})
        inventory.add(player, "grain", grain)
        repo.add_log(s, "player", player.id, f"🌾 телега привезла зерно +{grain}")
        await s.commit()
        note = "rich" if grain >= base * 1.3 else ("mishap" if grain <= base * 0.75 else "")
        st = millmod.state(player)
    return web.json_response({"ok": True, "grain": grain, "note": note, "mill": st},
                             headers={"Cache-Control": "no-store"})


async def _auth(request: web.Request):
    """Разобрать тело + проверить initData. -> (uid, body) | (None, Response-ошибка)."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return None, web.json_response({"ok": False, "error": "auth"}, status=401)
    return uid, body


# NPC → аватар (public/npc/N.png). Набор из 20 портретов раскидан по сословиям,
# женщины/иконичные — отдельно; выбор внутри сословия детерминирован по id.
_AV_BY_ESTATE = {
    "nobles": [4, 8, 19, 1], "clergy": [3, 14, 7], "merchants": [19, 5, 18, 20],
    "guild": [5, 12, 18, 20, 9], "watch": [1, 6, 13, 4], "thieves": [16, 11, 15, 2],
    "peasants": [7, 12, 17, 9], "vagrants": [16, 17, 2, 15], "oddballs": [11, 14, 2, 6],
}
_AV_FIXED = {
    "countess": 10, "dowager": 10, "nun_smirenna": 10, "paraska": 10, "milkmaid": 10,
    "herbalist_zel": 10, "vedma": 11, "fortunet_rask": 11,
    "magnat": 19, "duke_pompad": 19, "heir_prozhig": 8, "baron_darm": 8,
}


def _npc_avatar(npc_id: str | None, estate: str | None) -> int | None:
    if not npc_id:
        return None
    if npc_id in _AV_FIXED:
        return _AV_FIXED[npc_id]
    pool = _AV_BY_ESTATE.get(estate or "")
    if not pool:
        return None
    return pool[sum(ord(c) for c in npc_id) % len(pool)]


def _story_state(p, city=None) -> dict | None:
    """Висящий визитёр-сторилет для мини-аппа: NPC (эмодзи/имя/характер), завязка и
    ДОСТУПНЫЕ выборы (индексы — по полному списку choices, как ждёт story_engine.resolve)."""
    from bot.game import story_engine as se, npc as npcmod
    from bot.game.story_defs import Ctx
    s = se.pending_storylet(p)
    if s is None:
        return None
    ctx = Ctx(player=p, city=city)
    cz = npcmod.CATALOG.get(s.npc) if s.npc else None
    npcd = ({"emoji": cz.emoji, "name": cz.name, "blurb": cz.blurb, "traits": list(cz.traits),
             "avatar": _npc_avatar(s.npc, cz.estate)}
            if cz else ({"emoji": "🚪", "name": s.npc, "blurb": "", "traits": [], "avatar": None}
                        if s.npc else None))
    choices = [{"index": i, "label": c.label}
               for i, c in enumerate(s.choices)
               if all(pr.check(ctx) for pr in c.requires)]
    return {"id": s.id, "title": s.title, "text": s.text, "npc": npcd, "choices": choices}


def _world_event_state() -> dict | None:
    """Активное мировое событие (погода/экономика) для баннера на Таверне: имя, завязка,
    человекочитаемые эффекты и модный товар (если спрос-событие)."""
    from bot.game import worldevent as we, balance as bal, production as prod
    e = we.active()
    if e is None:
        return None
    good = we.fashion_good()
    gname = None
    if good:
        g = prod.GOODS.get(good)
        gname = g.name if g else {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}.get(good, good)
    effs: list[dict] = []
    def chan(m, label):                       # обычный канал: >1 — выгода
        if m != 1.0:
            effs.append({"text": f"{label} {'+' if m > 1 else '−'}{round(abs(m - 1) * 100)}%", "good": m > 1})
    def spd(m, label):                        # скорость: <1 — быстрее (выгода)
        if m != 1.0:
            effs.append({"text": f"{label} {'быстрее' if m < 1 else 'медленнее'} на {round(abs(m - 1) * 100)}%", "good": m < 1})
    chan(e.income, "касса"); chan(e.harvest, "добыча"); chan(e.sale, "сбыт")
    spd(e.exp_speed, "бригады"); spd(e.prod_speed, "варка")
    if good and gname:
        effs.append({"text": f"{gname} ×{e.good_price:g}", "good": e.good_price > 1})
    return {"id": e.id, "emoji": e.emoji, "name": e.name, "blurb": e.blurb,
            "good": good, "good_name": gname, "effects": effs}


def _city_state(city) -> dict | None:
    """Город сегодня: настроение, текущая ситуация и расклад сил фракций."""
    if city is None:
        return None
    from bot.game import city as citymod, factions
    from bot import texts
    sit = citymod.current(city)
    fp = {f: v for f, v in (city.faction_power or {}).items() if v}
    mv = citymod.mood_value(city)
    return {
        "mood": int(mv), "mood_label": texts._mood_label(mv),
        "situation": ({"emoji": sit.emoji, "label": sit.label} if sit else None),
        "factions": [{"id": f, "name": factions.name(f), "power": int(v)}
                     for f, v in sorted(fp.items(), key=lambda x: -x[1])],
    }


def _tavern_state(p, t) -> dict:
    """Состояние Таверны для мини-аппа — собрано из ТЕХ ЖЕ функций, что и текстовый
    экран бота (texts/logic/balance), но структурировано в JSON. Чистое чтение."""
    from bot import texts
    from bot.game import balance as bal, buff as buffmod, items, logic
    from bot.game import city as citymod, production as prod, season as seasonmod

    chat_id = getattr(p, "chat_id", None)
    eq = p.equipment or {}
    cs = items.combat_stats(eq)
    maxed = t.level >= bal.MAX_LEVEL
    pct = texts._upgrade_pct(p, t)

    from bot.game import newbie as newbiemod, story_state as ss

    now: list[dict] = []
    if ss.get_retail(p):                       # гости ждут заказ — выкупят товар из погреба
        now.append({"icon": "🍺", "text": "Гости ждут заказ", "sub": "выкупят товар из погреба",
                    "badge": "ready", "action": "retail"})
    act = buffmod.active(p)
    if act is not None:
        now.append({"icon": act.emoji, "text": f"Баф «{act.name}»",
                    "sub": f"ещё {buffmod.minutes_left(p)} мин"})
    elif buffmod.offer(p) is not None:
        now.append({"icon": "🎁", "text": "Бонус дня готов", "sub": "забери и активируй",
                    "badge": "ready", "action": "bonus"})
    if newbiemod.claimable(p, t):              # грамота новосёла — награда ждёт
        now.append({"icon": "📜", "text": "Грамота новосёла", "sub": "награда ждёт",
                    "badge": "ready", "action": "newbie"})
    c = logic.expedition_counts(p, t)
    if c.ready and c.out:
        now.append({"icon": "⛏", "text": f"Бригады: {c.ready} готовы, {c.out} в пути",
                    "sub": f"возврат ~{c.next_minutes} мин · забери готовых", "badge": "ready", "action": "expedition"})
    elif c.ready:
        now.append({"icon": "⛏", "text": f"Бригады вернулись ({c.ready})", "sub": "забирай добычу",
                    "badge": "ready", "action": "expedition"})
    elif c.out:
        now.append({"icon": "⛏", "text": f"Бригады в пути: {c.out}/{c.total}",
                    "sub": f"возврат ~{c.next_minutes} мин · отправь ещё", "action": "expedition"})
    else:
        now.append({"icon": "⛏", "text": "Бригады свободны", "sub": "отправь за добром",
                    "action": "expedition"})
    pa, pr = texts._producer_counts(t)
    if pr:
        now.append({"icon": "🏭", "text": f"Пристройки: {pr} готовы", "sub": "забери в разделе", "badge": "ready"})
    elif pa:
        now.append({"icon": "🏭", "text": f"Пристройки: {pa} в работе"})
    bl = texts._build_line(p)
    if bl:
        now.append({"icon": "🏗", "text": bl.replace("🏗 ", "", 1)})
    # перестройку не дублируем в «Сейчас» — она отдельной карточкой ниже

    story = _story_state(p)                       # внезапный визитёр-горожанин (story-движок)
    if story:
        _np = story.get("npc") or {}
        now.insert(0, {"icon": _np.get("emoji", "🚪"), "text": f"{_np.get('name', 'Гость')} у стойки",
                       "sub": "ждёт твоего слова", "badge": "ready", "action": "story"})

    inv = p.inventory or {}
    storage = [{"key": r, "name": bal.RESOURCE_NAMES.get(r, r), "amount": int(inv.get(r, 0))}
               for r in bal.RESOURCES if int(inv.get(r, 0)) > 0]
    cellar = [{"key": k, "name": prod.GOODS[k].name, "qty": int(q)}
              for k, q in (t.products or {}).items() if q and k in prod.GOODS]

    return {
        "ok": True, "name": t.name, "level": int(t.level),
        "region": bal.REGIONS.get(p.region, p.region or ""),
        "flavor": texts._flavor_line(p, t, chat_id, seasonmod, citymod),
        "gold": int(p.gold), "income_rate": int(t.income_rate),
        "income_ready": int(texts._pending_income(t)), "reputation": int(t.reputation or 0),
        "capacity": int(t.capacity), "comfort": int(t.comfort),
        "luck_pct": int(bal.lucky_chance(cs["luck"] + buffmod.luck_bonus(p))),
        "gear_worn": len(eq), "gear_slots": len(items.SLOTS),
        "now": now, "storage": storage, "cellar": cellar,
        "world": texts._world_lines(chat_id, seasonmod, citymod),
        "next_upgrade": (None if maxed else bal.upgrade_cost(t.level)),
        "upgrade_pct": pct, "maxed": maxed, "story": story,
    }


def _trade_dto(offer) -> dict | None:
    """Предложение заезжего купца для мини-аппа: товар, портрет/имя купца, реплика,
    справедливая цена и ценовые тиры (+ контр-цена, если идёт торг)."""
    if not offer:
        return None
    from bot.game import production as prod
    g = prod.GOODS.get(offer.get("good"))
    pool = _AV_BY_ESTATE.get(offer.get("estate") or "")
    avatar = pool[sum(ord(c) for c in offer.get("name", "")) % len(pool)] if pool else None
    return {
        "good": offer.get("good"), "name": g.name if g else offer.get("good"),
        "emoji": g.emoji if g else "📦", "qty": offer.get("qty"),
        "merchant": offer.get("name"), "memoji": offer.get("emoji"), "avatar": avatar,
        "intro": offer.get("intro"), "fv": offer.get("fv"),
        "prices": offer.get("prices"), "counter": offer.get("counter"),
    }


async def _api_state(request: web.Request) -> web.Response:
    """Снапшот Таверны. При открытии — шанс на внезапного визитёра (story-движок),
    как в текстовом боте при заходе в таверну."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from datetime import datetime, timezone
    from bot.game import story_engine as se, buff as buffmod
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        now = datetime.now(timezone.utc)
        before = (p.bonus_kind, p.buff_kind, p.buff_until)
        buffmod.refresh(p, now)                      # прокрутить ежедневный бонус (как бот перед таверной)
        city = await repo.get_or_create_city(s, p.chat_id, lock=True) if p.chat_id else None
        spawned = se.maybe_spawn(p, city, now)       # кулдаун+шанс → pending
        if spawned is not None:
            repo.add_log(s, "player", p.id, "🚪 у стойки объявился гость")
        if spawned is not None or (p.bonus_kind, p.buff_kind, p.buff_until) != before:
            await s.commit()                         # persist только при реальном изменении
        out = _tavern_state(p, p.tavern)
        out["story"] = _story_state(p, city)         # с городом — корректная доступность выборов
        out["world_event"] = _world_event_state()    # баннер активного мирового события
        out["city"] = _city_state(city)              # настроение + фракции + ситуация
        from bot.game import story_state as _ss
        out["trade"] = _trade_dto(_ss.get_trade(p))  # незавершённый торг с купцом (если висит)
        boss = await repo.get_active_raid(s)
        out["raid"] = _raid_summary(boss, uid) if boss else None  # кнопка «⚔️ РЕЙД-БОСС»
        out["admin"] = _is_admin(uid)                # админ-кнопка «Призвать босса» (если босса нет)
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _chron_ago(ts, now) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        from datetime import timezone as _tz
        ts = ts.replace(tzinfo=_tz.utc)
    d = (now - ts).total_seconds()
    if d < 3600:
        return f"{max(1, int(d // 60))} мин назад"
    if d < 86400:
        return f"{int(d // 3600)} ч назад"
    days = int(d // 86400)
    return "вчера" if days == 1 else f"{days} дн назад"


_FAC_EMOJI = {"watch": "👮", "thieves": "🥷", "merchants": "💰", "crown": "👑", "church": "⛪"}
_FAC_ORDER = ["watch", "thieves", "merchants", "crown", "church"]


def _rep_rank(v: int, npc: bool = False):
    """Ранг по репутации (−100..100): (метка, тон pos/neu/neg)."""
    from bot.game import balance as bal
    if v >= bal.REL_FRIEND:
        return ("Друг" if npc else "Свой", "pos")
    if v >= 15:
        return ("Приятель" if npc else "В фаворе", "pos")
    if v > -15:
        return ("Знакомый" if npc else "Нейтралитет", "neu")
    if v > bal.REL_FOE:
        return ("Недолюбливает" if npc else "На заметке", "neg")
    return ("Враг", "neg")


async def _api_reputation(request: web.Request) -> web.Response:
    """Репутация игрока: расклад у 5 фракций + отношения с конкретными горожанами."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import story_state as ss, factions, npc as npcmod, balance as bal
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None:
            return web.json_response({"ok": False, "error": "no_tavern"})
        fac = (p.story or {}).get("faction", {})
        facs = []
        for fid in _FAC_ORDER:
            v = int(fac.get(fid, 0))
            label, tone = _rep_rank(v)
            facs.append({"id": fid, "name": factions.name(fid), "emoji": _FAC_EMOJI.get(fid, "•"),
                         "value": v, "rank": label, "tone": tone,
                         "member": fid == "thieves" and ss.has_flag(p, "guild_member")})
        rel = (p.story or {}).get("npc_rel", {})
        npcs = []
        for nid, v in sorted(rel.items(), key=lambda kv: -abs(int(kv[1]))):
            v = int(v)
            if v == 0:
                continue
            cz = npcmod.CATALOG.get(nid)
            label, tone = _rep_rank(v, npc=True)
            npcs.append({"id": nid, "name": cz.name if cz else nid, "emoji": cz.emoji if cz else "🙂",
                         "blurb": cz.blurb if cz else "", "avatar": _npc_avatar(nid, cz.estate if cz else None),
                         "value": v, "rank": label, "tone": tone})
    return web.json_response({"ok": True, "factions": facs, "npcs": npcs,
                              "min": bal.FACTION_MIN, "max": bal.FACTION_MAX},
                             headers={"Cache-Control": "no-store"})


def _torg_open(uid: int) -> bool:
    """Открыт ли Торг этому игроку: всем (флаг) либо только админу (закрытый запуск)."""
    from bot.game import balance as bal
    from bot.config import settings
    return bool(bal.TORG_OPEN) or uid == settings.admin_id


def _shop_items(p) -> list:
    """Ассортимент скупщика для игрока: цена, дневной остаток, сколько по карману, запас."""
    from bot.game import balance as bal, shop
    inv = p.inventory or {}
    out = []
    for r in shop.sellable():
        out.append({
            "key": r, "name": bal.RESOURCE_NAMES.get(r, r), "emoji": bal.RESOURCE_EMOJI.get(r, "📦"),
            "price": shop.price(r), "room": shop.buy_room(p, r), "limit": bal.SHOP_DAILY_LIMIT,
            "max": shop.max_affordable(p, r), "have": int(inv.get(r, 0)),
        })
    return out


async def _api_torg(request: web.Request) -> web.Response:
    """Вкладка «Торг». Закрыта для всех (open=false) — кроме админа/флага. Открытому —
    скупщик (цены/лимиты/золото). Аукцион и биржа — пока «скоро»."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _torg_open(uid):
            return web.json_response({"ok": True, "open": False}, headers={"Cache-Control": "no-store"})
        out = {"ok": True, "open": True, "gold": p.gold, "limit": bal.SHOP_DAILY_LIMIT,
               "shop": _shop_items(p)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_torg_buy(request: web.Request) -> web.Response:
    """Купить сырьё у скупщика. Серверный гейт + клампы (золото/дневной лимит)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal, economy, inventory, shop
    res = str(body.get("res") or "")
    try:
        want = int(body.get("qty") or 0)
    except (TypeError, ValueError):
        want = 0
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _torg_open(uid):
            return web.json_response({"ok": False, "error": "closed"})
        if res not in shop.sellable():
            return web.json_response({"ok": False, "error": "bad_res"})
        qty = max(0, min(want, shop.max_affordable(p, res)))
        if qty <= 0:
            return web.json_response({"ok": False, "error": "cant"})
        cost = qty * shop.price(res)
        p.gold -= cost
        economy.record(p, "shop", -cost)
        inventory.add(p, res, qty)
        shop.record_buy(p, res, qty)
        repo.add_log(s, "player", p.id,
                     f"🛒 купил в лавке {qty}×{bal.RESOURCE_NAMES.get(res, res)} (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "limit": bal.SHOP_DAILY_LIMIT,
               "shop": _shop_items(p), "bought": {"res": res, "qty": qty, "cost": cost}}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _auction_open(uid: int) -> bool:
    from bot.game import balance as bal
    from bot.config import settings
    return bool(bal.AUCTION_OPEN) or uid == settings.admin_id


def _is_admin(uid: int) -> bool:
    from bot.config import settings
    return uid == settings.admin_id


def _auc_npc(nid):
    from bot.game import npc as npcmod
    if not nid:
        return None
    cz = npcmod.CATALOG.get(nid)
    return {"name": cz.name if cz else nid, "emoji": cz.emoji if cz else "🙂",
            "avatar": _npc_avatar(nid, cz.estate if cz else None)}


def _auction_state(p, world) -> dict:
    """Состояние аукциона: живой лот (товар/таймер/ставки/история) либо форма
    выставления (товары погреба со справедливой ценой, объёмы, тиры цены)."""
    from bot.game import auction as auc, balance as bal, production as prod
    t = p.tavern
    lot = auc.active(t)
    if lot:
        g = prod.GOODS.get(lot["good"])
        hist = [{"unit": h["unit"], **(_auc_npc(h["npc"]) or {})} for h in reversed(lot.get("history", []))]
        return {"active": True, "good": lot["good"], "name": g.name if g else lot["good"],
                "emoji": g.emoji if g else "📦", "qty": lot["qty"], "reserve": lot["unit_min"],
                "top_bid": lot.get("top_bid"), "bidder": _auc_npc(lot.get("top_bidder")),
                "bids": lot.get("bids", 0), "ends_at": lot["ends_at"],
                "mins_left": auc.time_left_minutes(lot), "history": hist,
                "duration_h": bal.AUCTION_DURATION_HOURS}
    prods = t.products or {}

    def _good(k):
        fv = auc.fair_value(world, k)
        return {"key": k, "name": (prod.GOODS[k].name if k in prod.GOODS else k),
                "emoji": (prod.GOODS[k].emoji if k in prod.GOODS else "📦"),
                "stock": int(prods.get(k, 0)), "fv": int(round(fv)),
                # точные цены тиров (та же формула, что и при создании) — превью == факт
                "prices": [max(1, round(fv * m)) for m in bal.AUCTION_PRICE_TIERS]}
    goods = [_good(k) for k in auc.sellable_goods(t)]
    tiers = [{"mult": m, "label": lbl}
             for m, lbl in zip(bal.AUCTION_PRICE_TIERS, ("по рынку", "бодро", "дорого"))]
    return {"active": False, "goods": goods, "tiers": tiers,
            "presets": list(bal.AUCTION_QTY_PRESETS), "qty_max": bal.AUCTION_QTY_MAX,
            "duration_h": bal.AUCTION_DURATION_HOURS}


def _auc_result(res: dict) -> dict | None:
    """Итог последних торгов для финал-экрана (свежее AUCTION_DURATION ч)."""
    if not res:
        return None
    from datetime import datetime, timezone
    from bot.game import balance as bal, production as prod
    try:
        ts = datetime.fromisoformat(res["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - ts).total_seconds() > bal.AUCTION_DURATION_HOURS * 3600:
            return None
    except (KeyError, ValueError, TypeError):
        return None
    g = prod.GOODS.get(res.get("good"))
    out = {"sold": bool(res.get("sold")), "qty": res.get("qty"), "good": res.get("good"),
           "name": g.name if g else res.get("good"), "emoji": g.emoji if g else "📦"}
    if res.get("sold"):
        out["unit"] = res.get("unit"); out["gold"] = res.get("gold")
        out["winner"] = _auc_npc(res.get("npc"))
    return out


async def _api_auction(request: web.Request) -> web.Response:
    """Аукцион: живой лот или форма выставления. Гейт: admin/AUCTION_OPEN.
    Если лот вышел по таймеру — закрываем прямо тут и отдаём итог (финал-экран)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import auction as auc
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _auction_open(uid):
            return web.json_response({"ok": True, "open": False}, headers={"Cache-Control": "no-store"})
        world = await repo.get_or_create_world(s)
        if auc.is_due(p.tavern):                       # таймер вышел — закрыть немедленно
            res = auc.settle(p, p.tavern, world)
            repo.add_log(s, "player", p.id, "🔨 торги закрыты (мини-апп)")
            if res is not None:                        # DM как у нотифаера — чтобы паритет был полный
                from bot import texts as _t
                repo.queue_notify(s, p.id, _t.auction_settled(res))
            await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": _is_admin(uid), **_auction_state(p, world)}
        res = _auc_result((p.story or {}).get("auc_last"))
        if res and not out.get("active"):
            out["result"] = res
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_seen(request: web.Request) -> web.Response:
    """Игрок увидел финал-экран — гасим запомненный итог."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is not None and (p.story or {}).get("auc_last"):
            st = dict(p.story); st.pop("auc_last", None); p.story = st
            await s.commit()
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


async def _api_auction_create(request: web.Request) -> web.Response:
    """Выставить лот: {good, qty, tier} (индекс тира цены) или {good, qty, price}."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import auction as auc, balance as bal
    good = str(body.get("good") or "")
    try:
        qty = int(body.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _auction_open(uid):
            return web.json_response({"ok": False, "error": "closed"})
        world = await repo.get_or_create_world(s)
        if "tier" in body:
            prices = [max(1, round(auc.fair_value(world, good) * m)) for m in bal.AUCTION_PRICE_TIERS]
            try:
                price = prices[int(body.get("tier"))]
            except (TypeError, ValueError, IndexError):
                return web.json_response({"ok": False, "error": "price"})
        else:
            try:
                price = int(body.get("price") or 0)
            except (TypeError, ValueError):
                price = 0
        ok, reason = auc.create(p, p.tavern, good, qty, price)
        if not ok:
            return web.json_response({"ok": False, "error": reason})
        repo.add_log(s, "player", p.id, f"🔨 выставил лот {qty}×{good} по {price}🪙 (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": _is_admin(uid), **_auction_state(p, world)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_cancel(request: web.Request) -> web.Response:
    """Снять лот: замороженный товар вернётся в погреб."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import auction as auc
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not auc.cancel(p, p.tavern):
            return web.json_response({"ok": False, "error": "none"})
        repo.add_log(s, "player", p.id, "🔨 снял лот с торгов (мини-апп)")
        await s.commit()
        world = await repo.get_or_create_world(s)
        out = {"ok": True, "open": True, "gold": p.gold, "admin": _is_admin(uid), **_auction_state(p, world)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_seed(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): подбросить 2-3 живые ставки горожан на текущий лот —
    чтобы вживую проверить зал торгов/подсветку/финал, не дожидаясь нотифаера."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    import random
    from bot.game import auction as auc, npc as npcmod
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        world = await repo.get_or_create_world(s)
        lot = p.tavern.auction
        if not lot:
            return web.json_response({"ok": False, "error": "none"})
        lot = dict(lot)   # КОПИЯ (см. try_bid): иначе in-place мутация не сохранится (JSONB)
        rng = random.Random()
        added = 0
        for _ in range(rng.randint(2, 3)):                 # цена лезет от резерва вверх
            cit = npcmod.random_trader(rng)
            cur = lot.get("top_bid") or 0
            bid = lot["unit_min"] if cur == 0 else cur + rng.randint(1, 3)
            lot["top_bid"], lot["top_bidder"] = bid, cit.id
            lot["bids"] = lot.get("bids", 0) + 1
            hist = list(lot.get("history", []))
            hist.append({"npc": cit.id, "unit": bid})
            lot["history"] = hist[-5:]
            added += 1
        p.tavern.auction = dict(lot)                        # переприсваивание для JSONB
        repo.add_log(s, "player", p.id, f"🧪 тест: +{added} ставок на лот (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": True, **_auction_state(p, world)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_auction_settle_now(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): закрыть торги немедленно — увидеть финал «Продано/Не взяли»."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from bot.game import auction as auc
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not p.tavern.auction:
            return web.json_response({"ok": False, "error": "none"})
        world = await repo.get_or_create_world(s)
        auc.settle(p, p.tavern, world)
        repo.add_log(s, "player", p.id, "🧪 тест: торги закрыты вручную (мини-апп)")
        await s.commit()
        out = {"ok": True, "open": True, "gold": p.gold, "admin": True, **_auction_state(p, world)}
        res = _auc_result((p.story or {}).get("auc_last"))
        if res and not out.get("active"):
            out["result"] = res
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _bourse_open(uid: int) -> bool:
    from bot.game import balance as bal
    return bool(bal.BOURSE_OPEN) or _is_admin(uid)


def _good_dto(k: str) -> dict:
    from bot.game import production as prod
    g = prod.GOODS.get(k)
    return {"key": k, "name": g.name if g else k, "emoji": g.emoji if g else "📦"}


async def _bourse_state(s, p) -> dict:
    """Снимок биржи для игрока: чужие продажи/заявки, мои ордера, стакан, топ-
    продавцы и товары с коридором цены/пресетами/лимитом скупки (для форм)."""
    from bot.game import bourse, production as prod, balance as bal
    from sqlalchemy import select
    from bot.db.models import Player
    sells = await repo.open_orders(s, p.id, "sell", limit=20)   # чужие продажи → купить
    buys = await repo.open_orders(s, p.id, "buy", limit=20)     # чужие заявки → продать в них
    mine = await repo.seller_orders(s, p.id)
    board = await repo.market_summary(s)
    sellers = await repo.top_sellers(s, 10)
    ids = {o.seller_id for o in (*sells, *buys)}
    names = {}
    if ids:
        rows = (await s.execute(
            select(Player.id, Player.first_name).where(Player.id.in_(ids)))).all()
        names = {i: n for i, n in rows}

    def _ord(o, who: bool):
        d = {"id": o.id, "side": o.side, "qty": o.qty, "unit": o.unit_price, **_good_dto(o.good)}
        if who:
            d["who"] = names.get(o.seller_id) or "горожанин"
        return d

    board_list = [{**_good_dto(k), "ask": b.get("ask"), "ask_qty": b.get("ask_qty"),
                   "bid": b.get("bid"), "bid_qty": b.get("bid_qty"),
                   "floor": bourse.price_floor(k), "ceil": bourse.price_ceil(k)}
                  for k, b in sorted(board.items())]
    prods = p.tavern.products or {}
    goods = [{**_good_dto(k), "stock": int(prods.get(k, 0)),
              "floor": bourse.price_floor(k), "ceil": bourse.price_ceil(k),
              "presets": bourse.price_tiers(k), "room": bourse.buy_room(p, k)}
             for k in prod.GOODS]
    return {
        "gold": p.gold,
        "sells": [_ord(o, True) for o in sells],
        "buys": [_ord(o, True) for o in buys],
        "mine": [_ord(o, False) for o in mine],
        "board": board_list,
        "sellers": [{"name": t.name, "sold": int(t.auction_sold or 0), "me": pl.id == p.id}
                    for t, pl in sellers],
        "goods": goods,
        "qty_max": bal.BOURSE_QTY_MAX, "max_orders": bal.BOURSE_MAX_ORDERS,
    }


async def _api_bourse(request: web.Request) -> web.Response:
    """Биржа (P2P-ордербук): доска + товары. Гейт: admin/BOURSE_OPEN."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _bourse_open(uid):
            return web.json_response({"ok": True, "open": False}, headers={"Cache-Control": "no-store"})
        out = {"ok": True, "open": True, "admin": _is_admin(uid), **(await _bourse_state(s, p))}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _bourse_chat(p) -> int:
    """Источник ордеров мини-аппа: домашний чат игрока, иначе его id (матчинг
    глобальный, chat_id — лишь привязка)."""
    return p.chat_id if p.chat_id is not None else p.id


async def _api_bourse_act(request: web.Request) -> web.Response:
    """Действия Биржи (ФАЗА 2): {op, ...}. Переиспользует боевые исполнители
    текст-бота (_do_buy/_do_fill/_do_create_sell/_do_create_buy) — логика и
    налоги/лимиты/коридор идентичны бирже в чате. Возвращает свежую доску + итог."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import bourse, production as prod
    from bot.handlers.auction import (_do_buy, _do_fill, _do_create_sell, _do_create_buy)
    op = str(body.get("op") or "")

    def _int(key):
        try:
            return int(body.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not _bourse_open(uid):
            return web.json_response({"ok": False, "error": "closed"})
        chat = _bourse_chat(p)
        done = None

        if op in ("buy", "fill"):
            order = await repo.get_order(s, _int("order_id"), lock=True)
            if order is None or order.qty <= 0 or order.seller_id == p.id:
                return web.json_response({"ok": False, "error": "gone"})
            qty = _int("qty")
            if op == "buy":
                if order.side != "sell":
                    return web.json_response({"ok": False, "error": "gone"})
                cap = min(order.qty, p.gold // order.unit_price if order.unit_price else 0,
                          bourse.buy_room(p, order.good))
                qty = max(1, min(qty, cap))
                if cap <= 0:
                    return web.json_response({"ok": False, "error": "cant"})
                done = await _do_buy(s, p, chat, order, qty)
            else:
                if order.side != "buy":
                    return web.json_response({"ok": False, "error": "gone"})
                buyer = await repo.get_player(s, order.seller_id, for_update=True)
                if buyer is None or buyer.tavern is None:
                    await repo.delete_order(s, order.id)
                    await s.commit()
                    return web.json_response({"ok": False, "error": "gone"})
                stock = int((p.tavern.products or {}).get(order.good, 0))
                qty = max(1, min(qty, order.qty, stock))
                if stock <= 0:
                    return web.json_response({"ok": False, "error": "cant"})
                done = await _do_fill(s, p, chat, order, qty, buyer)

        elif op in ("sell", "bid"):
            good = str(body.get("good") or "")
            qty, price = _int("qty"), _int("price")
            if good not in prod.GOODS or qty <= 0 or not bourse.valid_price(good, price):
                return web.json_response({"ok": False, "error": "bad"})
            if op == "sell":
                stock = int((p.tavern.products or {}).get(good, 0))
                qty = min(qty, stock, _bal_qty_max())
                if qty <= 0:
                    return web.json_response({"ok": False, "error": "empty"})
                done = await _do_create_sell(s, p, chat, good, qty, price)
            else:
                qty = min(qty, _bal_qty_max())
                done = await _do_create_buy(s, p, chat, good, qty, price)

        elif op == "cancel":
            order = await repo.get_order(s, _int("order_id"), lock=True)
            if order is None or order.seller_id != p.id:
                return web.json_response({"ok": False, "error": "gone"})
            if order.side == "sell":
                bourse.unfreeze(p.tavern, order.good, order.qty)
                done = "Лот снят — товар вернулся в погреб."
            else:
                p.gold += order.qty * order.unit_price
                done = f"Заявка снята — залог {order.qty * order.unit_price} 🪙 вернулся."
            await repo.delete_order(s, order.id)
        else:
            return web.json_response({"ok": False, "error": "bad_op"})

        await s.commit()
        out = {"ok": True, "open": True, "admin": _is_admin(uid), "done": done,
               **(await _bourse_state(s, p))}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


def _bal_qty_max() -> int:
    from bot.game import balance as bal
    return bal.BOURSE_QTY_MAX


async def _api_chronicle(request: web.Request) -> web.Response:
    """Летопись домашнего города игрока — лента заметных событий (свежие сверху)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from datetime import datetime, timezone
    from sqlalchemy import select
    from bot.db.models import Chronicle
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None:
            return web.json_response({"ok": False, "error": "no_tavern"})
        entries = []
        if p.chat_id is not None:
            rows = (await s.execute(
                select(Chronicle.text, Chronicle.ts)
                .where(Chronicle.chat_id == p.chat_id)
                .order_by(Chronicle.id.desc()).limit(40))).all()
            now = datetime.now(timezone.utc)
            entries = [{"text": t, "ago": _chron_ago(ts, now)} for t, ts in rows]
    return web.json_response({"ok": True, "entries": entries}, headers={"Cache-Control": "no-store"})


async def _api_referral(request: web.Request) -> web.Response:
    """Зазывала (рефералка): личная ссылка, прогресс по вехам, топ зазывал.
    Зеркало texts.referral_screen / referrers_screen из бота."""
    from urllib.parse import quote
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal
    from bot.keyboards.inline import get_bot_username
    _SHARE_TEXT = "Айда в Недоливск — заведём кабаки и зальём весь город элем! 🍺"
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None:
            return web.json_response({"ok": False, "error": "no_tavern"})
        uname = get_bot_username()
        link = f"https://t.me/{uname}?start=ref_{p.id}" if uname else ""
        share_url = (f"https://t.me/share/url?url={quote(link)}&text={quote(_SHARE_TEXT)}"
                     if link else "")
        invited = await repo.count_referrals(s, p.id)
        tier = int(p.ref_tier or 0)
        tiers = [{"need": need, "bonus": bonus, "done": i < tier}
                 for i, (need, bonus) in enumerate(bal.REFERRAL_TIERS)]
        nxt = None
        if tier < len(bal.REFERRAL_TIERS):
            need, bonus = bal.REFERRAL_TIERS[tier]
            nxt = {"need": need, "bonus": bonus, "left": max(0, need - invited)}
        rows = await repo.top_referrers(s)
        top = [{"name": (pl.first_name or "—"), "count": n, "me": pl.id == p.id}
               for pl, n in rows]
    return web.json_response({
        "ok": True, "link": link, "share_url": share_url, "invited": invited,
        "tier": tier, "tiers": tiers, "next": nxt,
        "reward": {"inviter_gold": bal.REFERRAL_INVITER_GOLD,
                   "inviter_rep": bal.REFERRAL_INVITER_REP,
                   "invitee_gold": bal.REFERRAL_INVITEE_GOLD},
        "top": top,
    }, headers={"Cache-Control": "no-store"})


async def _api_story_choice(request: web.Request) -> web.Response:
    """Резолв выбора у визитёра (story_engine.resolve): применить эффекты, записать
    летопись, эхо в общий чат (через очередь нотифаера), вернуть исход + дельты."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from datetime import datetime, timezone
    from bot.game import story_engine as se, story_state as ss, balance as bal, production as prod
    idx = int(body.get("index", -1))
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        st = se.pending_storylet(p)
        if st is None:
            if ss.get_pending(p):
                ss.clear_pending(p); await s.commit()
            return web.json_response({"ok": False, "error": "gone"})
        now = datetime.now(timezone.utc)
        city = await repo.get_or_create_city(s, p.chat_id, lock=True) if p.chat_id else None
        shielded = ss.is_shielded(p, now)
        g0, r0 = int(p.gold), int(p.reputation or 0)
        inv0 = dict(p.inventory or {}); cel0 = dict((p.tavern.products or {}))
        outcome, ctx = se.resolve(p, city, st, idx, now, shielded=shielded)
        if outcome is None:
            return web.json_response({"ok": False, "error": "unavailable"})
        if p.chat_id is not None:
            for line in ctx.chronicle:
                await repo.add_chronicle(s, p.chat_id, line)
            for line in ctx.chat_echo:               # эхо в группу — через очередь нотифаера
                repo.queue_notify(s, p.chat_id, line)
        repo.add_log(s, "player", p.id, f"🚪 {st.title}")
        await s.commit()
        # дельты для красивого исхода
        names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
        emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
        res = []
        for src0, src1 in ((inv0, dict(p.inventory or {})), (cel0, dict(p.tavern.products or {}))):
            for k in set(src0) | set(src1):
                d = src1.get(k, 0) - src0.get(k, 0)
                if d:
                    gd = prod.GOODS.get(k)
                    res.append({"key": k, "qty": int(d),
                                "name": gd.name if gd else names.get(k, k),
                                "emoji": gd.emoji if gd else emojis.get(k)})
        out = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "title": st.title, "text": outcome.text,
                              "gold": int(p.gold) - g0, "rep": int(p.reputation or 0) - r0,
                              "res": res, "state": out}, headers={"Cache-Control": "no-store"})


async def _api_collect(request: web.Request) -> web.Response:
    """Собрать накопленный доход (пассив) — та же logic.collect_income, что у бота."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import logic
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        res = logic.collect_income(p, p.tavern)
        collected = int(getattr(res, "passive", 0) or 0)
        if collected > 0:
            repo.add_log(s, "player", p.id, f"🪙 собрал доход +{collected}")
        order = getattr(res, "order", None)        # гости хотят выкупить товар из погреба
        if order:
            from bot.game import story_state
            story_state.set_retail(p, order)
        # Заезжий купец — как в боте (tavern.py): на сбор дохода заглядывает покупатель
        # готового товара (чаще/богаче на ярмарке). Розница приоритетнее — тогда не катим.
        trade_offer = None
        if not order:
            import random as _rnd
            from bot.game import story_state as _ss, trade as _trade, balance as _bal, world as _wld
            busy = _ss.get_pending(p) or _ss.get_trade(p)
            if not busy and _trade.has_sellable(p.tavern):
                chance = _bal.TRADE_FAIR_CHANCE if _wld.is_fair() else _bal.TRADE_CHANCE
                if _rnd.random() < chance:
                    world = await repo.get_or_create_world(s)
                    offer = _trade.make_offer(p.tavern, p, _wld.is_fair(), world=world)
                    if offer is not None:
                        _ss.set_trade(p, offer)
                        trade_offer = offer
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "collected": collected, "state": st,
                              "retail": bool(order), "trade": _trade_dto(trade_offer)},
                             headers={"Cache-Control": "no-store"})


async def _api_trade(request: web.Request) -> web.Response:
    """Торг с заезжим купцом: {op: offer(idx) | accept | push | decline}.
    Переиспользует боевую продажу _sell + trade.evaluate/push/reaction — характеры,
    контр-цены и зачисления идентичны торгу в чате. Возвращает исход + свежий торг/таверну."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    op = str(body.get("op") or "")
    from bot.game import (story_state as ss, trade as trademod, market,
                          balance as bal, newbie, production as prod)
    from bot.handlers.trade import _sell          # боевая продажа (товар/золото/буфы/имя)
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        offer = ss.get_trade(p)
        if not offer:
            return web.json_response({"ok": False, "error": "gone"})
        world = await repo.get_or_create_world(s)
        st = {"result": None, "react": None, "qty": 0, "gold": 0, "unit": 0}

        def _finish(unit: int, kind: str) -> None:
            qn, gn = _sell(p, offer, unit)
            ss.set_trade(p, None)
            if qn:
                newbie.mark(p, "nb_sale")
                gn_name = prod.GOODS[offer["good"]].name if offer["good"] in prod.GOODS else offer["good"]
                repo.add_log(s, "player", p.id, f"🤝 продал купцу {qn}×{gn_name} за {gn} 🪙 (мини-апп)")
                market.nudge(world, offer["good"], qn * bal.MARKET_WHOLESALE_WEIGHT)
                st.update(result="sold", react=trademod.reaction(offer, kind), qty=qn, gold=gn, unit=unit)
            else:
                st.update(result="walk", react=trademod.reaction(offer, "walk"))

        if op == "decline":
            ss.set_trade(p, None)
            st.update(result="walk", react=trademod.reaction(offer, "walk"))
        elif op == "accept":                          # согласие на контр-цену
            unit = int(offer.get("counter", offer["max_unit"]))
            _finish(unit, "accept_high" if unit >= offer["fv"] * 1.15 else "accept")
        elif op == "push":                            # дожать контр-цену
            decision, price = trademod.push(offer)
            if decision == "walk":
                ss.set_trade(p, None)
                st.update(result="walk", react=trademod.reaction(offer, "walk"))
            else:
                offer["counter"] = price
                ss.set_trade(p, offer)
                st.update(result="counter", react=trademod.reaction(offer, decision, price))
        elif op == "offer":                           # предложить цену из тира
            try:
                idx = int(body.get("idx"))
            except (TypeError, ValueError):
                idx = -1
            if not 0 <= idx < len(offer.get("prices", [])):
                return web.json_response({"ok": False, "error": "bad"})
            unit = offer["prices"][idx]
            decision, price = trademod.evaluate(offer, unit)
            if decision == "accept":
                _finish(unit, "accept_high" if unit >= offer["fv"] * 1.15 else "accept")
            elif decision == "counter":
                offer["counter"] = price
                ss.set_trade(p, offer)
                st.update(result="counter", react=trademod.reaction(offer, "counter", price))
            else:
                ss.set_trade(p, None)
                st.update(result="walk", react=trademod.reaction(offer, "walk"))
        else:
            return web.json_response({"ok": False, "error": "bad_op"})

        await s.commit()
        out = {"ok": True, "gold": p.gold, **st,
               "trade": _trade_dto(ss.get_trade(p)), "state": _tavern_state(p, p.tavern)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_upgrade(request: web.Request) -> web.Response:
    """Улучшить таверну — та же logic.try_upgrade (валидация ресурсов/макс-уровня)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import logic
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        r = logic.try_upgrade(p, p.tavern)
        if not r.ok:                       # not_enough | max_level
            return web.json_response({"ok": False, "error": r.reason,
                                      "state": _tavern_state(p, p.tavern)})
        repo.add_log(s, "player", p.id, f"🔨 улучшил таверну до ур. {r.new_level}")
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "level": r.new_level, "state": st},
                             headers={"Cache-Control": "no-store"})


def _panel_data(p, t, kind: str) -> dict:
    """Данные для bottom-sheet панели действия (бонус/грамота/бригады) —
    те же функции/тексты, что и экраны бота, в JSON."""
    from bot import texts
    from bot.game import balance as bal, buff as buffmod, logic, newbie as nb, season

    if kind == "bonus":
        act = buffmod.active(p)
        if act is not None:
            return {"kind": "bonus", "active": True, "emoji": act.emoji, "name": act.name,
                    "desc": act.desc, "minutes_left": buffmod.minutes_left(p)}
        boon = buffmod.offer(p)
        if boon is None:
            return {"kind": "bonus", "active": False, "available": False}
        return {"kind": "bonus", "active": False, "available": True,
                "emoji": boon.emoji, "name": boon.name, "desc": boon.desc,
                "hours": buffmod.BUFF_HOURS, "reset_h": buffmod.offer_hours_left(p)}

    if kind == "newbie":
        tasks = [{"label": label, "reward": texts._reward_str(reward),
                  "status": "claimed" if claimed else ("ready" if done else "todo")}
                 for _k, label, reward, done, claimed in nb.states(p, t)]
        return {"kind": "newbie", "tasks": tasks, "claimable": nb.claimable(p, t),
                "perks": nb.perks_active(p), "grace_days": nb.NEWBIE_GRACE_DAYS}

    if kind == "upgrade":
        from bot.game import balance as bal
        if t.level >= bal.MAX_LEVEL:
            return {"kind": "upgrade", "maxed": True}
        cost = bal.upgrade_cost(t.level)
        ns = bal.stats_for_level(t.level + 1)
        inv = p.inventory or {}
        names = {"gold": "Золото", **bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
        items = []
        for k, v in cost.items():
            have = int(p.gold) if k == "gold" else int(inv.get(k, 0))
            items.append({"key": k, "name": names.get(k, k), "need": int(v),
                          "have": have, "ok": have >= int(v)})
        gains = [
            {"label": "Места", "frm": int(t.capacity), "to": int(ns["capacity"])},
            {"label": "Уют", "frm": int(t.comfort), "to": int(ns["comfort"])},
            {"label": "Доход/ч", "frm": int(t.income_rate), "to": int(ns["income_rate"])},
        ]
        return {"kind": "upgrade", "level": int(t.level), "next": int(t.level) + 1,
                "cost": items, "gains": gains, "affordable": all(i["ok"] for i in items),
                "gold_cost": int(cost.get("gold", 0))}

    if kind == "retail":
        from bot.game import production as prod, story_state
        want = story_state.get_retail(p)
        if not want:
            return {"kind": "retail", "empty": True}
        items = [{"key": k, "name": prod.GOODS[k].name, "emoji": prod.GOODS[k].emoji,
                  "qty": int(n), "price": prod.GOODS[k].price, "sum": int(n) * prod.GOODS[k].price}
                 for k, n in sorted(want.items(), key=lambda kv: -prod.GOODS[kv[0]].price)
                 if k in prod.GOODS]
        return {"kind": "retail", "items": items, "total": logic.retail_total(want, p)}

    # expedition — статус бригад, «на что копить», список ресурсов для отправки
    c = logic.expedition_counts(p, t)
    level = t.level
    goals, _tot = logic.expedition_goals(p, t)
    goal_list = [{"label": label,
                  "items": [{"key": r, "name": bal.RESOURCE_NAMES.get(r, r), "qty": q}
                            for r, q in short.items()]}
                 for label, short in goals]
    resources = []
    if c.free > 0:
        for res in bal.RESOURCES:
            amt = int(bal.expedition_yield(res, level, p.region) * season.yield_mult(res))
            resources.append({"key": res, "name": bal.RESOURCE_NAMES.get(res, res), "amount": amt})
    return {"kind": "expedition", "free": c.free, "total": c.total, "out": c.out,
            "ready": c.ready, "next_minutes": c.next_minutes,
            "pay": bal.worker_pay(level), "hours": bal.EXPEDITION_HOURS,
            "goals": goal_list, "resources": resources}


async def _api_panel(request: web.Request) -> web.Response:
    """Снапшот данных для bottom-sheet панели (чтение)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    kind = str(body.get("kind") or "")
    if kind not in ("bonus", "newbie", "expedition", "retail", "upgrade"):
        return web.json_response({"ok": False, "error": "bad_kind"})
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        panel = _panel_data(p, p.tavern, kind)
    return web.json_response({"ok": True, "panel": panel},
                             headers={"Cache-Control": "no-store"})


async def _api_expedition_start(request: web.Request) -> web.Response:
    """Отправить бригаду за ресурсом — logic.start_expedition (плата вперёд)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal, logic
    res_key = str(body.get("resource") or "")
    if res_key not in bal.RESOURCES:
        return web.json_response({"ok": False, "error": "bad_resource"})
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        r = logic.start_expedition(p, p.tavern, res_key)
        if not r.ok:                           # no_slot | no_gold
            return web.json_response({"ok": False, "error": r.reason,
                                      "panel": _panel_data(p, p.tavern, "expedition")})
        repo.add_log(s, "player", p.id, f"⛏ отправил бригаду за {bal.RESOURCE_NAMES.get(res_key, res_key)}")
        await s.commit()
        st = _tavern_state(p, p.tavern)
        panel = _panel_data(p, p.tavern, "expedition")
    return web.json_response({"ok": True, "state": st, "panel": panel},
                             headers={"Cache-Control": "no-store"})


async def _api_bonus(request: web.Request) -> web.Response:
    """Активировать «бонус дня» (опохмел) — buff.refresh + buff.activate."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import buff as buffmod
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        buffmod.refresh(p)
        res = buffmod.activate(p)
        if not res.ok:                         # busy (баф уже идёт) | none (нет предложения)
            return web.json_response({"ok": False, "error": res.reason or "none",
                                      "state": _tavern_state(p, p.tavern)})
        repo.add_log(s, "player", p.id, f"🎁 активировал баф «{res.boon.name}»")
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "state": st,
                              "boon": res.boon.name, "minutes": res.minutes},
                             headers={"Cache-Control": "no-store"})


async def _api_newbie(request: web.Request) -> web.Response:
    """Забрать награды «грамоты новосёла» — newbie.claim_all."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import newbie
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not newbie.claimable(p, p.tavern):
            return web.json_response({"ok": False, "error": "nothing"})
        total = newbie.claim_all(p, p.tavern)
        if total:
            repo.add_log(s, "player", p.id,
                         f"📜 забрал награды грамоты: {sum(total.values())} ед.")
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "state": st, "reward": total},
                             headers={"Cache-Control": "no-store"})


async def _api_expedition(request: web.Request) -> web.Response:
    """Забрать добычу вернувшихся бригад — logic.claim_expeditions."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import logic
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        claimed = logic.claim_expeditions(p)
        if not claimed:
            return web.json_response({"ok": False, "error": "nothing"})
        total = sum(amount for _, amount, _ in claimed)
        repo.add_log(s, "player", p.id, f"🎒 забрал добычу бригад: {total} ед.")
        await s.commit()
        st = _tavern_state(p, p.tavern)
        panel = _panel_data(p, p.tavern, "expedition")
    return web.json_response({"ok": True, "state": st, "claimed": total, "panel": panel},
                             headers={"Cache-Control": "no-store"})


async def _api_retail_sell(request: web.Request) -> web.Response:
    """Налить гостям — продать заказанный товар из погреба (logic.apply_retail)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import logic, newbie, story_state
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        want = story_state.get_retail(p)
        if not want:
            return web.json_response({"ok": False, "error": "gone"})
        sold, gold, rep = logic.apply_retail(p, p.tavern, want)
        story_state.set_retail(p, None)
        if sold:
            newbie.mark(p, "nb_sale")          # веха грамоты новосёла
            repo.add_log(s, "player", p.id, f"🍺 налил гостям: +{gold} 🪙, +{rep} репутации")
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "state": st, "gold": gold, "rep": rep, "sold": bool(sold)},
                             headers={"Cache-Control": "no-store"})


async def _api_retail_hold(request: web.Request) -> web.Response:
    """Придержать товар — отклонить заказ гостей."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import story_state
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        story_state.set_retail(p, None)
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "state": st}, headers={"Cache-Control": "no-store"})


def _character_state(p) -> dict:
    """Состояние Персонажа для мини-аппа — статы/снаряжение/кузница из тех же
    функций бота (items/combat/logic)."""
    from bot.game import balance as bal, combat, items as it, logic

    eq = p.equipment or {}
    cs = it.combat_stats(eq)
    dmg = bal.BASE_DAMAGE + cs["damage"]
    crit = min(bal.HUNT_CRIT_CAP, cs["crit"] + cs["luck"] // 2)

    slots = []
    for slot_key, slot_name in it.SLOTS.items():
        entry = eq.get(slot_key)
        item = it.CATALOG.get(it.parse_entry(entry)[0]) if entry else None
        if item:
            _, tier = it.parse_entry(entry)
            slots.append({"slot": slot_key, "slot_name": slot_name, "id": item.id,
                          "name": item.name, "tier": tier, "sprite": item.sprite or item.id,
                          "trophy": not item.craftable})
        else:
            slots.append({"slot": slot_key, "slot_name": slot_name})

    bonuses = []
    im = it.income_multiplier(eq)
    if im > 1: bonuses.append({"label": "Доход", "val": f"+{round((im - 1) * 100)}%"})
    ym = it.yield_multiplier(eq, "grain")
    if ym > 1: bonuses.append({"label": "Добыча", "val": f"+{round((ym - 1) * 100)}%"})
    sm = it.speed_multiplier(eq)
    if sm < 1: bonuses.append({"label": "Время вылазок", "val": f"−{round((1 - sm) * 100)}%"})
    pm = it.pay_multiplier(eq)
    if pm < 1: bonuses.append({"label": "Плата работникам", "val": f"−{round((1 - pm) * 100)}%"})

    orc = None
    if it.orc_set_complete(eq):
        b = it.ORC_SET_BONUS
        orc = {**b, "income": it.ORC_SET_INCOME_PCT}

    state, minutes = logic.craft_state(p)
    craft = {"state": state}
    if state != "none" and p.craft_item:
        iid, tier = it.parse_entry(p.craft_item)
        cit = it.CATALOG.get(iid)
        craft.update({"name": cit.name if cit else "вещь", "tier": tier, "minutes": minutes,
                      "sprite": (cit.sprite or iid) if cit else None})

    # лечение: чем можно подлечиться из погреба (combat.heal)
    from bot.game import production as prod
    hp_cur, hp_max = combat.current_hp(p), combat.max_hp()
    prods = (p.tavern.products if p.tavern else None) or {}
    heal_opts = [{"key": k, "name": prod.GOODS[k].name, "emoji": prod.GOODS[k].emoji,
                  "hp": bal.HEAL_VALUES[k], "qty": int(prods.get(k, 0))}
                 for k in bal.HEAL_VALUES if k in prod.GOODS and int(prods.get(k, 0)) > 0]

    return {
        "ok": True, "name": (p.first_name or "Хозяин").upper(),
        "worn": len(eq), "slots_total": len(it.SLOTS),
        "hp": {"cur": hp_cur, "max": hp_max, "regen": combat.regen_full_minutes(p)},
        "damage": dmg, "crit": crit, "armor": cs["armor"], "luck": cs["luck"],
        "vylazka": bal.lucky_chance(cs["luck"]),
        "equipment": slots, "bonuses": bonuses, "orc": orc, "craft": craft,
        "heal": {"can": hp_cur < hp_max, "full": hp_cur >= hp_max, "options": heal_opts},
    }


def _forge_state(p) -> dict:
    """Список кузницы: куётся (с фильтром региона) + надетые трофеи; стоимость/ярус/часы."""
    from bot import texts
    from bot.game import balance as bal, items as it, logic

    eq = p.equipment or {}
    inv = p.inventory or {}
    names = {"gold": "Золото", **bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {"gold": "🪙", **bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
    state, minutes = logic.craft_state(p)

    def mk(item, trophy):
        cur = it.equipped_tier(eq, item.id)
        maxed = trophy or cur >= it.TIER_MAX
        nxt = cur if maxed else min(cur + 1, it.TIER_MAX)
        cost = []
        if not maxed:
            for k, v in it.tier_cost(item, nxt).items():
                if not v:
                    continue
                have = int(p.gold) if k == "gold" else int(inv.get(k, 0))
                cost.append({"key": k, "name": names.get(k, k), "emoji": emojis.get(k),
                             "need": int(v), "have": have, "ok": have >= int(v)})
        return {
            "id": item.id, "name": item.name, "slot_name": it.SLOTS[item.slot],
            "sprite": item.sprite or item.id, "desc": item.description,
            "cur": cur, "next": nxt, "maxed": maxed, "trophy": trophy,
            "gains_cur": texts._tier_bonus_line(item, cur) if cur else None,
            "gains_next": texts._tier_bonus_line(item, nxt if nxt else it.TIER_MAX),
            "cost": cost, "hours": it.tier_hours(item, nxt) if not maxed else 0,
            "afford": bool(cost) and all(c["ok"] for c in cost),
        }

    out = [mk(i, False) for i in it.CATALOG.values()
           if i.craftable and not (i.id in it.REGION_GEAR and it.REGION_GEAR[i.id] != p.region)]
    out += [mk(i, True) for i in it.CATALOG.values()
            if not i.craftable and it.equipped_tier(eq, i.id)]
    pouch = {k: (int(p.gold) if k == "gold" else int(inv.get(k, 0)))
             for k in ("gold", "wood", "grain", "hops", "ingot")}
    return {"ok": True, "pouch": pouch, "items": out, "craft": {"state": state, "minutes": minutes}}


async def _api_character(request: web.Request) -> web.Response:
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        st = _character_state(p)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_forge(request: web.Request) -> web.Response:
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        st = _forge_state(p)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_forge_make(request: web.Request) -> web.Response:
    """Заказать ковку (logic.start_craft, оплата вперёд, один заказ за раз)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import logic
    item_id = str(body.get("item_id") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        r = logic.start_craft(p, item_id)
        if not r.ok:                           # busy | unknown | not_enough | max_tier
            return web.json_response({"ok": False, "error": r.reason})
        repo.add_log(s, "player", p.id, f"⚒ заказал ковку «{r.item.name}» ★{r.tier}")
        await s.commit()
        ch, fg = _character_state(p), _forge_state(p)
    return web.json_response({"ok": True, "character": ch, "forge": fg,
                              "item": r.item.name, "tier": r.tier, "hours": r.hours},
                             headers={"Cache-Control": "no-store"})


async def _api_heal(request: web.Request) -> web.Response:
    """Подлечиться — съесть порцию из погреба, +HP (combat.heal)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import combat
    key = str(body.get("key") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        res = combat.heal(p, key)
        if res is None:
            return web.json_response({"ok": False, "error": "cant",
                                      "character": _character_state(p)})
        repo.add_log(s, "player", p.id, f"🍖 подлечился (+{res['healed']} HP)")
        await s.commit()
        ch = _character_state(p)
    return web.json_response({"ok": True, "character": ch, "healed": res["healed"], "hp": res["hp"]},
                             headers={"Cache-Control": "no-store"})


async def _api_craft_claim(request: web.Request) -> web.Response:
    """Забрать готовую вещь — сразу надевается (logic.claim_craft)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import logic
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        r = logic.claim_craft(p)
        if not r.ok:                           # none | not_ready
            return web.json_response({"ok": False, "error": r.reason, "minutes": r.minutes_left})
        repo.add_log(s, "player", p.id, f"🎁 выковал «{r.item.name}» ★{r.tier}")
        await s.commit()
        ch, fg = _character_state(p), _forge_state(p)
    return web.json_response({"ok": True, "character": ch, "forge": fg,
                              "item": r.item.name, "tier": r.tier},
                             headers={"Cache-Control": "no-store"})


# ===== Пристройки + Производство (порт bot/handlers/buildings.py) =====

def _cost_items(p, cost: dict) -> list:
    """Стоимость в виде [{key,name,emoji,need,have,ok}] — для стройки и рецептов.
    Единый лукап имён/эмодзи (как в кузнице): gold + RESOURCE_* + GOODS_*."""
    from bot.game import balance as bal
    names = {"gold": "Золото", **bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {"gold": "🪙", **bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
    inv = p.inventory or {}
    out = []
    for k, v in cost.items():
        if not v:
            continue
        have = int(p.gold) if k == "gold" else int(inv.get(k, 0))
        out.append({"key": k, "name": names.get(k, k), "emoji": emojis.get(k),
                    "need": int(v), "have": have, "ok": have >= int(v)})
    return out


def _ends_epoch(ready_iso, extra_min: int = 0):
    """Эпоха (сек) готовности партии — для живого отсчёта на клиенте. None — нет."""
    from datetime import datetime, timedelta
    try:
        return (datetime.fromisoformat(ready_iso) + timedelta(minutes=extra_min)).timestamp()
    except (TypeError, ValueError):
        return None


def _buildings_state(p) -> dict:
    """Список пристроек: статус каждой + текущий слот стройки (1 за раз)."""
    from bot.game import buildings as bld, production as prod
    t = p.tavern
    done = bld.finalize_build(p, t)               # ленивое достраивание при открытии
    bstate, bmin = bld.build_state(p)
    items = []
    for bid in bld.ORDER:
        b = bld.CATALOG[bid]
        lock = None
        if bld.is_built(t, bid):
            status, mins = "built", 0
        elif p.build_item == bid:
            status, mins = "building", bld.build_state(p)[1]
        elif bld.missing_requirements(t, b):
            status, mins = "locked", 0
            lock = "Нужна: " + ", ".join(r.name for r in bld.missing_requirements(t, b))
        elif bld.rep_locked(t, b):
            status, mins = "locked", 0
            lock = f"Репутация {b.req_reputation} · у тебя {int(t.reputation)}"
        else:
            status, mins = "available", 0
        prodst = None                                 # состояние производства (для точки-статуса)
        if status == "built" and bid in prod.PRODUCERS:
            if bid == "brewery":
                ph, pm = prod.brew_phase(t)
                pstate = ("active" if ph in ("fermenting", "aging")
                          else "ready" if ph in ("ready", "ripe", "overripe") else "none")
            else:
                pstate, pm = prod.state(t, bid)
            prodst = {"state": pstate, "minutes": pm}
        items.append({"id": bid, "emoji": b.emoji, "name": b.name, "status": status,
                      "minutes": mins, "lock": lock, "producer": bid in prod.PRODUCERS,
                      "prod": prodst})
    bname = (bld.CATALOG[p.build_item].name
             if p.build_item and p.build_item in bld.CATALOG else None)
    return {"ok": True, "level": int(t.level), "gold": int(p.gold),
            "reputation": int(t.reputation), "finished": done.name if done else None,
            "build": {"state": bstate, "minutes": bmin, "id": p.build_item, "name": bname},
            "list": items}


def _building_detail(p, bid: str) -> dict:
    """Деталь непостроенного здания: цена/время/гейты + can_build/afford."""
    from bot.game import buildings as bld
    b = bld.CATALOG.get(bid)
    if b is None:
        return {"ok": False, "error": "unknown"}
    t = p.tavern
    built = bld.is_built(t, bid)
    miss = bld.missing_requirements(t, b)
    bstate, bmin = bld.build_state(p)
    lock = None
    if not built:
        if p.build_item == bid:                       # это здание сейчас и возводится
            lock = {"kind": "self", "minutes": bmin, "text": "Возводится"}
        elif miss:
            lock = {"kind": "requires",
                    "text": "Сначала построй: " + ", ".join(r.name for r in miss)}
        elif bld.rep_locked(t, b):
            lock = {"kind": "reputation",
                    "text": f"Нужна репутация {b.req_reputation} · у тебя {int(t.reputation)}"}
        elif bstate != "none":
            lock = {"kind": "busy", "minutes": bmin,
                    "text": "Идёт другая стройка — артель одна"}
    cost = _cost_items(p, bld.cost_of(b))
    can_build = not built and bstate == "none" and bld.buildable(t, b)
    return {"ok": True, "id": bid, "emoji": b.emoji, "name": b.name,
            "desc": b.description, "unlocks": b.unlocks, "image": bid, "built": built,
            "build_hours": b.build_hours, "cost": cost, "lock": lock,
            "produces": _building_produces(bid), "level": int(t.level),
            "requires": [{"id": r, "emoji": bld.CATALOG[r].emoji, "name": bld.CATALOG[r].name}
                         for r in b.requires],
            "req_reputation": int(b.req_reputation),
            "can_build": can_build, "afford": all(c["ok"] for c in cost)}


def _building_produces(bid: str) -> list:
    """Что здание производит — для превью перед стройкой: выход, цена/назначение."""
    from bot.game import balance as bal, production as prod
    names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
    use = {"malt": "сырьё для варки эля", "flour": "сырьё для выпечки",
           "ingot": "сырьё для ковки снаряги"}
    if bid in prod.GRIND:
        keys, good = list(prod.GRIND[bid]), False
    elif bid in prod.RECIPES:
        keys, good = list(prod.RECIPES[bid]), True
    elif bid == "brewery":
        keys, good = ["ale1", "ale2", "ale3"], True
    elif bid == "meadery":
        keys, good = list(prod.MEADERY), True
    elif bid == "kitchen":
        keys, good = list(prod.KITCHEN), True
    elif bid == "winery":
        keys, good = list(prod.WINERY), True
    else:
        return []
    brew_name = {"ale1": "Эль ★", "ale2": "Светлое ★★", "ale3": "Праздничное ★★★"}
    out = []
    for k in keys:
        g = prod.GOODS.get(k)
        out.append({"key": k, "good": good,
                    "name": brew_name.get(k) or (g.name if g else names.get(k, k)),
                    "emoji": g.emoji if g else emojis.get(k),
                    "price": g.price if g else None, "use": use.get(k)})
    return out


async def _api_buildings(request: web.Request) -> web.Response:
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        st = _buildings_state(p)
        await s.commit()                          # finalize_build мог достроить
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_building(request: web.Request) -> web.Response:
    """Деталь здания: производство, если построено и оно производитель; иначе — стройка."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import buildings as bld, production as prod
    bid = str(body.get("id") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if bld.is_built(p.tavern, bid) and bid in prod.PRODUCERS:
            st = _production_state(p, bid)
        else:
            st = _building_detail(p, bid)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_build_start(request: web.Request) -> web.Response:
    """Заложить пристройку (buildings.start_build, оплата вперёд, один слот за раз)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import buildings as bld
    bid = str(body.get("id") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        bld.finalize_build(p, p.tavern)           # вдруг прошлая уже готова
        r = bld.start_build(p, p.tavern, bid)
        if not r.ok:                              # unknown|built|busy|requires|reputation|not_enough
            return web.json_response({"ok": False, "error": r.reason})
        repo.add_log(s, "player", p.id, f"🏗 заложил постройку: {r.building.name}")
        await s.commit()
        st = _buildings_state(p)
    return web.json_response({"ok": True, "name": r.building.name, "hours": r.hours,
                              "buildings": st}, headers={"Cache-Control": "no-store"})


def _production_state(p, bid: str) -> dict:
    """Экран производства построенного здания: рецепты, текущая партия, склад."""
    from bot.game import balance as bal, buildings as bld, inventory, production as prod
    t = p.tavern
    b = bld.CATALOG[bid]
    L = int(t.level)
    names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}

    def gname(k):
        g = prod.GOODS.get(k)
        return g.name if g else names.get(k, k)

    def gemoji(k):
        g = prod.GOODS.get(k)
        return g.emoji if g else emojis.get(k)

    is_good = lambda k: k in prod.GOODS                       # товар (GoodIcon) vs сырьё (ResIcon)
    base = {"ok": True, "id": bid, "emoji": b.emoji, "name": b.name,
            "desc": b.description, "image": bid, "level": L}
    braw = (t.production or {}).get(bid) or {}

    # ── Пивоварня (фазы + выдержка) ───────────────────────────────────────
    if bid == "brewery":
        phase, minutes = prod.brew_phase(t)
        tier = int(braw.get("tier", 0)) if phase != "empty" else 0
        bname = {1: "Эль", 2: "Светлое", 3: "Праздничное"}    # флейвор-имена ярусов (как кнопки бота)
        anm = lambda tt: f"{bname[tt]} {prod.ALE_STARS[tt]}"
        recipes = [{"key": f"ale{tt}", "tier": tt, "name": anm(tt),
                    "emoji": "🍺", "good": True, "out_qty": prod.brew_output(tt, L),
                    "time": f"{prod.brew_hours(tt)} ч",
                    "inputs": _cost_items(p, prod.brew_inputs(tt, L))} for tt in (1, 2, 3)]
        stock = [{"key": f"ale{tt}", "name": anm(tt), "emoji": "🍺",
                  "good": True, "qty": int((t.products or {}).get(f"ale{tt}", 0))}
                 for tt in (1, 2, 3)]
        bstate = ("active" if phase in ("fermenting", "aging")
                  else "ready" if phase in ("ready", "ripe", "overripe") else "none")
        ends = (_ends_epoch(braw.get("ready_at")) if phase in ("fermenting", "aging")
                else _ends_epoch(braw.get("ready_at"), prod._brew_grace_minutes(tier)) if phase == "ripe"
                else None)
        base.update(kind="brewery", to="cellar", recipes=recipes, stock=stock,
                    batch={"state": bstate, "minutes": minutes, "ends_at": ends,
                           "total": prod.brew_hours(tier) * 60 if tier else 0,
                           "out": ({"key": f"ale{tier}", "name": anm(tier),
                                    "emoji": "🍺", "good": True,
                                    "qty": int(braw.get("out_qty", 0))} if tier else None)},
                    brewery={"phase": phase, "minutes": minutes, "tier": tier,
                             "next_tier": min(3, tier + 1), "can_age": phase == "ready" and tier < 3,
                             "mature_chance": prod.MATURE_CHANCE})
        return base

    # ── Грайнд (мельница/горн): сырьё → полуфабрикат в инвентарь ───────────
    if bid in prod.GRIND:
        state, minutes = prod.state(t, bid)
        recipes = [{"key": rc, "name": gname(rc), "emoji": gemoji(rc), "good": False,
                    "out_qty": prod.grind_output(bid, rc, L), "time": f"{mins} мин",
                    "inputs": _cost_items(p, prod.grind_inputs(bid, rc, L))}
                   for rc, (_i, mins, _o) in prod.GRIND[bid].items()]
        stock = [{"key": rc, "name": gname(rc), "emoji": gemoji(rc), "good": False,
                  "qty": int(inventory.get(p, rc))} for rc in prod.GRIND[bid]]
        out_res = braw.get("out_res")
        out = ({"key": out_res, "name": gname(out_res), "emoji": gemoji(out_res),
                "good": False, "qty": int(braw.get("out_qty", 0))} if state != "none" else None)
        total = prod.grind_minutes(bid, out_res) if out_res in prod.GRIND[bid] else 0
        ends = _ends_epoch(braw.get("ready_at")) if state == "active" else None
        base.update(kind="grind", to="inventory", recipes=recipes, stock=stock,
                    batch={"state": state, "minutes": minutes, "total": total, "ends_at": ends, "out": out})
        return base

    # ── Рецептурные/одиночные (вход → товар в погреб) ─────────────────────
    if bid in prod.RECIPES:                                   # пекарня/коптильня/сыроварня
        rmap = list(prod.RECIPES[bid].keys())
        hours_of = lambda rc: prod.recipe_hours(bid, rc)      # noqa: E731
        recipes = [{"key": rc, "name": gname(rc), "emoji": gemoji(rc), "good": True,
                    "out_qty": prod.recipe_output(bid, rc, L),
                    "time": f"{prod.recipe_hours(bid, rc)} ч",
                    "inputs": _cost_items(p, prod.recipe_inputs(bid, rc, L))} for rc in rmap]
    else:                                                     # кухня/винокурня/медоварня
        single = {"kitchen": (prod.KITCHEN, prod.kitchen_inputs, prod.kitchen_hours, prod.kitchen_output),
                  "winery": (prod.WINERY, prod.winery_inputs, prod.winery_hours, prod.winery_output),
                  "meadery": (prod.MEADERY, prod.meadery_inputs, prod.meadery_hours, prod.meadery_output)}[bid]
        cat, f_in, f_hr, f_out = single
        rmap = list(cat.keys())
        hours_of = f_hr
        recipes = [{"key": rc, "name": gname(rc), "emoji": gemoji(rc), "good": True,
                    "out_qty": f_out(rc, L), "time": f"{f_hr(rc)} ч",
                    "inputs": _cost_items(p, f_in(rc, L))} for rc in rmap]
    state, minutes = prod.state(t, bid)
    rc_now = braw.get("recipe")
    out = ({"key": rc_now, "name": gname(rc_now), "emoji": gemoji(rc_now), "good": True,
            "qty": int(braw.get("out_qty", 0))} if state != "none" and rc_now else None)
    total = hours_of(rc_now) * 60 if rc_now and rc_now in rmap else 0
    stock = [{"key": rc, "name": gname(rc), "emoji": gemoji(rc), "good": True,
              "qty": int((t.products or {}).get(rc, 0))} for rc in rmap]
    flavor = {"meadery": "Берут состоятельные — репутация решает.",
              "kitchen": "Сытые гости платят за еду сверх выпивки.",
              "winery": "Самый дорогой напиток — берут только богачи."}.get(bid)
    ends = _ends_epoch(braw.get("ready_at")) if state == "active" else None
    base.update(kind="recipe", to="cellar", recipes=recipes, stock=stock, flavor=flavor,
                batch={"state": state, "minutes": minutes, "total": total, "ends_at": ends, "out": out})
    return base


async def _api_prod_start(request: web.Request) -> web.Response:
    """Запустить партию (диспатч по зданию). Оплата вперёд, один слот на здание."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import production as prod
    building = str(body.get("building") or "")
    recipe = str(body.get("recipe") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        t = p.tavern
        if building in prod.GRIND:
            ok, reason, _cin = prod.start_grind(p, t, building, recipe)
        elif building in prod.RECIPES:
            ok, reason, _cin = prod.start_recipe(p, t, building, recipe)
        elif building == "meadery":
            ok, reason, _cin = prod.start_meadery(p, t, recipe)
        elif building == "kitchen":
            ok, reason, _cin = prod.start_kitchen(p, t, recipe)
        elif building == "winery":
            ok, reason, _cin = prod.start_winery(p, t, recipe)
        elif building == "brewery":
            try:
                ok, reason, _cin = prod.start_brew(p, t, int(body.get("tier") or 0))
            except (ValueError, TypeError):
                ok, reason = False, "unknown"
        else:
            ok, reason = False, "unknown"
        if not ok:                                            # unknown|busy|not_enough
            return web.json_response({"ok": False, "error": reason})
        repo.add_log(s, "player", p.id, f"⚙ запустил производство: {building}/{recipe}")
        await s.commit()
        st = _production_state(p, building)
    return web.json_response({"ok": True, "production": st},
                             headers={"Cache-Control": "no-store"})


async def _api_brew_age(request: web.Request) -> web.Response:
    """Поставить готовый эль на выдержку (риск +ярус)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import production as prod
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not prod.start_age(p, p.tavern):
            return web.json_response({"ok": False, "error": "cant"})
        await s.commit()
        st = _production_state(p, "brewery")
    return web.json_response({"ok": True, "production": st},
                             headers={"Cache-Control": "no-store"})


async def _api_prod_claim(request: web.Request) -> web.Response:
    """Забрать готовую партию (диспатч по зданию). Возвращает тост + новый стейт."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal, newbie, production as prod
    from bot import texts
    building = str(body.get("building") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        t = p.tavern
        toast = None
        if building in prod.GRIND:
            res = prod.claim_grind(p, t, building)
            if res is None:
                return web.json_response({"ok": False, "error": "not_ready"})
            r, qty = res
            toast = f"{bal.GOODS_EMOJI.get(r, '📦')} +{qty} {bal.GOODS_NAMES.get(r, r)}"
        elif building in prod.RECIPES or building in ("meadery", "kitchen", "winery"):
            claim = {"meadery": prod.claim_meadery, "kitchen": prod.claim_kitchen,
                     "winery": prod.claim_winery}.get(building)
            res = claim(p, t) if claim else prod.claim_recipe(p, t, building)
            if res is None:
                return web.json_response({"ok": False, "error": "not_ready"})
            rc, qty = res
            g = prod.GOODS[rc]
            newbie.mark(p, "nb_craft")
            toast = f"{g.emoji} +{qty} {g.name}"
        elif building == "brewery":
            res = prod.claim_brew(p, t)
            if res is None:
                return web.json_response({"ok": False, "error": "not_ready"})
            outcome, tier, qty = res
            if qty > 0:
                newbie.mark(p, "nb_craft")
            toast = texts.brew_claimed(outcome, tier, qty)
        else:
            return web.json_response({"ok": False, "error": "unknown"})
        repo.add_log(s, "player", p.id, f"📦 забрал производство: {building}")
        await s.commit()
        st = _production_state(p, building)
    return web.json_response({"ok": True, "production": st, "toast": toast},
                             headers={"Cache-Control": "no-store"})


# ===== Охота (порт bot/handlers/hunt.py + game/combat.py) =====

# enemy.id → ключ пака анимированных спрайтов (miniapp/public/monsters/<key>/)
ENEMY_SPRITE = {
    "zayac": "flying_eye", "lisa": "gargoyle", "gadyuka": "medusa",
    "olen": "centaur", "volk": "cerberus", "kaban": "minotaur",
    "vozhak": "skeleton", "medved": "golem", "razboy": "goblin",
    "ataman": "dragon", "lynx": "harpy", "tusker": "satyr", "scorpion": "witch",
    "olen_gold": "centaur", "volk_white": "cerberus", "kaban_rabid": "minotaur",
}


def _drop_items(drops) -> list:
    """Таблица добычи зверя: ресурсы (диапазон/шанс) и трофеи (res='')."""
    from bot.game import balance as bal, production as prod
    names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
    out = []
    for d in drops:
        if d.res:
            g = prod.GOODS.get(d.res)
            out.append({"key": d.res, "trophy": False, "lo": d.lo, "hi": d.hi,
                        "chance": d.chance, "name": g.name if g else names.get(d.res, d.res),
                        "emoji": g.emoji if g else emojis.get(d.res)})
        else:
            out.append({"trophy": True, "label": d.label, "chance": d.chance})
    return out


def _hunt_state(p) -> dict:
    """Меню охоты: HP/реген/готовность, расклад игрока, бестиарий с прогнозом и
    добычей, опции лечения. Прогноз — combat.forecast (все статы, мгновенно)."""
    from bot.game import balance as bal, combat, production as prod
    chp, mhp = combat.current_hp(p), combat.max_hp()
    ready, mins = combat.hunt_ready(p)
    stats = combat.player_stats(p)
    beasts = []
    for e in combat.huntable(getattr(p, "region", None)):
        win, est = combat.forecast(stats, e, chp)
        icon, label = combat.threat(win)
        beasts.append({
            "id": e.id, "emoji": e.emoji, "name": e.name, "hp": e.hp,
            "sprite": ENEMY_SPRITE.get(e.id),
            "attack": e.attack, "armor": e.armor, "gold": [e.gold[0], e.gold[1]],
            "rep": e.rep, "blurb": e.blurb, "traits": list(e.traits),
            "regional": bool(e.region), "win": win, "est_hp": est,
            "threat": {"icon": icon, "label": label}, "drops": _drop_items(e.drops),
        })
    prods = (p.tavern.products if p.tavern else None) or {}
    heal_opts = [{"key": k, "name": prod.GOODS[k].name, "emoji": prod.GOODS[k].emoji,
                  "hp": bal.HEAL_VALUES[k], "qty": int(prods.get(k, 0))}
                 for k in bal.HEAL_VALUES if k in prod.GOODS and int(prods.get(k, 0)) > 0]
    return {
        "ok": True,
        "hp": {"cur": chp, "max": mhp, "regen": combat.regen_full_minutes(p)},
        "ready": {"can": ready, "minutes": mins},
        "stats": {"damage": bal.BASE_DAMAGE + stats.get("damage", 0),
                  "crit": min(bal.HUNT_CRIT_CAP, stats.get("crit", 0)),
                  "armor": stats.get("armor", 0), "luck": stats.get("luck", 0)},
        "heal": {"can": chp < mhp, "full": chp >= mhp, "options": heal_opts},
        "beasts": beasts,
    }


async def _api_hunt(request: web.Request) -> web.Response:
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        st = _hunt_state(p)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_hunt_fight(request: web.Request) -> web.Response:
    """Бой (combat.hunt): гейт по HP, исход + лог раундов для анимации, добыча/раны."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal, combat, production as prod
    eid = str(body.get("id") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        chp0 = combat.current_hp(p)                  # HP на старте — для шкалы анимации
        res = combat.hunt(p, eid)
        if not res.ok:                               # unknown | lowhp
            return web.json_response({"ok": False, "error": res.reason, "minutes": res.minutes_left})
        if res.fight.win:
            repo.add_log(s, "player", p.id, f"🏹 одолел: {res.enemy.name} (+{(res.loot or {}).get('gold', 0)} 🪙)")
        else:
            repo.add_log(s, "player", p.id, f"🩸 проиграл: {res.enemy.name} (−{res.gold_lost} 🪙)")
        await s.commit()
        names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
        emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
        loot_res = []
        if res.fight.win and res.loot:
            for k, q in res.loot["res"].items():
                gd = prod.GOODS.get(k)
                loot_res.append({"key": k, "qty": int(q),
                                 "name": gd.name if gd else names.get(k, k),
                                 "emoji": gd.emoji if gd else emojis.get(k)})
        hunt = _hunt_state(p)
    return web.json_response({
        "ok": True, "win": res.fight.win, "elite": res.elite,
        "enemy": {"name": res.enemy.name, "emoji": res.enemy.emoji, "hp": res.enemy.hp,
                  "sprite": ENEMY_SPRITE.get(res.enemy.id), "traits": list(res.enemy.traits)},
        "player_hp0": chp0, "hp_max": combat.max_hp(), "rounds": res.fight.log,
        "rounds_n": res.fight.rounds, "crits": res.fight.crits, "overwhelmed": res.fight.overwhelmed,
        "loot": {"gold": (res.loot or {}).get("gold", 0) if res.fight.win else 0, "res": loot_res,
                 "trophies": (res.loot or {}).get("trophies", []) if res.fight.win else [],
                 "rep": (res.loot or {}).get("rep", 0) if res.fight.win else 0},
        "gold_lost": res.gold_lost, "hp_now": res.hp_now, "hunt": hunt,
    }, headers={"Cache-Control": "no-store"})


# ===== Ночная ходка (порт bot/game/nightrun.py — соло push-your-luck) =====
# Server-authoritative: ВЕСЬ RNG (бросок Лихо, успех испытаний) — на сервере;
# фронт лишь анимирует к результату (анти-чит, как в охоте).

_NR_KIND = {  # тип испытания → (эмодзи, имя, рисковый?)
    "fight": ("⚔️", "Засада", True), "gamble": ("🎲", "Лихо", True),
    "sneak": ("🌒", "Тишком", True), "meet": ("🗣", "Встреча", False),
    "quiz": ("❓", "Загадка", False), "rest": ("🔥", "Привал", False),
    "find": ("💰", "Схрон", False),
}
_NR_HINT = {
    "fight": "Сила и броня решают. Победа стоит здоровья.",
    "gamble": "Бросок костей: высокая дисперсия — куш или обчистят.",
    "sneak": "Удача — проскользнуть мимо беды.",
    "meet": "Встреча на тракте: выбор и сдвиг сил города. Без бюста.",
    "quiz": "Загадка Ведьмы: угадал — куш. Без бюста.",
    "rest": "Привал у костра: лечит. Добычи нет.",
    "find": "Схрон: малая добыча. Безопасно.",
}


def _nr_items(d: dict | None) -> list:
    """Лут/котомка {gold,res…} → [{key,name,emoji,qty}] (как в охоте)."""
    from bot.game import balance as bal, production as prod
    names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
    out = []
    for k, v in (d or {}).items():
        if not v:
            continue
        g = prod.GOODS.get(k)
        out.append({"key": k, "qty": int(v),
                    "name": "Золото" if k == "gold" else (g.name if g else names.get(k, k)),
                    "emoji": "🪙" if k == "gold" else (g.emoji if g else emojis.get(k))})
    return out


def _nightrun_state(p) -> dict:
    """Состояние ночной ходки: кулдаун / активный забег (этап, HP, котомка, текущий
    под-экран развилки/встречи/загадки). Прогноз успеха — nightrun.success_p."""
    from bot.game import balance as bal, combat, nightrun as nr
    from bot.config import settings
    cd = 0 if p.id == settings.admin_id else nr.cooldown_left(p)   # админ — без кулдауна (тест)
    run = p.night_run or {}
    s = combat.player_stats(p)
    base = {"ok": True, "cooldown": cd, "active": nr.is_active(run),
            "max_legs": bal.NIGHTRUN_LEGS,
            "stats": {"armor": s.get("armor", 0), "luck": s.get("luck", 0)}}
    if not nr.is_active(run):
        base["run"] = None
        return base
    st = run.get("state")
    r = {"leg": run["leg"], "state": st, "hp": run["hp"], "hp_max": bal.BASE_HP,
         "satchel": _nr_items(run.get("satchel")),
         "satchel_value": nr.satchel_value(run.get("satchel")),
         "situation": run.get("situation"), "can_push": nr.can_push(run),
         "rest_heal": bal.NIGHTRUN_REST_HEAL,
         "next_value": round(nr.leg_value(run["leg"] + 1)) if nr.can_push(run) else 0,
         "growth": round(bal.NIGHTRUN_REWARD_GROWTH, 2)}
    if st == "fork":
        _stat = {"fight": "armor", "sneak": "luck"}
        _mult = {"find": 0.6, "quiz": 1.5}

        def _fk(k):
            sp = nr.success_p(run, p, k)
            return {"kind": k, "emoji": _NR_KIND[k][0], "name": _NR_KIND[k][1],
                    "risky": _NR_KIND[k][2], "hint": _NR_HINT[k],
                    "success": round(sp * 100), "risk": round((1 - sp) * 100) if _NR_KIND[k][2] else 0,
                    "reward": round(nr.leg_value(run["leg"]) * _mult.get(k, 1.0)),
                    "stat": _stat.get(k)}
        r["fork"] = [_fk(k) for k in nr.fork(run)]
    elif st == "meet":
        enc = nr.MEET_ENCOUNTERS[run["meet"]]
        r["meet"] = {"npc": enc["npc"], "scene": enc["scene"],
                     "options": [{"id": o[0], "label": o[1]} for o in enc["options"]]}
    elif st == "quiz":
        rd = nr.current_riddle(run)
        r["quiz"] = {"q": rd["q"], "options": list(rd["options"])}   # correct НЕ отдаём
    base["run"] = r
    return base


async def _api_nightrun(request: web.Request) -> web.Response:
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        st = _nightrun_state(p)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_nightrun_start(request: web.Request) -> web.Response:
    """Выйти на тракт: ситуация города красит ночь, кулдаун 4ч с момента старта."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from datetime import datetime, timezone
    from bot.game import city as citymod, nightrun as nr
    from bot.config import settings
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if nr.is_active(p.night_run or {}):
            return web.json_response(_nightrun_state(p), headers={"Cache-Control": "no-store"})
        if nr.cooldown_left(p) > 0 and p.id != settings.admin_id:   # админ — без кулдауна
            return web.json_response({"ok": False, "error": "cooldown"})
        situation = None
        if getattr(p, "chat_id", None) is not None:
            city = await repo.get_or_create_city(s, p.chat_id)
            sit = citymod.current(city)
            situation = sit.id if sit else None
        p.night_run_at = datetime.now(timezone.utc)
        p.night_run = nr.start(p, p.region or "", situation=situation)
        repo.add_log(s, "player", p.id, "🌙 ушёл в ночную ходку")
        await s.commit()
        st = _nightrun_state(p)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


def _nr_out(out: dict) -> dict:
    """Исход испытания для анимации фронта (лут/потеря → предметы)."""
    o = {"kind": out.get("kind"), "busted": bool(out.get("busted")),
         "loot": _nr_items(out.get("loot")), "hp_cost": out.get("hp_cost", 0),
         "healed": out.get("healed", 0), "roll": out.get("roll"),
         "lose_faces": out.get("lose_faces"), "collapsed": bool(out.get("collapsed"))}
    if out.get("lost"):
        o["lost"] = _nr_items(out.get("lost"))
    if "correct" in out:
        o["correct"] = bool(out["correct"])
    if out.get("factions"):
        o["factions"] = [{"faction": f, "delta": d} for f, d in out["factions"]]
        o["npc"] = out.get("npc")
    return o


async def _api_nightrun_pick(request: web.Request) -> web.Response:
    """Выбрать испытание на развилке. gamble — сервер катит кубик."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    import random as _r
    from bot.game import nightrun as nr
    kind = str(body.get("kind") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        run = dict(p.night_run or {})
        if not nr.is_active(run) or run.get("state") != "fork" or kind not in nr.fork(run):
            return web.json_response({"ok": False, "error": "stale"})
        roll = _r.randint(1, 6) if kind == "gamble" else None
        out = nr.attempt(run, p, kind, roll=roll)
        if out.get("busted"):
            p.night_run = {}
            repo.add_log(s, "player", p.id, "🌑 ходка сорвалась")
        else:
            p.night_run = run
        await s.commit()
        resp = {"ok": True, "out": _nr_out(out), "nightrun": _nightrun_state(p)}
    return web.json_response(resp, headers={"Cache-Control": "no-store"})


async def _api_nightrun_meet(request: web.Request) -> web.Response:
    """Выбор у НПС: добыча + сдвиг фракций города."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import nightrun as nr
    opt = str(body.get("opt") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        run = dict(p.night_run or {})
        if run.get("state") != "meet":
            return web.json_response({"ok": False, "error": "stale"})
        out = nr.meet_resolve(run, p, opt)
        if out.get("factions") and getattr(p, "chat_id", None) is not None:
            city = await repo.get_or_create_city(s, p.chat_id, lock=True)
            fp = dict(city.faction_power or {})
            for fac, delta in out["factions"]:
                fp[fac] = fp.get(fac, 0) + delta
            city.faction_power = fp
        p.night_run = run
        await s.commit()
        resp = {"ok": True, "out": _nr_out(out), "nightrun": _nightrun_state(p)}
    return web.json_response(resp, headers={"Cache-Control": "no-store"})


async def _api_nightrun_quiz(request: web.Request) -> web.Response:
    """Ответ на загадку Ведьмы (индекс): верно — куш, мимо — без добычи (без бюста)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import nightrun as nr
    try:
        ans = int(body.get("answer"))
    except (TypeError, ValueError):
        ans = -1
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        run = dict(p.night_run or {})
        if run.get("state") != "quiz":
            return web.json_response({"ok": False, "error": "stale"})
        correct = ans == nr.current_riddle(run)["correct"]
        out = nr.quiz_resolve(run, p, correct)
        p.night_run = run
        await s.commit()
        resp = {"ok": True, "out": _nr_out(out), "nightrun": _nightrun_state(p)}
    return web.json_response(resp, headers={"Cache-Control": "no-store"})


async def _api_nightrun_push(request: web.Request) -> web.Response:
    """Углубиться: следующий этап (новая развилка, опаснее и жирнее)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import nightrun as nr
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        run = dict(p.night_run or {})
        if run.get("state") != "crossroad":
            return web.json_response({"ok": False, "error": "stale"})
        nr.push(run)
        p.night_run = run
        await s.commit()
        st = _nightrun_state(p)
    return web.json_response(st, headers={"Cache-Control": "no-store"})


async def _api_nightrun_bank(request: web.Request) -> web.Response:
    """Свернуть в таверну: вся котомка → инвентарь/золото, забег завершён."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import nightrun as nr
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        run = dict(p.night_run or {})
        if not nr.is_active(run):
            return web.json_response({"ok": False, "error": "stale"})
        banked = nr.bank(run, p)
        p.night_run = {}
        repo.add_log(s, "player", p.id, f"🏠 вернулся с ходки (+{nr.satchel_value(banked)}🪙-экв)")
        await s.commit()
        st = _nightrun_state(p)
    return web.json_response({"ok": True, "banked": _nr_items(banked),
                              "value": nr.satchel_value(banked), "nightrun": st},
                             headers={"Cache-Control": "no-store"})


def _init_user(init_data: str) -> dict:
    """Имя/username из (уже проверенного) initData — для создания игрока в онбординге."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        u = json.loads(pairs.get("user", "{}"))
        return {"first_name": u.get("first_name"), "username": u.get("username")}
    except (ValueError, TypeError):
        return {}


async def _api_onboard(request: web.Request) -> web.Response:
    """Создать игрока (если нет) и таверну — порт cmd_start/cb_create_tavern:
    слот на карте, стартовый сундук, активация зазыва. Идемпотентно."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import newbie
    from bot.game.balance import REGIONS
    name = str(body.get("name") or "").strip()
    region = str(body.get("region") or "")
    if not 2 <= len(name) <= 40:
        return web.json_response({"ok": False, "error": "bad_name"})
    if region not in REGIONS:
        return web.json_response({"ok": False, "error": "bad_region"})
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None:
            u = _init_user(body.get("initData") or "")
            p = await repo.create_player(s, uid, u.get("username"), u.get("first_name") or "Хозяин")
        if p.tavern is not None:                       # уже есть — отдаём состояние
            return web.json_response({"ok": True, "state": _tavern_state(p, p.tavern)})
        t = await repo.create_tavern(s, p, name, region)
        await repo.assign_map_slot(s, t, region)
        repo.add_log(s, "player", p.id, f"🏗 завёл таверну «{name}» в {REGIONS[region]}")
        chest = newbie.grant_chest(p)                  # стартовый сундук новосёла
        await repo.grant_referral_rewards(s, p)        # активировать зазыв (если был)
        await s.commit()
        st = _tavern_state(p, t)
    return web.json_response({"ok": True, "state": st, "chest": chest},
                             headers={"Cache-Control": "no-store"})


async def _map_page(request: web.Request) -> web.Response:
    return web.Response(text=_MAP_HTML, content_type="text/html")


async def _world_png(request: web.Request) -> web.Response:
    return web.FileResponse(worldmap.MAP_FILE)


# ── Новый мир-атлас: тайловая Leaflet-карта (огромный бесшовный мир из 25 континентов) ──
_WORLD_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=PT+Serif:wght@700&display=swap">
<title>Мир Недоливска</title>
<style>
:root{--serif:'PT Serif',Georgia,'Times New Roman',serif}
html,body{margin:0;height:100%;background:#0f1828;overflow:hidden;font-family:system-ui,sans-serif}
#map{height:100%}.leaflet-container{background:#0f1828;font-family:inherit}
/* кинематографичное обрамление: виньетка по краям + тёплый световой грейд (статично, без blur) */
#frame{position:fixed;inset:0;z-index:480;pointer-events:none;transform:translateZ(0);
  box-shadow:inset 0 0 110px 26px rgba(5,8,16,.82),inset 0 0 280px 70px rgba(5,8,16,.34);
  background:radial-gradient(125% 95% at 50% 40%,rgba(255,208,128,.05),rgba(8,12,24,0) 46%,rgba(5,8,16,.34) 100%)}
.leaflet-control-zoom{margin-bottom:16px!important;margin-right:12px!important;border:none!important}
.leaflet-control-zoom a{background:rgba(16,22,38,.85)!important;color:#f3dca0!important;
  border:1px solid #4a3a1e!important;width:34px!important;height:34px!important;line-height:32px!important}
/* шапка-баннер */
#hud{position:fixed;left:0;right:0;top:0;z-index:1000;display:flex;align-items:center;gap:8px;
  padding:calc(env(safe-area-inset-top,0px) + 9px) 12px 12px;pointer-events:none;
  background:linear-gradient(180deg,rgba(7,10,20,.95),rgba(7,10,20,.5) 62%,rgba(7,10,20,0))}
#title{font-family:var(--serif);font-weight:700;font-size:16px;color:#f3dca0;text-shadow:0 1px 5px #000;
  flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#title b{color:#ffd57a}#cnt{color:#c0a26a;font-weight:400;font-size:13px}
#mine{pointer-events:auto;flex:none;white-space:nowrap;border:1px solid #c79a44;border-radius:999px;
  padding:6px 14px;font-weight:700;font-size:13px;color:#241405;cursor:pointer;font-family:var(--serif);
  background:linear-gradient(180deg,#ffe09a,#dca03c);box-shadow:0 2px 9px rgba(220,160,40,.45),inset 0 1px 0 rgba(255,255,220,.5)}
/* баннер рейда */
#raidbar{position:fixed;left:8px;right:8px;top:calc(env(safe-area-inset-top,0px) + 48px);z-index:1000;
  display:none;align-items:center;gap:9px;padding:9px 13px;border-radius:14px;cursor:pointer;font-family:var(--serif);
  color:#fff;font-weight:700;font-size:14px;background:linear-gradient(180deg,#d23a18,#9a2a10);
  border:1px solid #ff7a4a;box-shadow:0 4px 16px rgba(210,58,24,.5);animation:rb 1.6s ease-in-out infinite}
@keyframes rb{0%,100%{box-shadow:0 4px 16px rgba(210,58,24,.45)}50%{box-shadow:0 4px 26px rgba(255,90,50,.8)}}
#raidbar .go{margin-left:auto;opacity:.85}
/* подписи континентов — картуш с иконкой биома */
.cont-label{width:210px!important;display:flex;align-items:center;justify-content:center;pointer-events:none}
.cl-plate{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-family:var(--serif);
  font-weight:700;font-size:13.5px;letter-spacing:.01em;color:#f4e3bd;padding:3px 12px;border-radius:999px;
  background:rgba(10,14,26,.6);border:1px solid rgba(198,162,92,.5);
  box-shadow:0 2px 10px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,228,170,.1);text-shadow:0 1px 2px #000}
.cl-plate .ci{font-size:12px;opacity:.95}
/* подпись таверны (на близком зуме) */
.leaflet-tooltip.tav-label{background:rgba(10,14,24,.85);border:1px solid #6b522e;color:#f3dca0;
  font-family:var(--serif);font-weight:700;font-size:11px;border-radius:7px;padding:1px 7px;
  box-shadow:0 1px 6px rgba(0,0,0,.5);opacity:0;transition:opacity .18s}
.leaflet-tooltip.tav-label::before{display:none}
/* пин таверны: спрайт-здание + тень на земле + бейдж уровня */
.tav-pin .sh{position:absolute;left:50%;bottom:1px;width:60%;height:13%;transform:translateX(-50%);
  background:radial-gradient(ellipse,rgba(0,0,0,.5),rgba(0,0,0,0) 70%);border-radius:50%}
.tav-pin img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
  filter:drop-shadow(0 2px 3px rgba(0,0,0,.55))}
.tav-pin .lv{position:absolute;top:-3px;right:-3px;min-width:15px;height:15px;padding:0 3px;box-sizing:border-box;
  display:flex;align-items:center;justify-content:center;border-radius:999px;font:700 10px/1 var(--serif);
  color:#241405;background:linear-gradient(180deg,#ffe09a,#d99a36);border:1px solid #8a6a22;
  box-shadow:0 1px 3px rgba(0,0,0,.5)}
.tav-pin.mine img{filter:drop-shadow(0 0 8px #ffd27a) drop-shadow(0 2px 3px rgba(0,0,0,.6))}
.tav-pin.mine .lv{background:linear-gradient(180deg,#fff0c0,#f0b840)}
/* карточка таверны */
.tav-pop{font-family:var(--serif);font-weight:400;font-size:13px;line-height:1.5;color:#e9dcc2;min-width:178px}
.tav-pop .h{font-weight:700;font-size:15px;color:#ffcf6a;margin-bottom:1px}
.tav-pop .o{color:#bfa775;font-size:12px;margin-bottom:6px}
.tav-pop .loc{color:#8fb0d8;font-size:12px}
.tav-pop .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:5px;font-size:12px;color:#d8c8a6}
.tav-pop .mine{margin-top:7px;color:#ffd27a;font-weight:700}
.leaflet-popup-content-wrapper{background:#1a140c;border:1px solid #6b522e;border-radius:12px}
.leaflet-popup-tip{background:#1a140c}
/* кластер — золотая монета */
.tcl{display:flex;align-items:center;justify-content:center;border-radius:50%;
  background:radial-gradient(circle at 38% 30%,#3c2d15,#1a120a);color:#ffd98a;font:700 13px var(--serif);
  border:2px solid #c9a14e;box-shadow:0 2px 9px rgba(0,0,0,.55),inset 0 0 0 1px rgba(255,220,150,.22),0 0 13px -3px rgba(255,190,90,.55)}
/* лоадер */
#loader{position:fixed;inset:0;z-index:1500;display:flex;align-items:center;justify-content:center;
  background:#0f1828;color:#caa86a;font-weight:700;font-size:15px;transition:opacity .4s}
#loader.hide{opacity:0;pointer-events:none}
</style></head>
<body>
<div id="map"></div>
<div id="frame"></div>
<div id="hud"><div id="title">🗺 <b>Мир Недоливска</b> <span id="cnt"></span></div>
  <button id="mine">🏰 Моя таверна</button></div>
<div id="raidbar"></div>
<div id="loader">Разворачиваем карту мира…</div>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
var tg=window.Telegram&&Telegram.WebApp;
if(tg){tg.ready();tg.expand();try{tg.setHeaderColor&&tg.setHeaderColor('#0f1828');}catch(e){}}
var W=11020,H=11020,TILE=256,MAXZ=6;
var map=L.map('map',{crs:L.CRS.Simple,maxZoom:MAXZ+1,attributionControl:false,zoomControl:false,
  zoomSnap:0,zoomDelta:.6,wheelPxPerZoomLevel:90,inertia:true});
L.control.zoom({position:'bottomright'}).addTo(map);
function px(x,y){return map.unproject([x,y],MAXZ);}
var bounds=L.latLngBounds(px(0,H),px(W,0));
L.tileLayer('/world/tiles/{z}/{x}/{y}.jpg',{tileSize:TILE,noWrap:true,bounds:bounds,
  maxNativeZoom:MAXZ,maxZoom:MAXZ+1,keepBuffer:4}).addTo(map);
// стартовый валидный вид сразу (на случай, если cover-расчёт задержится в WebView)
map.setView(px(W/2,H/2),2);
map.setMaxBounds(bounds.pad(0.04));
// «Cover»: мир ЗАПОЛНЯЕТ экран (без чёрных полей). minZoom = зум покрытия, старт по центру.
// В WebView/iframe контейнер на whenReady часто ещё нулевой высоты → getSize()=0 →
// log2(0)=-Infinity ломает карту. Поэтому пересчитываем размер и ждём, пока разложится.
function fit(){
  map.invalidateSize(false);
  var s=map.getSize();
  if(!s||s.x<40||s.y<40){setTimeout(fit,100);return;}
  var cz=MAXZ+Math.log2(Math.max(s.x,s.y)/W*1.02);
  if(!isFinite(cz)){cz=2;}
  map.setMinZoom(cz);
  if(!map._c){map.setView(px(W/2,H/2),cz,{animate:false});map._c=true;}
}
map.whenReady(fit);window.addEventListener('load',fit);
setTimeout(fit,350);setTimeout(fit,1200);
window.addEventListener('resize',function(){map._c=false;fit();});
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
var uid=(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user&&tg.initDataUnsafe.user.id)||parseInt(new URLSearchParams(location.search).get('uid')||'0',10)||0;
// ── подписи континентов (видны на дальнем зуме) ──
var contLayer=L.layerGroup();
var BICON={snow:'❄',green:'🌿',desert:'☀'};
fetch('/world/slots.json').then(function(r){return r.json();}).then(function(cs){
  cs.forEach(function(c){
    var bi=BICON[c.biome]||'•';
    L.marker(px(c.x*W,c.y*H),{interactive:false,keyboard:false,
      icon:L.divIcon({className:'cont-label',iconSize:[210,24],iconAnchor:[105,28],
        html:'<span class="cl-plate"><span class="ci">'+bi+'</span>'+esc(c.name)+'</span>'})}).addTo(contLayer);
  });
  queueRelayout();
}).catch(function(){});
// ── Коллайдер подписей (механика антикаши): имена таверн рисуются по приоритету
//    (своя > уровень+реп); налезающие на монеты/пины/друг друга — плавно прячутся.
//    Континенты — на дальнем зуме. Пересчёт на zoomend/moveend и сменах кластеров.
var mapEl=document.getElementById('map');
function _box(el,pad){var r=el.getBoundingClientRect();if(!r.width)return null;var m=mapEl.getBoundingClientRect();
  pad=pad||0;return {x0:r.left-m.left-pad,y0:r.top-m.top-pad,x1:r.right-m.left+pad,y1:r.bottom-m.top+pad};}
function _hit(a,b){return a.x0<b.x1&&a.x1>b.x0&&a.y0<b.y1&&a.y1>b.y0;}
var _rq=false;
function relayout(){_rq=false;var z=map.getZoom(),i;
  if(z<=3){if(!map.hasLayer(contLayer))contLayer.addTo(map);}
  else{if(map.hasLayer(contLayer))map.removeLayer(contLayer);}
  var showNames=z>=3.6,occ=[],cand=[];
  if(showNames){var blk=document.querySelectorAll('.tcl');  // резервируем монеты (не пины: имя над своим пином)
    for(i=0;i<blk.length;i++){var bb=_box(blk[i],1);if(bb)occ.push(bb);}}
  tavMarkers.forEach(function(o){var tt=o.m.getTooltip&&o.m.getTooltip();var el=tt&&tt.getElement&&tt.getElement();
    if(!el)return;o._el=el;
    if(!showNames){el.style.opacity=o.mine?1:0;return;}
    cand.push(o);});
  if(showNames){cand.sort(function(a,b){return b.prio-a.prio;});
    cand.forEach(function(o){var b=_box(o._el,2);if(!b){o._el.style.opacity=0;return;}
      var ok=true;for(var i=0;i<occ.length;i++){if(_hit(b,occ[i])){ok=false;break;}}
      if(ok||o.mine){o._el.style.opacity=1;occ.push(b);}else{o._el.style.opacity=0;}});}
}
function queueRelayout(){if(_rq)return;_rq=true;requestAnimationFrame(relayout);}
map.on('zoomend moveend',queueRelayout);
// ── таверны ──
var cluster=L.markerClusterGroup?L.markerClusterGroup({maxClusterRadius:function(z){return z<=2?120:z<=3?92:z<=4?64:46;},showCoverageOnHover:false,
  disableClusteringAtZoom:MAXZ,iconCreateFunction:function(c){var n=c.getChildCount();var d=30+Math.min(22,n);
    return L.divIcon({html:'<div class="tcl" style="width:'+d+'px;height:'+d+'px">'+n+'</div>',className:'',iconSize:[d,d],iconAnchor:[d/2,d/2-8]});}}):null;
var layer=cluster||map;var myLL=null;var myMarker=null;var tavMarkers=[];
function card(t){
  return '<div class="tav-pop"><div class="h">🏰 '+esc(t.name)+'</div>'+
    '<div class="o">хозяин: '+esc(t.owner)+'</div>'+
    '<div class="loc">📍 '+esc(t.continent)+'</div>'+
    '<div class="row"><span>⚜️ ур. '+t.level+'</span><span>⭐ реп. '+t.rep+'</span>'+
    '<span>👥 '+t.cap+'</span><span>☕ уют '+t.comfort+'</span><span>🏛 '+t.builds+'</span></div>'+
    (t.mine?'<div class="mine">★ твоя таверна</div>':'')+'</div>';
}
fetch('/world/taverns.json?uid='+uid).then(function(r){return r.json();}).then(function(d){
  var tv=d.taverns||[];
  document.getElementById('cnt').textContent='· '+(d.total||tv.length)+' таверн';
  tv.forEach(function(t){
    var sz=t.mine?56:42;var ll=px(t.x*W,t.y*H);
    var icon=L.divIcon({className:'tav-pin'+(t.mine?' mine':''),iconSize:[sz,sz],
      iconAnchor:[sz/2,sz*0.9],popupAnchor:[0,-sz*0.82],
      html:'<div class="sh"></div><img src="/assets/map_tavern_'+t.tier+'.png" alt=""><div class="lv">'+t.level+'</div>'});
    var m=L.marker(ll,{icon:icon,zIndexOffset:t.mine?1000:0}).addTo(layer).bindPopup(card(t));
    m.bindTooltip(esc(t.name),{permanent:true,direction:'top',className:'tav-label'+(t.mine?' tl-mine':''),offset:[0,-sz*0.78]});
    tavMarkers.push({m:m,mine:!!t.mine,prio:t.mine?1e9:(t.level*1000+(t.rep||0))});
    if(t.mine){myLL=ll;myMarker=m;}
  });
  if(cluster){map.addLayer(cluster);cluster.on('animationend',queueRelayout);}
  queueRelayout();setTimeout(queueRelayout,300);
  // баннер рейда
  if(d.raid){var rb=document.getElementById('raidbar');
    rb.innerHTML=d.raid.emoji+' <span>'+esc(d.raid.name)+' — '+(d.raid.status==='gathering'?'идёт сбор!':'В БОЙ!')+'</span><span class="go">играть ›</span>';
    rb.style.display='flex';rb.onclick=function(){(window.top||window).location.href='/app/?startapp=raid';};}
  // кнопка «моя таверна»
  var mb=document.getElementById('mine');
  if(myMarker){mb.onclick=function(){
    if(cluster&&cluster.zoomToShowLayer){cluster.zoomToShowLayer(myMarker,function(){myMarker.openPopup();});}
    else{map.flyTo(myLL,MAXZ-1,{duration:.8});setTimeout(function(){myMarker.openPopup();},850);}};}
  else{mb.style.display='none';}
  document.getElementById('loader').classList.add('hide');
}).catch(function(){document.getElementById('loader').textContent='Карта не загрузилась — обнови';});
</script></body></html>"""


async def _world_page(request: web.Request) -> web.Response:
    return web.Response(text=_WORLD_HTML, content_type="text/html")


# Названия 25 континентов по биому (порядок = снег ×5 → зелень ×14 → пустыни ×6).
CONTINENT_NAMES = [
    "Ледяные Пределы", "Морозный Кряж", "Стылые Фьорды", "Белое Безмолвие", "Снежный Зарубеж",
    "Зелёные Долы", "Хмельные Луга", "Дубравный Край", "Речные Земли", "Изумрудная Чаща",
    "Медовые Поля", "Грибная Лощина", "Светлая Пуща", "Холмогорье", "Тихие Поймы",
    "Вересковый Дол", "Заливные Луга", "Старолесье", "Травяной Простор",
    "Выжженные Земли", "Красные Пустоши", "Солончак", "Пыльный Предел", "Багровые Дюны", "Сухой Кряж",
]
_WORLD_CONT: list[dict] | None = None


def _world_continents() -> list[dict]:
    """25 континентов: индекс, центр (норм.), биом, ИМЯ. Кэш из world25_slots.json."""
    global _WORLD_CONT
    if _WORLD_CONT is None:
        p = worldmap.MAP_FILE.parent / "world25_slots.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:   # noqa: BLE001
            data = []
        _WORLD_CONT = [
            {"i": i, "x": c[1], "y": c[2], "biome": c[3] if len(c) > 3 else "",
             "name": CONTINENT_NAMES[i] if i < len(CONTINENT_NAMES) else f"Земля {c[0]}"}
            for i, c in enumerate(data)
        ]
    return _WORLD_CONT or [{"i": 0, "x": 0.5, "y": 0.5, "biome": "", "name": "Недоливск"}]


async def _world_slots(request: web.Request) -> web.Response:
    """Континенты с именами/биомом — для подписей на карте."""
    return web.json_response(_world_continents(), headers={"Cache-Control": "public, max-age=3600"})


async def _world_taverns(request: web.Request) -> web.Response:
    """Таверны на мире-атласе с ПОЛНОЙ инфой (имя/владелец/уровень/репутация/вместимость/
    уют/пристройки/континент). Позиция ВЫЧИСЛЯЕТСЯ на лету (игрок→континент pid%25, внутри —
    слот спиралью-подсолнухом) — без миграции БД и правки игровых регионов. + активный рейд."""
    import math
    try:
        uid = int(request.query.get("uid", "0"))
    except ValueError:
        uid = 0
    conts = _world_continents()
    nc = len(conts)
    async with session_factory() as s:
        rows = await repo.get_map_taverns(s)
        boss = await repo.get_active_raid(s)
    # Позиция СТАБИЛЬНА (не зависит от явки соседей — раньше спираль шла по индексу
    # сортировки и таверны «прыгали» при появлении нового игрока на континенте). Берём
    # её прямо из ХЭША id игрока, полярно и равномерно по площади диска вокруг центра
    # континента — без наложений (непрерывно, а не по сетке слотов).
    R = 0.095
    out = []
    for tav, pl in rows:
        c = conts[pl.id % nc]
        h1 = (pl.id * 2654435761) & 0xFFFFFFFF
        h2 = (pl.id * 40503 + 0x9E3779B1) & 0xFFFFFFFF
        a = (h1 / 4294967296.0) * 6.2831853                  # угол
        rr = R * math.sqrt(h2 / 4294967296.0)                # радиус (равномерно по площади)
        x = min(0.997, max(0.003, c["x"] + rr * math.cos(a)))
        y = min(0.997, max(0.003, c["y"] + rr * math.sin(a)))
        out.append({
            # income/доход НЕ отдаём: mine определяется по ?uid (подделываемому на публичном
            # /world), иначе утекал бы чужой доход. Прочие поля — публичные игровые статы.
            "x": round(x, 4), "y": round(y, 4),
            "name": tav.name or "Таверна", "owner": pl.first_name or "Кабатчик",
            "level": tav.level, "tier": worldmap.sprite_tier(tav.level),
            "rep": tav.reputation, "cap": tav.capacity, "comfort": tav.comfort,
            "builds": len(tav.buildings or []), "continent": c["name"],
            "mine": bool(uid) and pl.id == uid,
        })
    raid = None
    if boss is not None and boss.status in ("gathering", "active"):
        from bot.game import raid as rd
        spec = rd.BOSSES.get(boss.boss_key)
        if spec is not None:
            raid = {"name": spec.name, "emoji": spec.emoji, "status": boss.status}
    return web.json_response({"taverns": out, "raid": raid, "total": len(out)},
                             headers={"Cache-Control": "no-store"})


async def _world_tile(request: web.Request) -> web.Response:
    """Тайл пирамиды мира {z}/{x}/{y}.jpg (статика из world_tiles, сгенерён в Docker)."""
    try:
        z = int(request.match_info["z"]); x = int(request.match_info["x"]); y = int(request.match_info["y"])
    except (ValueError, KeyError):
        return web.Response(status=404)
    p = WORLD_TILES / str(z) / str(x) / f"{y}.jpg"
    if not p.is_file():
        return web.Response(status=404)
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=604800"})


async def _api_whoami(request: web.Request) -> web.Response:
    """Кто я: флаг админа (для гейта вкладки «Карта» в мини-аппе). Auth — initData."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    return web.json_response({"ok": True, "admin": _is_admin(uid)},
                             headers={"Cache-Control": "no-store"})


_SPRITE_CACHE: dict[int, bytes] = {}


def _trimmed_sprite_png(n: int) -> bytes | None:
    # Обрезаем по альфе (как статичная карта в _load_sprite), чтобы низ картинки
    # совпадал с основанием здания — иначе прозрачные поля снизу «подвешивают»
    # таверну над землёй. Результат кешируем в памяти процесса.
    if n in _SPRITE_CACHE:
        return _SPRITE_CACHE[n]
    img = worldmap._load_sprite(n)   # PIL.Image, уже crop по bbox; None если нет файла
    if img is None:
        return None
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    _SPRITE_CACHE[n] = buf.getvalue()
    return _SPRITE_CACHE[n]


async def _tavern_sprite(request: web.Request) -> web.Response:
    # Спрайты-здания таверн по уровню (1..9) для 2.5D-диорамы. Только эти файлы —
    # не вся папка assets (там бывают служебные картинки).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    if not 1 <= n <= 9:
        raise web.HTTPNotFound()
    body = _trimmed_sprite_png(n)
    if body is None:
        raise web.HTTPNotFound()
    return web.Response(body=body, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


_EVENT_ANIMS = {"idle", "hurt", "die", "attack", "walk", "run"}


async def _event_sprite(request: web.Request) -> web.Response:
    # Стрип-анимация орка-ивента: ork{n}_{anim}.png — 10 кадров в ряд (AnimatedSprite).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    anim = request.match_info.get("anim", "idle")
    if not (1 <= n <= 3) or anim not in _EVENT_ANIMS:
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "boss" / f"ork{n}_{anim}.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _hero_sprite(request: web.Request) -> web.Response:
    # Стрип-анимация героя-воина (1..3): hero{n}_{anim}.png — войска из таверн.
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    anim = request.match_info.get("anim", "walk")
    if not (1 <= n <= 6) or anim not in _EVENT_ANIMS:
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "heroes" / f"hero{n}_{anim}.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _fx_sprite(request: web.Request) -> web.Response:
    # Стрип-эффект удара/взрыва: fire{n}.png — квадратные кадры (one-shot VFX).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "fx" / f"fire{n}.png"
    if not (1 <= n <= 10) or not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _spa(request: web.Request) -> web.Response:
    """Отдача React-мини-аппа под /app с SPA-fallback: реальный файл из dist
    (assets/gothic.otf/…) — отдаём, иначе любой путь → index.html (клиент-роутинг)."""
    if not MINIAPP_DIST.is_dir():
        return web.Response(text="mini-app не собран", status=503)
    tail = request.match_info.get("tail", "")
    target = (MINIAPP_DIST / tail).resolve()
    # защита от выхода за пределы dist + отдаём только существующие файлы
    if tail and target.is_file() and str(target).startswith(str(MINIAPP_DIST.resolve())):
        cache = "no-store" if target.name == "index.html" else "public, max-age=86400"
        return web.FileResponse(target, headers={"Cache-Control": cache})
    return web.FileResponse(MINIAPP_DIST / "index.html", headers={"Cache-Control": "no-store"})


@web.middleware
async def _api_errors(request: web.Request, handler):
    """Никаких немых 500 на /api: логируем трейсбек и возвращаем суть ошибки,
    чтобы клиент показал её (а не общее «Не вышло»)."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        import logging, traceback
        logging.error("API ERROR %s\n%s", request.path, traceback.format_exc())
        if request.path.startswith("/api/"):
            return web.json_response(
                {"ok": False, "error": f"x:{type(e).__name__}:{str(e)[:140]}"},
                headers={"Cache-Control": "no-store"})
        raise


def build_app() -> web.Application:
    app = web.Application(middlewares=[_api_errors])
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/map", _map_page)
    app.router.add_get("/world", _world_page)                 # тайловый мир-атлас (Leaflet)
    app.router.add_get("/world/slots.json", _world_slots)
    app.router.add_get("/world/taverns.json", _world_taverns)
    app.router.add_get("/world/tiles/{z}/{x}/{y}.jpg", _world_tile)
    app.router.add_get("/app", _spa)                  # React-мини-апп (каркас игры)
    app.router.add_get("/app/{tail:.*}", _spa)        # SPA-fallback + статика dist
    app.router.add_get("/api/taverns", _api_taverns)
    app.router.add_post("/api/invasion/join", _api_invasion_join)
    app.router.add_post("/api/whoami", _api_whoami)          # флаг админа (гейт вкладки «Карта»)
    app.router.add_post("/api/raid", _api_raid)              # рейд-босс: состояние
    app.router.add_post("/api/raid/join", _api_raid_join)    # записаться (сбор)
    app.router.add_post("/api/raid/hit", _api_raid_hit)      # удар по боссу (битва)
    app.router.add_post("/api/raid/seed", _api_raid_seed)    # ТЕСТ(админ): призвать+в бой
    app.router.add_post("/api/raid/summon", _api_raid_summon)  # АДМИН: настоящий призыв (сбор+рассылка)
    app.router.add_post("/api/mill/run", _api_mill_run)        # вылазка телеги за зерном
    app.router.add_post("/api/mill/collect", _api_mill_collect)
    app.router.add_post("/api/state", _api_state)        # снапшот Таверны (mini-app)
    app.router.add_post("/api/collect", _api_collect)    # собрать доход
    app.router.add_post("/api/trade", _api_trade)        # торг с заезжим купцом
    app.router.add_post("/api/upgrade", _api_upgrade)    # улучшить таверну
    app.router.add_post("/api/bonus", _api_bonus)        # активировать бонус дня
    app.router.add_post("/api/newbie", _api_newbie)      # забрать грамоту новосёла
    app.router.add_post("/api/expedition", _api_expedition)  # забрать добычу бригад
    app.router.add_post("/api/expedition_start", _api_expedition_start)  # отправить бригаду
    app.router.add_post("/api/retail_sell", _api_retail_sell)  # налить гостям (продать заказ)
    app.router.add_post("/api/retail_hold", _api_retail_hold)  # придержать товар
    app.router.add_post("/api/character", _api_character)  # персонаж: статы/снаряга/кузница
    app.router.add_post("/api/forge", _api_forge)        # список кузницы
    app.router.add_post("/api/forge_make", _api_forge_make)  # заказать ковку
    app.router.add_post("/api/craft_claim", _api_craft_claim)  # забрать готовую вещь
    app.router.add_post("/api/heal", _api_heal)          # подлечиться (еда из погреба)
    app.router.add_post("/api/buildings", _api_buildings)    # список пристроек
    app.router.add_post("/api/building", _api_building)       # деталь/производство здания
    app.router.add_post("/api/build_start", _api_build_start)  # заложить пристройку
    app.router.add_post("/api/prod_start", _api_prod_start)   # запустить партию
    app.router.add_post("/api/brew_age", _api_brew_age)       # выдержка эля (риск)
    app.router.add_post("/api/prod_claim", _api_prod_claim)   # забрать партию
    app.router.add_post("/api/hunt", _api_hunt)               # меню охоты (бестиарий+прогноз)
    app.router.add_post("/api/hunt_fight", _api_hunt_fight)   # бой со зверем
    app.router.add_post("/api/nightrun", _api_nightrun)            # ночная ходка: стейт
    app.router.add_post("/api/nightrun/start", _api_nightrun_start)  # выйти на тракт
    app.router.add_post("/api/nightrun/pick", _api_nightrun_pick)    # выбрать испытание
    app.router.add_post("/api/nightrun/meet", _api_nightrun_meet)    # выбор у НПС
    app.router.add_post("/api/nightrun/quiz", _api_nightrun_quiz)    # ответ на загадку
    app.router.add_post("/api/nightrun/push", _api_nightrun_push)    # глубже
    app.router.add_post("/api/nightrun/bank", _api_nightrun_bank)    # свернуть (банк)
    app.router.add_post("/api/story_choice", _api_story_choice)  # резолв выбора у визитёра
    app.router.add_post("/api/chronicle", _api_chronicle)        # летопись города
    app.router.add_post("/api/reputation", _api_reputation)      # репутация у фракций/NPC
    app.router.add_post("/api/torg", _api_torg)                  # вкладка Торг (скупщик), гейт
    app.router.add_post("/api/torg/buy", _api_torg_buy)          # купить сырьё у скупщика
    app.router.add_post("/api/auction", _api_auction)            # аукцион: стейт (лот/форма)
    app.router.add_post("/api/auction/create", _api_auction_create)  # выставить лот
    app.router.add_post("/api/auction/cancel", _api_auction_cancel)  # снять лот
    app.router.add_post("/api/auction/seen", _api_auction_seen)      # погасить финал-экран
    app.router.add_post("/api/auction/seed", _api_auction_seed)          # ТЕСТ(админ): подбросить ставки
    app.router.add_post("/api/auction/settle_now", _api_auction_settle_now)  # ТЕСТ(админ): закрыть сейчас
    app.router.add_post("/api/bourse", _api_bourse)                      # Биржа: доска
    app.router.add_post("/api/bourse/act", _api_bourse_act)              # Биржа: сделки (фаза 2)
    app.router.add_post("/api/referral", _api_referral)          # зазывала (рефералка)
    app.router.add_post("/api/panel", _api_panel)        # данные bottom-sheet панели
    app.router.add_post("/api/onboard", _api_onboard)    # создать игрока+таверну (онбординг)
    app.router.add_get("/assets/world.png", _world_png)   # земля диорамы
    app.router.add_get("/assets/map_tavern_{n}.png", _tavern_sprite)  # здания
    app.router.add_get("/assets/boss/ork{n}_{anim}.png", _event_sprite)  # ивент-анимации
    app.router.add_get("/assets/heroes/hero{n}_{anim}.png", _hero_sprite)  # войска-герои
    app.router.add_get("/assets/fx/fire{n}.png", _fx_sprite)  # эффекты ударов
    app.router.add_get("/assets/hud/squad_globe.png", _hud_globe)  # сфера HP дружины
    app.router.add_get("/assets/audio/festival.mp3", _audio_track)  # фоновая музыка карты
    app.router.add_get("/assets/animals/{name}.png", _animal_sprite)  # бродячая живность
    app.router.add_get("/assets/farm/{name}.png", _farm_sprite)  # ферма (мельница) на карте
    app.router.add_get("/phasertest", _phaser_page)              # ТЕСТ движка Phaser (сцена)
    return app


async def _phaser_page(request: web.Request) -> web.Response:
    return web.Response(text=_PHASER_HTML, content_type="text/html")


_FARM = {"mill", "miller_sowing", "bed1", "bed2", "bed3", "fence1", "fence2", "cart",
         "rye1", "rye2", "cabbage1", "cabbage2", "pumpkin1", "pumpkin2",
         "tomato1", "tomato2", "carrot1", "carrot2"}


async def _farm_sprite(request: web.Request) -> web.Response:
    name = request.match_info.get("name", "")
    if name not in _FARM:
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "farm" / f"{name}.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


_ANIMALS = {"horse", "foal", "goat", "goatling", "goose", "gosling", "rabbit", "rabbit_cub"}


async def _animal_sprite(request: web.Request) -> web.Response:
    name = request.match_info.get("name", "")
    if name not in _ANIMALS:
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "animals" / f"{name}.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _hud_globe(request: web.Request) -> web.Response:
    p = ASSETS_DIR / "hud" / "squad_globe.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _audio_track(request: web.Request) -> web.Response:
    p = ASSETS_DIR / "audio" / "festival.mp3"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def run_webapp(port: int, bot=None) -> web.AppRunner:
    """Запустить веб-сервер карты (вызывается из main параллельно с поллингом).
    bot — тот же aiogram-Bot (один event-loop): нужен, чтобы мини-апп-эндпоинты
    могли слать в чаты (напр. админский призыв рейд-босса)."""
    global _BOT
    _BOT = bot
    runner = web.AppRunner(build_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner


_PHASER_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.jsdelivr.net/npm/phaser@3.80.1/dist/phaser.min.js"></script>
<title>Phaser-тест</title>
<style>html,body{margin:0;height:100%;background:#15100a;overflow:hidden;
  overscroll-behavior:none;touch-action:none}</style></head>
<body>
<script>
  const tg=window.Telegram?.WebApp;
  if(tg){tg.ready();tg.expand(); try{tg.disableVerticalSwipes&&tg.disableVerticalSwipes();}catch(e){}
    try{tg.setHeaderColor&&tg.setHeaderColor('#15100a');}catch(e){}}

  function preload(){
    this.load.spritesheet('walk','/assets/heroes/hero1_walk.png',{frameWidth:112,frameHeight:140});
  }
  function drawBackdrop(s){
    const w=s.scale.width, h=s.scale.height, top=h*0.40;
    s.bg.clear();
    s.bg.fillStyle(0x1b2433,1).fillRect(0,0,w,top);             // небо
    s.bg.fillStyle(0x2e2114,1).fillRect(0,top,w,h-top);         // земля
    s.bg.lineStyle(2,0x4a3a22,0.8).lineBetween(0,top,w,top);    // горизонт
    s.hint.setPosition(w/2,22);
  }
  function depthScale(s,spr){
    const h=s.scale.height, top=h*0.42;
    const t=Phaser.Math.Clamp((spr.y-top)/(h-top),0,1);
    spr.setScale(Phaser.Math.Linear(0.30,0.62,t));             // дальше=мельче, ближе=крупнее
  }
  function create(){
    const s=this; s.bg=s.add.graphics();
    s.hint=s.add.text(0,0,'🎮 Phaser-сцена · тапни — трактирщик пойдёт (с глубиной)',
      {fontFamily:'Georgia,serif',fontSize:'15px',color:'#ffd9a8'}).setOrigin(0.5,0);
    drawBackdrop(s);
    s.anims.create({key:'walk',frames:s.anims.generateFrameNumbers('walk',{start:0,end:9}),
      frameRate:13,repeat:-1});
    s.hero=s.add.sprite(s.scale.width/2, s.scale.height*0.8,'walk',0).setOrigin(0.5,1);
    depthScale(s,s.hero);
    s.target=null;
    s.input.on('pointerdown',p=>{ s.target={x:p.x,
      y:Phaser.Math.Clamp(p.y, s.scale.height*0.43, s.scale.height*0.98)}; });
    s.scale.on('resize',()=>drawBackdrop(s));
  }
  function update(t,dt){
    const s=this, hero=s.hero; if(!hero) return;
    if(!s.target){ if(hero.anims.isPlaying){hero.anims.stop(); hero.setFrame(0);} return; }
    const dx=s.target.x-hero.x, dy=s.target.y-hero.y, d=Math.hypot(dx,dy);
    if(d<3){ s.target=null; hero.anims.stop(); hero.setFrame(0); return; }
    const v=150*(dt/1000); hero.x+=dx/d*v; hero.y+=dy/d*v;
    hero.setFlipX(dx<0);
    if(!hero.anims.isPlaying) hero.anims.play('walk');
    depthScale(s,hero); hero.setDepth(hero.y);                 // Y-сортировка (глубина)
  }
  new Phaser.Game({type:Phaser.AUTO, backgroundColor:'#15100a',
    scale:{mode:Phaser.Scale.RESIZE, autoCenter:Phaser.Scale.CENTER_BOTH,
           width:'100%', height:'100%'},
    scene:{preload,create,update}});
</script>
</body></html>"""


_MAP_HTML = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Карта Недоливска</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.jsdelivr.net/npm/pixi.js@8.6.6/dist/pixi.min.js"></script>
<style>
  html,body{margin:0;padding:0;height:100%;width:100%;overflow:hidden;
    position:fixed;inset:0;overscroll-behavior:none;background:#0e1822;
    font:14px/1.4 Georgia,serif;color:#f3e6c8;-webkit-tap-highlight-color:transparent}
  canvas{display:block;touch-action:none}
  .bar{position:fixed;left:10px;bottom:10px;z-index:6;background:#241809cc;
    border:1px solid #5a452788;border-radius:20px;padding:5px 13px;font-size:11px;
    color:#d8c39a;letter-spacing:.2px;backdrop-filter:blur(4px);pointer-events:none;
    box-shadow:0 2px 10px #0006;transition:opacity .2s}
  .card{position:fixed;left:50%;bottom:14px;transform:translateX(-50%) translateY(140%);
    z-index:10;width:min(92vw,420px);background:#241809f2;border:1px solid #6b522e;
    border-radius:14px;padding:12px 14px;box-shadow:0 8px 26px #000a;transition:transform .22s ease}
  .card.show{transform:translateX(-50%) translateY(0)}
  .card .nm{font-size:17px;color:#f6dca0;font-weight:700;margin:0 0 4px}
  .card .rw{display:flex;gap:14px;font-size:13px;color:#d8c39a;flex-wrap:wrap}
  .card .rg{color:#c2a878}
  .card .me{margin-top:7px;color:#ffd24a;font-weight:700}
  .card .x{position:absolute;right:9px;top:6px;font-size:20px;color:#a98c5c;cursor:pointer;line-height:1}
  .hint{position:fixed;right:8px;top:8px;z-index:10;font-size:11px;color:#9a8052;opacity:.85}
  .snd{position:fixed;left:10px;top:calc(8px + env(safe-area-inset-top,0px));z-index:13;
    width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-size:17px;cursor:pointer;background:#241809cc;border:1px solid #6b522e;color:#ffe2a8;
    user-select:none;-webkit-user-select:none;box-shadow:0 2px 8px #0008}
  .snd:active{transform:scale(.94)}
  .vig{position:fixed;inset:0;pointer-events:none;z-index:5;
    background:radial-gradient(ellipse 78% 78% at 50% 50%, transparent 58%, #060a12 100%)}
  .ev{position:fixed;left:50%;top:calc(12px + env(safe-area-inset-top,0px));
    transform:translateX(-50%);z-index:10;display:none;
    background:#2a160af2;border:1px solid #c9803a;border-radius:22px;padding:8px 18px;
    font-size:13px;color:#ffe2a8;font-weight:700;letter-spacing:.2px;
    box-shadow:0 4px 18px #000b;white-space:nowrap;backdrop-filter:blur(3px)}
  .reg{position:fixed;left:50%;bottom:calc(172px + env(safe-area-inset-bottom,0px));
    transform:translateX(-50%);z-index:11;display:none;
    width:min(92vw,420px);background:#241809f5;border:1px solid #c9803a;border-radius:14px;
    padding:12px 14px;text-align:center;box-shadow:0 8px 28px #000b}
  .reg .rt{font-size:16px;color:#ffd9a8;font-weight:700;margin-bottom:3px}
  .reg .rs{font-size:12px;color:#d8c39a;margin-bottom:9px;min-height:15px}
  .reg .rb{width:100%;padding:12px;border:none;border-radius:11px;background:#c0392b;
    color:#fff;font:700 15px Georgia,serif;cursor:pointer}
  .reg .rb:active{transform:scale(.98)} .reg .rb:disabled{opacity:.55}
  .reg .rj{font-size:14px;color:#ffd24a;font-weight:700}
  .rep{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:12;display:none;
    width:min(88vw,410px);max-height:76vh;overflow:auto;background:#1c1206f8;
    border:1px solid #c9803a;border-radius:14px;padding:12px 11px 15px;
    box-shadow:0 10px 34px #000d}
  .rep h3{margin:0 0 9px;font-size:15px;color:#ffd9a8;text-align:center;padding-right:18px}
  .rep .x{position:absolute;right:11px;top:8px;font-size:20px;color:#a98c5c;cursor:pointer;line-height:1}
  .reg .x{position:absolute;right:11px;top:7px;font-size:20px;color:#a98c5c;cursor:pointer;line-height:1}
  .rep table{width:100%;border-collapse:collapse;font-size:11.5px}
  .rep th{color:#a98c5c;font-weight:600;text-align:right;padding:3px 4px}
  .rep th:first-child{text-align:left}
  .rep td{padding:5px 4px;text-align:right;border-top:1px solid #3a2a16;color:#e6d3a8}
  .rep td:first-child{text-align:left;white-space:nowrap}
  .rep tr.me td{background:#43301266;color:#ffe2a8;font-weight:700}
  .rep .gold{color:#ffd24a;white-space:nowrap}
</style></head>
<body>
<div class="vig"></div>
<div class="ev" id="ev"></div>
<div class="reg" id="reg">
  <div class="rt" id="regTitle">🪓 Орда орков — сбор войск</div>
  <div class="rs" id="regSub"></div>
  <button class="rb" id="regBtn">⚔ Поднять войско</button>
  <div class="rj" id="regJoined" style="display:none"></div>
</div>
<div class="rep" id="rep">
  <span class="x" id="repx">×</span>
  <h3 id="repTitle"></h3>
  <div id="repBody"></div>
</div>
<div class="reg" id="millPanel" style="display:none">
  <span class="x" id="millx">×</span>
  <div class="rt" id="millTitle">🌀 Мельница</div>
  <div class="rs" id="millSub"></div>
  <button class="rb" id="millBtn">🛒 Снарядить телегу</button>
</div>
<div class="bar" id="bar">🗺 Недоливск · загрузка…</div>
<div class="hint">тащи · щипок/колесо — зум · тап по кружку — раскрыть</div>
<audio id="bgm" loop preload="auto" src="/assets/audio/festival.mp3"></audio>
<div class="snd" id="snd">🔊</div>
<div class="card" id="card">
  <span class="x" id="cardx">×</span>
  <div class="nm" id="cnm"></div>
  <div class="rw"><span id="clv"></span><span class="rg" id="crg"></span></div>
  <div class="me" id="cme" style="display:none">🏠 Твоя таверна</div>
</div>
<script>
const tg = window.Telegram?.WebApp;
if (tg){ tg.ready(); tg.expand();
  // отключаем вертикальный свайп Telegram (тянет/закрывает мини-апп) — иначе
  // нельзя протащить карту вниз, чтобы посмотреть север. 7.7+; на старых — no-op.
  try { tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch(e){}
}
const myId = tg?.initDataUnsafe?.user?.id || 0;
// фоновая музыка ярмарки — луп, с памятью вкл/выкл. Мобильные блокируют автоплей
// до жеста — поэтому стартуем и сразу, и при первом касании; кнопка 🔊/🔇 глушит.
(function(){
  const bgm = document.getElementById('bgm'), btn = document.getElementById('snd');
  if (!bgm || !btn) return;
  bgm.volume = 0.42;
  let muted = false; try { muted = localStorage.getItem('map_mute') === '1'; } catch(e){}
  const paint = () => { btn.textContent = muted ? '🔇' : '🔊'; };
  // Браузеры блокируют автоплей со звуком до жеста (Android — строго, iOS мягче).
  // Снимаем жест-слушатели ТОЛЬКО когда play() реально запустился; иначе пробуем
  // на КАЖДЫЙ следующий жест (а не сдаёмся после первого) — capture, чтобы поймать
  // событие раньше карты.
  const EVS = ['pointerdown','touchend','click','keydown'];
  const arm = on => EVS.forEach(e => on
    ? document.addEventListener(e, onGesture, {capture:true})
    : document.removeEventListener(e, onGesture, {capture:true}));
  function play(){
    if (muted) return;
    const p = bgm.play();
    if (p && p.then) p.then(() => arm(false)).catch(() => {});  // не вышло — ждём след. жест
  }
  function onGesture(){ play(); }
  paint(); play(); arm(true);                        // пробуем сразу (iOS) + ловим жест (Android)
  btn.addEventListener('click', (e) => { e.stopPropagation(); muted = !muted;
    try { localStorage.setItem('map_mute', muted ? '1' : '0'); } catch(_){}
    if (muted) bgm.pause(); else play();
    paint(); });
})();
const bar = document.getElementById('bar');
const card = document.getElementById('card');
const RING = {north_wilds:0x6ea8ff, green_valleys:0x6fd07a, red_wastes:0xe07a55};
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const SCREEN_W = 58;          // ширина здания НА ЭКРАНЕ (постоянная, не зависит от зума)
const CLUSTER_T = 50;         // ближе этого (px на экране) — таверны сливаются в кластер
const LABEL_MIN = 0.22;       // ниже этого масштаба подписи названий скрыты
const MAXS = 9;               // максимальный зум; минимальный = «вся карта в экране»

(async () => {
  const app = new PIXI.Application();
  await app.init({resizeTo: window, antialias: true, background: 0x0e1822,
                  resolution: Math.min(window.devicePixelRatio||1, 2), autoDensity: true});
  document.body.appendChild(app.canvas);

  let bgTex;
  try { bgTex = await PIXI.Assets.load('/assets/world.png'); }
  catch(e){ bar.textContent='⚠ карта не загрузилась'; return; }
  const W = bgTex.width, H = bgTex.height;

  // мир (фон) — зумится/двигается нативно; маркеры — ОТДЕЛЬНЫЙ слой поверх,
  // постоянного экранного размера (как пины на гео-картах), позиционируем вручную.
  const world = new PIXI.Container();
  const bg = new PIXI.Sprite(bgTex); world.addChild(bg);
  app.stage.addChild(world);
  const critterLayer = new PIXI.Container(); app.stage.addChild(critterLayer);  // живность (под маркерами)
  const millRoute = new PIXI.Graphics(); app.stage.addChild(millRoute);  // дорога телеги к мельнице
  const farmLayer = new PIXI.Container(); app.stage.addChild(farmLayer);  // фермы-ориентиры
  const pathLayer = new PIXI.Graphics(); app.stage.addChild(pathLayer);  // пунктир маршрутов
  const markers = new PIXI.Container(); markers.sortableChildren = true;
  app.stage.addChild(markers);
  const eventLayer = new PIXI.Container(); app.stage.addChild(eventLayer);  // ивенты поверх
  const eventNodes = [];   // самостоятельные анимированные ивент-объекты

  // минимальный зум = «вся карта в экране» с небольшим запасом → вокруг материка
  // видна кайма моря/тумана (плюс виньетка). Снапится по центру, меньше не сжать.
  const SEA_FRAME = 0.9;   // <1 → материк чуть меньше экрана, вокруг полоса моря
  let minScale = Math.min(app.screen.width/W, app.screen.height/H) * SEA_FRAME;
  world.scale.set(minScale); clampCam();

  // --- таверны ---
  let data;
  try { data = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json(); }
  catch(e){ bar.textContent='⚠ не загрузить таверны'; return; }
  const regions = data.regions || {};
  const taverns = data.taverns.map(t => ({...t, wx: t.x*W, wy: t.y*H}));  // мировые px

  // предзагрузим только нужные спрайты-здания
  const tiers = [...new Set(taverns.map(t=>t.tier))];
  const tex = {};
  await Promise.all(tiers.map(async n => {
    try { tex[n] = await PIXI.Assets.load('/assets/map_tavern_'+n+'.png'); } catch(e){}
  }));

  // мировые → экранные координаты (world только масштаб+сдвиг, без поворота)
  const screenOf = (wx, wy) => ({x: wx*world.scale.x + world.x, y: wy*world.scale.y + world.y});

  // ---------- здание (одиночная таверна) ----------
  function makeBuilding(t){
    const node = new PIXI.Container(); node.wx = t.wx; node.wy = t.wy; node.zIndex = t.wy;
    const st = tex[t.tier]; const w = SCREEN_W;
    const hs = st ? w*(st.height/st.width) : w;
    node.addChild(new PIXI.Graphics().ellipse(0,0, w*0.42, w*0.15).fill({color:0x000000, alpha:0.34}));
    if (t.mine)
      node.addChild(new PIXI.Graphics().ellipse(0,0, w*0.5, w*0.19).stroke({color:0xffd24a, width:3, alpha:0.95}));
    else
      node.addChild(new PIXI.Graphics().ellipse(0,0, w*0.46, w*0.17).stroke({color:RING[t.region]||0xcaa23f, width:2, alpha:0.5}));
    if (st){
      const sp = new PIXI.Sprite(st); sp.anchor.set(0.5,1); sp.scale.set(w/st.width);
      sp.y = Math.round(w*0.05); node.addChild(sp);
      sp.eventMode='static'; sp.cursor='pointer'; sp.on('pointertap', e=> showCard(t, e));
    } else {
      const g = new PIXI.Graphics().circle(0,-w*0.4, w*0.32).fill({color: t.mine?0xffd24a:(RING[t.region]||0xcaa23f)});
      node.addChild(g); g.eventMode='static'; g.cursor='pointer'; g.on('pointertap', e=> showCard(t, e));
    }
    // подпись: ЕДИНАЯ рамка [чип уровня][название] под зданием.
    // Текст всегда помещается в рамку (ширина считается по тексту). Видимость
    // решает декластеризация подписей (declutterLabels) — чтобы не налезали.
    const raw = (t.name || '').trim();
    const nm = raw.length > 20 ? raw.slice(0,19)+'…' : (raw || 'Таверна');
    const lab = new PIXI.Container(); lab.eventMode = 'none'; lab.y = 8;
    const fh = 21, padX = 6, gap = 5, chipR = 8.5;
    const txt = new PIXI.Text({text:nm, style:{fontFamily:'Georgia,serif',
      fontSize:12, fontWeight:'600', fill:0xf3e6c8}});
    const totalW = padX + chipR*2 + gap + Math.ceil(txt.width) + padX;
    lab.addChild(new PIXI.Graphics().roundRect(-totalW/2, 0, totalW, fh, 7)
      .fill({color:0x140d06, alpha:0.76}).stroke({color:0x6b522e, width:1.2, alpha:0.7}));
    const chipX = -totalW/2 + padX + chipR;
    const chipCol = t.mine ? 0xffd24a : (RING[t.region] || 0xcaa23f);
    lab.addChild(new PIXI.Graphics().circle(chipX, fh/2, chipR)
      .fill({color:chipCol}).stroke({color:0x140d06, width:1.5}));
    const lt = new PIXI.Text({text:String(t.level), style:{fontFamily:'Georgia,serif',
      fontSize:11, fontWeight:'700', fill:0x201202}});
    lt.anchor.set(0.5); lt.position.set(chipX, fh/2); lab.addChild(lt);
    txt.anchor.set(0, 0.5); txt.position.set(chipX + chipR + gap, fh/2); lab.addChild(txt);
    node.addChild(lab);
    node._label = lab; node._labelBox = {w: totalW, h: fh};
    node._pri = (t.mine ? 1e6 : 0) + t.level;   // приоритет в борьбе за место
    return node;
  }

  // ---------- кластер (несколько таверн рядом) ----------
  function makeCluster(grp, wx, wy){
    const node = new PIXI.Container(); node.wx = wx; node.wy = wy; node.zIndex = wy;
    const hasMine = grp.some(m=>m.mine);
    const cnt = {}; grp.forEach(m=>{cnt[m.region]=(cnt[m.region]||0)+1;});
    const dom = Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a])[0];
    const col = hasMine ? 0xffd24a : (RING[dom] || 0xcaa23f);
    const r = 15 + Math.min(11, grp.length);
    node.addChild(new PIXI.Graphics().ellipse(0, r*0.7, r*0.95, r*0.32).fill({color:0x000000, alpha:0.32}));
    node.addChild(new PIXI.Graphics().circle(0,0,r).fill({color:col, alpha:0.93}).stroke({color:0x241809, width:2}));
    const txt = new PIXI.Text({text:String(grp.length), style:{fontFamily:'Georgia,serif',
      fontSize:Math.round(r*0.95), fontWeight:'700', fill:0x201202}});
    txt.anchor.set(0.5); node.addChild(txt);
    node.eventMode='static'; node.cursor='pointer';
    node.on('pointertap', e=>{ e.stopPropagation(); const s = screenOf(node.wx, node.wy);
      zoomAt(s.x, s.y, 2.1); refresh(); });
    return node;
  }

  // размер маркеров привязан к зуму (sublinear, с полом/потолком): при отдалении
  // здания УМЕНЬШАЮТСЯ (видно отдельные), при приближении растут до предела.
  function markerK(){ return Math.max(0.45, Math.min(1.2, Math.sqrt(world.scale.x/minScale) * 0.52)); }

  // ---------- кластеризация (жадная, по экранной дистанции) ----------
  function buildClusters(){
    for (const c of markers.children) c.destroy({children:true});
    markers.removeChildren();
    const T = CLUSTER_T * markerK();   // порог слияния тоже масштабируется с маркерами
    const pts = taverns.map(t => ({t, s: screenOf(t.wx, t.wy)}));
    // приоритет посева: своя таверна и более высокий уровень — «центры» кластеров
    pts.sort((a,b)=> (Number(b.t.mine)-Number(a.t.mine)) || (b.t.level - a.t.level));
    const used = new Array(pts.length).fill(false);
    for (let i=0;i<pts.length;i++){
      if (used[i]) continue; used[i]=true;
      const grp = [pts[i].t];
      for (let j=i+1;j<pts.length;j++){
        if (used[j]) continue;
        if (Math.hypot(pts[j].s.x-pts[i].s.x, pts[j].s.y-pts[i].s.y) < T){ used[j]=true; grp.push(pts[j].t); }
      }
      let node;
      if (grp.length === 1) node = makeBuilding(grp[0]);
      else {
        let cx=0, cy=0; grp.forEach(m=>{cx+=m.wx; cy+=m.wy;}); cx/=grp.length; cy/=grp.length;
        node = makeCluster(grp, cx, cy);
      }
      markers.addChild(node);
    }
    declutterLabels();
    reposition();
  }

  // greedy label placement: рамка-подпись видна, только если её экранный бокс не
  // налезает на другое здание и на уже размещённые подписи. Приоритет — своя
  // таверна и более высокий уровень (сортировка по _pri убыванием).
  function declutterLabels(){
    const k = markerK();   // боксы коллизий — в текущем масштабе маркеров
    const blds = markers.children.filter(n => n._label);
    const foot = blds.map(n => { const s = screenOf(n.wx, n.wy);
      return {n, l:s.x-SCREEN_W*0.5*k, r:s.x+SCREEN_W*0.5*k, t:s.y-SCREEN_W*1.05*k, b:s.y+3}; });
    const hit = (a,b) => !(a.r < b.l || a.l > b.r || a.b < b.t || a.t > b.b);
    blds.sort((a,b) => b._pri - a._pri);
    const placed = [];
    for (const n of blds){
      const s = screenOf(n.wx, n.wy), bw = n._labelBox.w*k, bh = n._labelBox.h*k;
      const box = {l:s.x-bw/2, r:s.x+bw/2, t:s.y+8*k, b:s.y+8*k+bh};
      let ok = true;
      for (const f of foot){ if (f.n !== n && hit(box, f)){ ok = false; break; } }
      if (ok) for (const p of placed){ if (hit(box, p)){ ok = false; break; } }
      n._labelAllowed = ok;
      if (ok) placed.push(box);
    }
  }
  function reposition(){
    const showLabels = world.scale.x > LABEL_MIN;   // на сильном отдалении подписи прячем
    const k = markerK();
    for (const node of markers.children){
      const s = screenOf(node.wx, node.wy); node.x = s.x; node.y = s.y; node.scale.set(k);
      if (node._label) node._label.visible = showLabels && node._labelAllowed;
    }
    for (const ev of eventNodes){ const s = screenOf(ev.wx, ev.wy);
      ev.x = s.x; ev.y = s.y; ev.scale.set(k * 0.52); }   // ивенты крупнее таверн
  }

  // перерисовку коалесцируем по кадрам: пан — только перепозиционируем (дёшево),
  // зум (заметное изменение масштаба) — пересобираем кластеры.
  let dirty = true, lastClusterScale = -1;
  app.ticker.add(() => {
    if (!dirty) return; dirty = false;
    if (Math.abs(world.scale.x - lastClusterScale) > Math.max(lastClusterScale,0.0001)*0.02){
      buildClusters(); lastClusterScale = world.scale.x;
    } else reposition();
  });
  const refresh = () => { dirty = true; };

  // ---------- pan / zoom ----------
  app.stage.eventMode = 'static';
  app.stage.hitArea = {contains:()=>true};
  const ptrs = new Map(); let lastDist = null;

  // привязка камеры к границам: карта всегда покрывает экран, а если по оси меньше
  // (на минимальном зуме) — снапится по центру; за край утащить нельзя, меньше не сжать.
  function clampCam(){
    const s = world.scale.x, mw = W*s, mh = H*s;
    if (mw <= app.screen.width) world.x = (app.screen.width - mw)/2;
    else world.x = Math.min(0, Math.max(app.screen.width - mw, world.x));
    if (mh <= app.screen.height) world.y = (app.screen.height - mh)/2;
    else world.y = Math.min(0, Math.max(app.screen.height - mh, world.y));
  }
  function zoomAt(sx, sy, factor){
    const ns = Math.min(MAXS, Math.max(minScale, world.scale.x*factor));
    const f = ns/world.scale.x;
    world.x = sx - (sx-world.x)*f;
    world.y = sy - (sy-world.y)*f;
    world.scale.set(ns); clampCam(); refresh();
  }
  function centerOn(wx, wy, s){
    world.scale.set(Math.min(MAXS, Math.max(minScale, s)));
    world.x = app.screen.width/2  - wx*world.scale.x;
    world.y = app.screen.height/2 - wy*world.scale.y; clampCam(); refresh();
  }

  app.stage.on('pointerdown', e => ptrs.set(e.pointerId, {x:e.global.x, y:e.global.y}));
  const drop = e => { ptrs.delete(e.pointerId); if (ptrs.size<2) lastDist=null; };
  app.stage.on('pointerup', drop);
  app.stage.on('pointerupoutside', drop);
  app.stage.on('pointermove', e => {
    if (!ptrs.has(e.pointerId)) return;
    const prev = ptrs.get(e.pointerId);
    const cur = {x:e.global.x, y:e.global.y};
    ptrs.set(e.pointerId, cur);
    if (ptrs.size === 1){ world.x += cur.x-prev.x; world.y += cur.y-prev.y; clampCam(); refresh(); }
    else if (ptrs.size === 2){
      const p = [...ptrs.values()];
      const d = Math.hypot(p[0].x-p[1].x, p[0].y-p[1].y);
      const mx = (p[0].x+p[1].x)/2, my = (p[0].y+p[1].y)/2;
      if (lastDist) zoomAt(mx, my, d/lastDist);
      lastDist = d;
    }
  });
  app.canvas.addEventListener('wheel', e => {
    e.preventDefault(); zoomAt(e.offsetX, e.offsetY, e.deltaY<0 ? 1.12 : 0.89);
  }, {passive:false});
  app.stage.on('pointertap', () => card.classList.remove('show'));  // тап по пустому — закрыть

  // ---------- старт ----------
  bar.textContent = '🗺 Недоливск · ' + taverns.length + ' таверн';
  const mine = taverns.find(t=>t.mine);
  if (mine) centerOn(mine.wx, mine.wy, Math.max(minScale, 0.85)); else refresh();
  window.addEventListener('resize', () => {
    minScale = Math.min(app.screen.width/W, app.screen.height/H) * SEA_FRAME;
    if (world.scale.x < minScale) world.scale.set(minScale);
    clampCam(); refresh();
  });

  // ---------- бродячая живность (амбиент): пасётся у поселений, тихо гуляет ----------
  // Размер ПРОПОРЦИОНАЛЕН зданиям (масштаб по markerK, своя база на вид), чтобы не
  // были ни огромными, ни мелкими. Спрайт-лист 6×8, ряд 2 = боковой шаг (вправо),
  // флип по направлению. Привязаны к таверне (на суше), бродят в малом радиусе.
  (async () => {
    const SPECIES = [{n:'horse',h:30},{n:'foal',h:24},{n:'goat',h:21},{n:'goatling',h:15},
                     {n:'goose',h:17},{n:'gosling',h:11},{n:'rabbit',h:15},{n:'rabbit_cub',h:10}];
    const avail = [];
    for (const s of SPECIES){
      try {
        const tex = await PIXI.Assets.load('/assets/animals/'+s.n+'.png');
        const fw = tex.width/6, fh = tex.height/8, fr = [];     // сетка 6×8, кадр квадратный
        for (let c=0;c<6;c++)
          fr.push(new PIXI.Texture({source:tex.source, frame:new PIXI.Rectangle(c*fw, 2*fh, fw, fh)}));
        s.frames = fr; s.fh = fh; avail.push(s);
      } catch(e){}
    }
    if (!avail.length || !taverns.length) return;
    const critters = [];
    const N = Math.min(90, Math.max(24, Math.round(taverns.length*1.8)));
    for (let i=0;i<N;i++){
      const home = taverns[(Math.random()*taverns.length)|0];
      const sp = avail[(Math.random()*avail.length)|0];
      const an = new PIXI.AnimatedSprite(sp.frames);
      an.anchor.set(0.5,0.9); an.animationSpeed = 0.12; an.play();
      critterLayer.addChild(an);
      const hx = home.wx + (Math.random()-0.5)*70, hy = home.wy + (Math.random()-0.5)*70;
      critters.push({an, sp, hx, hy, wx:hx, wy:hy, tx:hx, ty:hy, dir:1, idle:Math.random()*4, moving:false});
    }
    const newTarget = c => { const r = 24+Math.random()*46, a = Math.random()*6.283;
      c.tx = c.hx + Math.cos(a)*r; c.ty = c.hy + Math.sin(a)*r; };
    let last = performance.now();
    app.ticker.add(() => {
      const now = performance.now(), dt = Math.min(0.05,(now-last)/1000); last = now;
      const show = world.scale.x > LABEL_MIN, k = markerK();   // на сильном отдалении прячем
      for (const c of critters){
        c.an.visible = show; if (!show) continue;
        if (c.moving){
          const dx=c.tx-c.wx, dy=c.ty-c.wy, d=Math.hypot(dx,dy);
          if (d < 1.5){ c.moving=false; c.idle = 1+Math.random()*4; c.an.gotoAndStop(0); }
          else { const v=14*dt; c.wx += dx/d*v; c.wy += dy/d*v; c.dir = dx>=0?1:-1;
                 if (!c.an.playing) c.an.play(); }
        } else if ((c.idle -= dt) <= 0){ newTarget(c); c.moving = true; c.an.play(); }
        const s = screenOf(c.wx,c.wy); c.an.x=s.x; c.an.y=s.y;
        const sc = (c.sp.h/c.sp.fh)*k; c.an.scale.set(sc); c.an.scale.x = sc*c.dir;  // флип
      }
    });
  })();

  let gatherMillPos = null;            // {wx,wy} мельницы-вылазки (ставит ферма-блок ниже)
  // ---------- ферма-сценка (мельница + мельник + поле + забор) на пустой суше ----------
  // Точку ищем в центральной полосе (точно суша) с МАКС. зазором до ближайшей таверны
  // → в «пустоте», а не впритык к поселениям. Вся сценка — один контейнер в пиксельных
  // координатах мельницы (origin = низ мельницы), сортировка по Y для глубины.
  (async () => {
    const load = async n => { try { return await PIXI.Assets.load('/assets/farm/'+n+'.png'); }
                              catch(e){ return null; } };
    const strip = (t, n) => { const fw=t.width/n, fr=[]; for (let i=0;i<n;i++)
      fr.push(new PIXI.Texture({source:t.source, frame:new PIXI.Rectangle(i*fw,0,fw,t.height)})); return fr; };
    const millTex = await load('mill');
    if (!millTex) return;
    const FH = millTex.height;                          // опорная высота (мельница)
    const sowTex = await load('miller_sowing'), cartTex = await load('cart'), fenceTex = await load('fence1');
    const bedTex = [await load('bed1'), await load('bed2'), await load('bed3')].filter(Boolean);
    const cropTex = [];
    for (const c of [['rye1','rye2'],['cabbage1','cabbage2'],['pumpkin1','pumpkin2'],
                     ['tomato1','tomato2'],['carrot1','carrot2']]){
      const a = await load(c[0]), b = await load(c[1]); if (a&&b) cropTex.push([a,b]);
    }
    const spr = (t, x, y, z) => { const s=new PIXI.Sprite(t); s.anchor.set(0.5,1); s.position.set(x,y); s.zIndex=z; return s; };
    const anim = (fr, x, y, z, sp) => { const a=new PIXI.AnimatedSprite(fr); a.anchor.set(0.5,1);
      a.position.set(x,y); a.zIndex=z; a.animationSpeed=sp; a.play(); return a; };
    function buildFarm(){
      const c = new PIXI.Container(); c.sortableChildren = true;
      c.addChild(anim(strip(millTex,3), 0, 0, 0, 0.06));               // мельница (лопасти крутятся)
      if (cartTex) c.addChild(spr(cartTex, -120, 4, 4));              // телега слева
      let ci = 0;                                                      // поле грядок справа
      for (let row=0; row<2; row++) for (let col=0; col<3; col++){
        const bx = 120 + col*36, by = 18 - row*14;
        if (bedTex.length) c.addChild(spr(bedTex[(row*3+col)%bedTex.length], bx, by, by));
        if (cropTex.length){ c.addChild(anim(cropTex[ci%cropTex.length], bx, by, by+0.2, 0.03)); ci++; }
      }
      if (fenceTex) for (let x=108; x<=216; x+=30) c.addChild(spr(fenceTex, x, 28, 28));  // забор спереди
      if (sowTex) c.addChild(anim(strip(sowTex,6), 98, 24, 24, 0.14)); // мельник сеет у поля
      farmLayer.addChild(c);
      return c;
    }
    const cand = [];
    for (let gx=0.22; gx<=0.78; gx+=0.07)
      for (let gy=0.26; gy<=0.74; gy+=0.07) cand.push({x:gx, y:gy, gap:1e9});
    for (const cc of cand)
      for (const t of taverns){ const d=Math.hypot(cc.x-t.x, cc.y-t.y); if (d<cc.gap) cc.gap=d; }
    cand.sort((a,b)=>b.gap-a.gap);
    const spots = [], want = 2;
    for (const cc of cand){
      if (cc.gap < 0.11) break;
      if (spots.every(o=>Math.hypot(o.x-cc.x,o.y-cc.y) > 0.22)) spots.push(cc);
      if (spots.length>=want) break;
    }
    if (!spots.length) spots.push({x:0.5, y:0.5});
    const farms = spots.map(s => ({node: buildFarm(), wx:s.x*W, wy:s.y*H}));
    if (farms.length){                                  // первая мельница — кликабельная вылазка
      gatherMillPos = {wx: farms[0].wx, wy: farms[0].wy};
      farms[0].node.eventMode = 'static'; farms[0].node.cursor = 'pointer';
      farms[0].node.on('pointertap', e => { e.stopPropagation(); openMillPanel(); });
    }
    const BASE_H = 64;
    app.ticker.add(() => {
      const k = markerK();
      for (const f of farms){ const sc = screenOf(f.wx, f.wy);
        f.node.x=sc.x; f.node.y=sc.y; f.node.scale.set((BASE_H/FH)*k); }
    });
  })();

  // ---------- вылазка «телега за зерном»: панель + телега на карте ----------
  let millState = data.mill || null;          // состояние вылазки зрителя
  let millFetchT = performance.now()/1000;     // когда получили millState (для живого отсчёта)
  let millHold = 0;                            // не перерисовывать панель (показываем итог сбора)
  const millPanel = document.getElementById('millPanel');
  const millSub = document.getElementById('millSub'), millBtn = document.getElementById('millBtn');
  const mineTav = () => taverns.find(t => t.mine);
  const millLive = () => performance.now()/1000 - millFetchT;
  function setMill(st){ millState = st || null; millFetchT = performance.now()/1000; renderMillPanel(); }
  function fmtT(s){ s=Math.max(0,Math.round(s)); const h=Math.floor(s/3600), m=Math.floor((s%3600)/60);
    return h>0 ? (h+'ч '+String(m).padStart(2,'0')+'м') : (m+':'+String(s%60).padStart(2,'0')); }
  function renderMillPanel(){
    if (millPanel.style.display==='none' || performance.now()<millHold) return;
    const st = millState || {state:'idle'};
    if (st.state==='transit'){
      const back = (st.trip_secs||1800) - (st.elapsed_secs + millLive());
      millSub.textContent = '🛒 Телега в пути · вернётся через ' + fmtT(back);
      millBtn.style.display = 'none';
      if (back <= 0) pollMill();                         // доехала — обновим до «забрать»
    } else if (st.state==='ready'){
      millSub.textContent = '🌾 Телега вернулась — забирай зерно!';
      millBtn.style.display=''; millBtn.disabled=false;
      millBtn.textContent='🌾 Забрать зерно'; millBtn.dataset.act='collect';
    } else if (st.state==='cooldown'){
      millSub.textContent = '😴 Мельница отдыхает · телега снова через ' + fmtT((st.ready_in||0) - millLive());
      millBtn.style.display = 'none';
    } else {
      millSub.textContent = 'Снаряди телегу — привезёт зерно с мельницы (~30 мин в пути).';
      millBtn.style.display=''; millBtn.disabled=false;
      millBtn.textContent='🛒 Снарядить телегу'; millBtn.dataset.act='run';
    }
  }
  async function pollMill(){
    try { const d = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json();
      setMill(d.mill); } catch(_){}
  }
  function openMillPanel(){
    millPanel.style.display='block'; millHold=0;
    if (!mineTav()){ millSub.textContent='Сначала заведи кабак в боте (/start).';
      millBtn.style.display='none'; return; }
    renderMillPanel(); pollMill();
  }
  document.getElementById('millx').onclick = () => { millPanel.style.display='none'; };
  millBtn.onclick = async () => {
    const act = millBtn.dataset.act;
    millBtn.disabled=true; const was=millBtn.textContent; millBtn.textContent='…';
    try {
      const r = await fetch(act==='collect' ? '/api/mill/collect' : '/api/mill/run',
        {method:'POST', headers:{'Content-Type':'application/json'},
         body:JSON.stringify({initData:(tg&&tg.initData)||''})});
      const d = await r.json();
      if (d.ok){
        if (act==='collect'){
          const note = d.note==='rich' ? ' · богатый помол!' : (d.note==='mishap' ? ' · тряхнуло, часть просыпал' : '');
          millSub.textContent = '🌾 +' + d.grain + ' зерна' + note;
          millBtn.style.display='none'; millHold = performance.now()+3500;   // подержать итог
          try{ tg&&tg.HapticFeedback&&tg.HapticFeedback.notificationOccurred('success'); }catch(e){}
        } else {
          try{ tg&&tg.HapticFeedback&&tg.HapticFeedback.impactOccurred('medium'); }catch(e){}
        }
        setMill(d.mill);
      } else {
        millBtn.disabled=false; millBtn.textContent=was;
        millSub.textContent = ({auth:'Открой карту через бота', no_tavern:'Сначала заведи кабак (/start)',
          busy:'Телега ещё в деле / мельница отдыхает', nothing:'Забирать нечего'}[d.error]) || 'Не вышло, ещё раз';
        if (d.mill) setMill(d.mill);
      }
    } catch(e){ millBtn.disabled=false; millBtn.textContent=was; millSub.textContent='Сеть подвела — ещё раз'; }
  };
  // движущаяся ПОВОЗКА (конь тянет телегу) на карте: таверна → мельница → таверна.
  // Конь — боковой шаг (анимация), телега прицеплена сзади; вся повозка флипается
  // по направлению (вправо/влево), конь идёт мордой вперёд.
  let millRig = null;
  (async () => {
    let hTex, cTex;
    try { hTex = await PIXI.Assets.load('/assets/animals/horse.png'); } catch(e){}
    try { cTex = await PIXI.Assets.load('/assets/farm/cart.png'); } catch(e){}
    if (!hTex) return;
    const HFW = hTex.width/6, HFH = hTex.height/8, hf = [];     // 6×8, ряд 2 = боковой шаг
    for (let c=0;c<6;c++)
      hf.push(new PIXI.Texture({source:hTex.source, frame:new PIXI.Rectangle(c*HFW, 2*HFH, HFW, HFH)}));
    const node = new PIXI.Container(); node.visible = false;
    if (cTex){ const cart = new PIXI.Sprite(cTex); cart.anchor.set(0.5,1);   // телега СЗАДИ коня
      cart.position.set(-26, -4); node.addChild(cart); }                    // дышло под коня
    const horse = new PIXI.AnimatedSprite(hf); horse.anchor.set(0.5,0.72);   // якорь по НОГАМ коня
    horse.animationSpeed = 0.18; horse.play(); node.addChild(horse);
    farmLayer.addChild(node);
    millRig = {node, HFH};
  })();
  app.ticker.add(() => {
    if (millPanel.style.display!=='none') renderMillPanel();
    millRoute.clear();
    if (!millRig) return;
    const mt = mineTav();
    if (millState && millState.state==='transit' && gatherMillPos && mt){
      const p = Math.max(0, Math.min(1, (millState.elapsed_secs + millLive())/(millState.trip_secs||1800)));
      const q = p<0.5 ? p*2 : (1-p)*2;                  // 0→1→0 (туда и обратно)
      const a = screenOf(mt.wx, mt.wy), b = screenOf(gatherMillPos.wx, gatherMillPos.wy);
      const k = markerK();
      // ЯРКАЯ ДОРОГА таверна→мельница: тёмная окантовка + светлый пунктир поверх
      const dx=b.x-a.x, dy=b.y-a.y, len=Math.hypot(dx,dy)||1, ux=dx/len, uy=dy/len;
      millRoute.moveTo(a.x,a.y).lineTo(b.x,b.y)
        .stroke({color:0x3a2410, width:Math.max(5,8*k), alpha:0.5, cap:'round'});  // казёнка
      const dash=16*k, gap=10*k;
      for (let d=0; d<len; d+=dash+gap){ const e=Math.min(len,d+dash);
        millRoute.moveTo(a.x+ux*d, a.y+uy*d).lineTo(a.x+ux*e, a.y+uy*e); }
      millRoute.stroke({color:0xffd98a, width:Math.max(3,4.5*k), alpha:0.95, cap:'round'});  // пунктир
      // повозка
      const wx = mt.wx + (gatherMillPos.wx-mt.wx)*q, wy = mt.wy + (gatherMillPos.wy-mt.wy)*q;
      const s = screenOf(wx,wy);
      const sc = (46/millRig.HFH)*k;                    // размер повозки на экране
      const dir = (gatherMillPos.wx>=mt.wx ? 1 : -1) * (p<0.5 ? 1 : -1);
      millRig.node.visible=true; millRig.node.x=s.x; millRig.node.y=s.y;
      millRig.node.scale.set(sc); millRig.node.scale.x = sc*dir;
    } else millRig.node.visible=false;
  });

  // ---------- ивент-объекты (анимированные, самостоятельные) ----------
  const RL = {tank:['🛡','Авангард'], archer:['⚔️','Рубаки'],
              scout:['🔭','Разведка'], ratnik:['🗡','Ратники']};
  let liveInv = null, reportEv = null;      // живой ивент / сводка боя
  let invAddTroop = null;                    // добавить свою дружину на карту live
  let invSyncTroops = null;                  // пересобрать дружины под финальный состав
  for (const ev of (data.events || [])){
    try {
      const tex = await PIXI.Assets.load('/assets/boss/ork'+ev.sprite+'_idle.png');
      const fw = tex.width/10, fh = tex.height;   // стрип = 10 равных кадров в ряд
      const node = buildEvent(ev, sliceFrames(tex, 10), fw, fh);
      eventLayer.addChild(node); eventNodes.push(node);
      if (ev.gather_secs != null) await setupInvasion(ev, node, fw, fh);   // полноценный ивент с боем
      if (ev.gather_secs != null && !ev.demo) liveInv = ev;                // настоящий ивент
      if (ev.report) reportEv = ev;                                        // сводка после боя
    } catch(e){ console.log('event load fail', e); }
  }
  if (liveInv || reportEv){            // во время ивента подсказка-жесты мешает банеру фазы (сверху)
    const h = document.querySelector('.hint'); if (h) h.style.display = 'none';
  }
  if (liveInv){
    centerOn(liveInv.x*W, liveInv.y*H, Math.max(minScale, 1.1));   // открываемся на орде
    if (liveInv.status === 'gathering') setupRegPanel(liveInv);    // плашка регистрации
  } else if (reportEv){
    centerOn(reportEv.x*W, reportEv.y*H, Math.max(minScale, 1.1));
    let seen = ''; try { seen = localStorage.getItem('inv_seen') || ''; } catch(e){}
    if (String(reportEv.id) !== seen) setupReportPanel(reportEv);  // авто-показ только ОДИН раз
    // иначе сводка доступна тапом по орде (showEventCard), сама не лезет
  }
  if (eventNodes.length){
    app.ticker.add(() => { const a = 0.10 + 0.12*(0.5 + 0.5*Math.sin(performance.now()/700));
      for (const ev of eventNodes) ev._glow.alpha = a; });   // мягкий пульс свечения
    refresh();
  }

  // ---------- карточка ----------
  function showCard(t, e){
    if (e) e.stopPropagation();
    document.getElementById('cnm').textContent = t.name;
    document.getElementById('clv').textContent = 'Уровень ' + t.level;
    document.getElementById('crg').textContent = regions[t.region] || t.region || '';
    document.getElementById('cme').style.display = t.mine ? 'block' : 'none';
    card.classList.add('show');
  }
  function sliceFrames(tex, count){
    const fw = tex.width/count, fh = tex.height, fr = [];
    for (let i=0;i<count;i++)
      fr.push(new PIXI.Texture({source:tex.source, frame:new PIXI.Rectangle(i*fw,0,fw,fh)}));
    return fr;
  }
  function buildEvent(ev, frames, fw, fh){
    const node = new PIXI.Container(); node.wx = ev.x*W; node.wy = ev.y*H; node._fh = fh; node._fw = fw;
    // мягкое тёплое свечение под ивентом (пульсирует) + тень
    const glow = new PIXI.Graphics().ellipse(0, -fh*0.06, fw*0.5, fw*0.2).fill({color:0xffb347, alpha:0.2});
    node.addChild(glow); node._glow = glow;
    node.addChild(new PIXI.Graphics().ellipse(0,0, fw*0.4, fw*0.13).fill({color:0x000000, alpha:0.42}));
    const anim = new PIXI.AnimatedSprite(frames); anim.animationSpeed = 0.12; anim.anchor.set(0.5,1); anim.play();
    anim.eventMode='static'; anim.cursor='pointer'; anim.on('pointertap', e=> showEventCard(ev, e));
    node.addChild(anim); node._anim = anim; node._idle = frames;
    // статичная подпись-банер — только для idle-маркера (у ивента с боем банер сверху, в HTML)
    if (ev.gather_secs == null){
      const txt = new PIXI.Text({text:'⚔ '+ev.name, style:{fontFamily:'Georgia,serif',
        fontSize:14, fontWeight:'700', fill:0xffe2a8}});
      txt.anchor.set(0.5, 1); txt.y = -fh - 8;
      const bw = txt.width + 18, by = -fh - 8 - txt.height - 4;
      node.addChild(new PIXI.Graphics().roundRect(-bw/2, by, bw, txt.height + 6, 7)
        .fill({color:0x2a160a, alpha:0.9}).stroke({color:0xc9803a, width:1.4, alpha:0.9}));
      node.addChild(txt);
    }
    return node;
  }
  // полноценный ивент: сбор → марш войск из таверн → авто-бой → итог.
  // Драйвится таймлайном (демо — локальная петля; реальный — серверное время).
  async function setupInvasion(ev, node, fw, fh){
    const anim = node._anim, idle = node._idle;
    const A = {};
    for (const a of ['hurt','die','attack']){
      try { A[a] = sliceFrames(await PIXI.Assets.load('/assets/boss/ork'+ev.sprite+'_'+a+'.png'), 10); } catch(e){}
    }
    const bx = ev.x*W, by = ev.y*H;
    // HP-бар орды (рисуем по ходу боя)
    const hp = new PIXI.Graphics(); hp.visible = false; node.addChild(hp);
    const barW = fw*0.8, barY = -fh - 16;
    function drawHp(frac, warded){     // под щитом (бронёй) бар синеет и обводится
      frac = Math.max(0, Math.min(1, frac)); hp.clear();
      hp.roundRect(-barW/2, barY, barW, 11, 4).fill({color:0x140d06, alpha:0.85})
        .stroke({color: warded?0x6ea8ff:0x6b522e, width: warded?2:1});
      if (frac>0) hp.roundRect(-barW/2+1.5, barY+1.5, (barW-3)*frac, 8, 3)
        .fill({color: warded?0x3d6fb0:0xc0392b});
    }
    // ── Сфера HP/ГОТОВНОСТИ ДРУЖИНЫ (HUD, экранная, правый-нижний угол) ─────────
    // Жидкость в стеклянной сфере (арт fant_UI). На сборе — наливается «готовность
    // к победе» (рубеж VL); в бою — живое HP дружины, тает с гибелью бойцов.
    // squadOn() — ПРОВЕРЯЕТСЯ КАЖДЫЙ КАДР: ev.army_hp_max доливается опросом, когда
    // кто-то записывается ПОСЛЕ открытия карты (иначе у раннего зрителя сфера мертва).
    const VL = 0.7;            // зеркалит invasion.VICTORY_LINE
    const squadOn = () => (ev.army_hp_max||0) > 0;
    const readyCol = f => f>=VL ? 0x3fa34d : (f>=VL*0.6 ? 0xe0a020 : 0xc0392b);
    const hpCol    = f => f>0.5 ? 0x3fa34d : (f>0.25 ? 0xe0a020 : 0xc0392b);
    let gTex=null; try{ gTex=await PIXI.Assets.load('/assets/hud/squad_globe.png'); }catch(e){}
    const GIW=226, GIH=219, GCX=112.5, GCY=100.5, GR=96;   // геометрия PNG: круг жидкости
    const hud = new PIXI.Container(); hud.visible=false; app.stage.addChild(hud);
    const gShadow = new PIXI.Graphics().ellipse(GCX, GCY+8, GR+8, GR+5).fill({color:0x000000, alpha:0.32});
    hud.addChild(gShadow);                                               // мягкая тень-подложка
    if (gTex){ const gSpr = new PIXI.Sprite(gTex); hud.addChild(gSpr); }  // стекло/оправа
    const liquid = new PIXI.Graphics(); hud.addChild(liquid);            // жидкость — поверх (полупрозрачная)
    const lmask = new PIXI.Graphics().circle(GCX, GCY, GR-2).fill(0xffffff);
    hud.addChild(lmask); liquid.mask = lmask;                            // не даём жидкости вылезти за круг
    const gLabel = new PIXI.Text({text:'', style:{fontFamily:'Georgia,serif', fontSize:20,
      fontWeight:'700', fill:0xffe9c2, stroke:{color:0x140d06, width:5}, align:'center'}});
    gLabel.anchor.set(0.5, 0.5); gLabel.position.set(GCX, GCY); hud.addChild(gLabel);   // число по центру орба
    function placeHud(){
      const disp = Math.min(138, app.screen.width*0.30), s = disp/GIW;
      hud.scale.set(s);
      hud.x = app.screen.width - GIW*s - 16;                            // правый-нижний угол
      hud.y = app.screen.height - GIH*s - 22;
    }
    placeHud(); window.addEventListener('resize', placeHud);
    function setGlobe(frac, color, label, notch){
      if (!squadOn()) return;
      hud.visible = true; frac = Math.max(0, Math.min(1, frac));
      const yTop = (GCY+GR) - frac*2*GR;
      liquid.clear();
      if (frac>0){ liquid.rect(0, yTop, GIW, (GCY+GR)-yTop).fill({color, alpha:0.6});   // тело
        liquid.rect(0, yTop, GIW, 5).fill({color:0xffffff, alpha:0.28}); }              // поверхность
      if (notch!=null){ const ny=(GCY+GR)-notch*2*GR;                                    // победный рубеж
        liquid.rect(0, ny-1, GIW, 2).fill({color:0xffe9a8, alpha:0.95}); }
      if (gLabel.text !== (label||'')) gLabel.text = label || '';   // не перерисовываем текст каждый кадр
    }
    // иконки активных баффов орды над полоской (по реальному таймлайну)
    const buffTxt = new PIXI.Text({text:'', style:{fontFamily:'Georgia,serif', fontSize:15,
      fontWeight:'700', fill:0xffe2a8, stroke:{color:0x140d06, width:4}}});
    buffTxt.anchor.set(0.5, 1); buffTxt.y = barY - 3; buffTxt.visible = false; node.addChild(buffTxt);
    // спрайты героев (3 модели) — раздаём таверне стабильно по координатам
    const HERO_COUNT = 6;
    const HERO = {};
    for (let h=1; h<=HERO_COUNT; h++){ HERO[h] = {};
      for (const a of ['walk','attack','die','idle']){
        try { HERO[h][a] = sliceFrames(await PIXI.Assets.load('/assets/heroes/hero'+h+'_'+a+'.png'), 10); } catch(e){}
      }
    }
    const hashCoord = (x,y) => Math.abs(Math.floor(x*1000)*31 + Math.floor(y*1000)*17);
    function uAnim(u, name){ if (u.anim===name) return; const fr=HERO[u.hero][name]; if (!fr) return;
      u.sp.textures = fr; u.sp.loop = (name!=='die'); u.sp.gotoAndPlay(0); u.anim = name; }
    // войска — герои, выходят из таверн
    function makeUnit(t, i){
      const h = 1 + (hashCoord(t.x, t.y) % HERO_COUNT);
      const sp = new PIXI.AnimatedSprite(HERO[h].walk || [PIXI.Texture.EMPTY]);
      sp.anchor.set(0.5, 1); sp.animationSpeed = 0.22; sp.play(); sp.visible = false;
      eventLayer.addChild(sp);
      return {sp, hero:h, anim:'walk', dir:1, ox:t.x*W, oy:t.y*H, wx:t.x*W, wy:t.y*H,
              ang:Math.random()*6.28, rad:fw*(0.30+0.25*Math.random()), delay:(i%6)*0.06};
    }
    const units = (ev.troops||[]).map((t,i)=>makeUnit(t,i));
    invAddTroop = (t) => { units.push(makeUnit(t, units.length)); };   // своя дружина live
    function rebuildUnits(troops){            // пересобрать под финальный состав (новые записи)
      for (const u of units) u.sp.destroy();
      units.length = 0;
      (troops||[]).forEach((t,i)=> units.push(makeUnit(t,i)));
    }
    invSyncTroops = (troops) => {             // вызывает опрос сбора при изменении числа
      if (troops && troops.length !== units.length) rebuildUnits(troops);
    };
    const HSCALE = 0.44;   // размер героя относительно карты
    // пунктир маршрута таверна→орда (экранные коорд., экранно-постоянный шаг)
    function drawDotted(x1,y1,x2,y2,prog){
      const dx=x2-x1, dy=y2-y1, len=Math.hypot(dx,dy)||1, ux=dx/len, uy=dy/len, end=len*prog;
      for (let d=0; d<end; d+=15){ const a=d, b=Math.min(end, d+8);
        pathLayer.moveTo(x1+ux*a, y1+uy*a).lineTo(x1+ux*b, y1+uy*b); }
    }
    // эффекты ударов (огонь/взрыв) — one-shot, спавним по орку в бою
    const FX = [];
    for (let n=1; n<=10; n++){
      try { const tx = await PIXI.Assets.load('/assets/fx/fire'+n+'.png');
        FX.push(sliceFrames(tx, Math.max(1, Math.round(tx.width/tx.height)))); } catch(e){}
    }
    const hits = [];
    function spawnHit(wx, wy, size){
      if (!FX.length) return;
      const fr = FX[(Math.random()*FX.length)|0];
      const sp = new PIXI.AnimatedSprite(fr); sp.anchor.set(0.5); sp.loop=false;
      sp.animationSpeed = 0.4; sp._wx=wx; sp._wy=wy; sp._size=size; sp._fs=fr[0].height||128;
      sp.onComplete = () => { const i=hits.indexOf(sp); if(i>=0) hits.splice(i,1); sp.destroy(); };
      sp.play(); eventLayer.addChild(sp); hits.push(sp);
    }
    // G/M фиксированы; B (длина боя) может уточниться, когда опрос сбора подтянет
    // финальный состав → читаем её и TOTAL вживую, иначе ранний зритель крутил бы
    // бой по старому числу раундов.
    const G=ev.gather_secs, M=ev.march_secs, END=4;
    const B = () => (ev.battle_secs || 0), TOTAL = () => G+M+B()+END;
    const evEl = document.getElementById('ev');
    // демо крутит локально; живой ивент синхронизируем серверным elapsed (сек с
    // начала сбора) — сдвигаем старт так, чтобы t совпало с фазой на сервере.
    let start = performance.now()/1000 - (ev.demo ? 0 : (ev.elapsed||0));
    let cur='', dieStarted=false, lastHurt=0, reportFetched=false;
    let retStarted=false, retStart=0;
    const RETURN_SECS = 7;        // дружины уходят домой так же неспешно, как шли к орде
    // конец боя — подтянуть сводку с сервера (предсказание готово сразу) и показать
    // ПРЯМО НА КАРТЕ, без перезагрузки. Несколько попыток на случай сетевой заминки.
    async function pollReport(){
      for (let i=0;i<60;i++){
        try {
          const d = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json();
          const e = (d.events||[]).find(x=>x.report);
          if (e){ setupReportPanel(e); return; }
        } catch(_){}
        await new Promise(r=>setTimeout(r, 700));
      }
    }
    function setAnim(name){
      if (cur===name) return;
      const fr = name==='idle' ? idle : A[name]; if (!fr) return;
      anim.textures = fr; anim.loop = (name!=='die'); anim.gotoAndPlay(0); cur=name;
    }
    function fmt(s){ s=Math.max(0,Math.ceil(s)); return Math.floor(s/60)+':'+String(s%60).padStart(2,'0'); }
    function reset(){ start=performance.now()/1000; cur=''; dieStarted=false; node.alpha=1; anim.tint=0xffffff;
      setAnim('idle');
      for (const sp of hits.splice(0)) sp.destroy();   // убрать активные вспышки
      for (const u of units){ u.wx=u.ox; u.wy=u.oy; u.sp.alpha=1; u.sp.visible=false; uAnim(u,'walk'); } }
    setAnim('idle');

    app.ticker.add(() => {
      let t = (performance.now()/1000) - start;
      if (t > TOTAL()){ if (ev.demo) { reset(); t = 0; } else t = TOTAL(); }
      const k = markerK();
      pathLayer.clear();
      const bs = screenOf(bx, by);
      evEl.style.display = 'block';                  // баннер фазы (внизу); на живом сборе скроем
      buffTxt.visible = false;                       // баффы орды — только в бою
      if (t < G){                                   // СБОР: войска СТОЯТ у таверн + пунктир к орде
        evEl.style.display = ev.demo ? 'block' : 'none';   // на сборе отсчёт показывает плашка регистрации
        evEl.textContent = '⚔ Сбор войск · выход через '+Math.ceil(G-t)+'с · таверн: '+units.length;
        setAnim('idle');
        if (squadOn()){                                 // 🪓 орда (бар) vs 🛡 сфера готовности
          hp.visible=true; drawHp(1);
          const rf = ev.ready!=null ? ev.ready : 0;
          const tag = rf>=VL ? 'ГОТОВЫ' : Math.min(99, Math.round(rf/VL*100))+'%';
          setGlobe(rf, readyCol(rf), '🛡 '+tag, VL);
        } else { hp.visible=false; }
        for (const u of units){ u.wx=u.ox; u.wy=u.oy; u.sp.visible=true;
          u.dir=(bx>=u.ox)?1:-1; uAnim(u,'idle');
          const us=screenOf(u.ox,u.oy); drawDotted(us.x,us.y, bs.x,bs.y, t/G); }
      } else if (t < G+M){                            // МАРШ: герои идут по пунктиру
        const p=(t-G)/M;
        evEl.textContent = '⚔ Войска идут к орде!'; setAnim('idle');
        if (squadOn()){ hp.visible=true; drawHp(1); setGlobe(1, hpCol(1), '🛡 100%'); }
        else { hp.visible=false; }
        for (const u of units){
          const lp = Math.max(0, Math.min(1, (p-u.delay)/(1-u.delay)));
          u.wx = u.ox + (bx-u.ox)*lp; u.wy = u.oy + (by-u.oy)*lp;
          u.sp.visible = lp>0; u.dir = (bx>=u.ox)?1:-1; uAnim(u,'walk');
          const us=screenOf(u.ox,u.oy); drawDotted(us.x,us.y, bs.x,bs.y, 1);
        }
      } else if (t < G+M+B()){                        // БОЙ
        const bp=(t-(G+M))/B();
        evEl.textContent = '⚔ Битва · '+fmt(B()*(1-bp));
        hp.visible=true;
        let warded=false, bf='';
        if (ev.timeline && ev.timeline.length && ev.orc_hp_max){    // РЕАЛЬНАЯ динамика
          const tl=ev.timeline, idx=Math.min(tl.length-1, Math.max(0, Math.floor(bp*tl.length)));
          const st=tl[idx]; warded=!!st.ward;
          drawHp(st.hp/ev.orc_hp_max, warded);
          if (squadOn()){ const af = st.army!=null ? st.army/ev.army_hp_max : 1;
            setGlobe(af, hpCol(af), '🛡 '+Math.round(af*100)+'%'); }   // HP дружины тает по-настоящему
          if (st.ward) bf+='🛡'; if (st.curse) bf+='💀'; if (st.adds>0) bf+='🐺'; if (st.enraged) bf+='🗣';
        } else { drawHp(1-bp); }                                    // демо — по таймеру
        buffTxt.visible = !!bf; buffTxt.text = bf;
        if (bp > 0.88 && !ev.demo && !reportFetched){ reportFetched=true; pollReport(); }  // итог пораньше
        for (const u of units){ u.ang+=0.03;
          u.wx = bx + Math.cos(u.ang)*u.rad*0.55; u.wy = by + Math.sin(u.ang)*u.rad*0.30 - fh*0.06;
          u.sp.visible=true; u.dir = (bx>=u.wx)?1:-1; uAnim(u,'attack'); }
        const s = performance.now()/1000;
        if (s-lastHurt > 0.55){ lastHurt=s; anim.tint=0xff7a6a; setAnim('hurt');
          const n = 2 + (Math.random()*2|0);   // 2–3 вспышки за удар — кучно по орку
          for (let q=0;q<n;q++)
            spawnHit(bx + (Math.random()-0.5)*fw*0.22, by - Math.random()*fh*0.1, 120 + Math.random()*60); }
        else if (s-lastHurt > 0.22){ anim.tint=0xffffff; setAnim('idle'); }
      } else {                                        // ИТОГ
        const won = ev.result!=='lost';
        evEl.textContent = won ? '🏆 Орда разбита! Победа за городом' : '💀 Орки устояли…';
        if (won){
          hp.visible=false;
          if (squadOn()){ const last=ev.timeline&&ev.timeline.length?ev.timeline[ev.timeline.length-1]:null;
            const af=last&&ev.army_hp_max?(last.army||0)/ev.army_hp_max:1;
            setGlobe(af, hpCol(af), '🛡 '+Math.round(af*100)+'%'); }   // выжившие вернулись
          if (!dieStarted && A.die){ dieStarted=true; anim.tint=0xffffff; setAnim('die');
            spawnHit(bx, by - fh*0.2, 280);                              // большой взрыв
            spawnHit(bx-fw*0.3, by, 150); spawnHit(bx+fw*0.3, by, 150); }  // + по бокам
          node.alpha = Math.max(0, node.alpha - 0.012);
          if (!retStarted){ retStarted=true; retStart=performance.now()/1000;
            for (const u of units){ u.rx0=u.wx; u.ry0=u.wy; } }   // откуда уходят
          const rp = Math.min(1, (performance.now()/1000 - retStart)/RETURN_SECS);
          for (const u of units){                       // победа — дружины НЕСПЕШНО идут домой
            u.wx = u.rx0 + (u.ox-u.rx0)*rp; u.wy = u.ry0 + (u.oy-u.ry0)*rp;
            u.dir = (u.ox>=u.wx)?1:-1; uAnim(u, rp<1 ? 'walk' : 'idle');
          }
        } else {
          let lf=0.35, af=0;
          if (ev.timeline && ev.timeline.length && ev.orc_hp_max){
            const last = ev.timeline[ev.timeline.length-1];
            lf = last.hp / ev.orc_hp_max;                              // реальный остаток HP орды
            if (squadOn()) af = (last.army||0) / ev.army_hp_max;        // дружина выбита
          }
          hp.visible=true; drawHp(lf); setAnim('idle'); anim.tint=0xffffff;
          if (squadOn()){ setGlobe(af, hpCol(af), '🛡 '+Math.round(af*100)+'%'); }   // дружина выбита
          for (const u of units){ uAnim(u,'die'); }
        }
        if (!ev.demo && !reportFetched){ reportFetched=true; pollReport(); }   // сводка live, без reload
      }
      pathLayer.stroke({color:0xffe2a8, width:Math.max(1.4, 2*k), alpha:0.5});
      for (const u of units){ const s=screenOf(u.wx,u.wy); u.sp.x=s.x; u.sp.y=s.y;
        u.sp.scale.set(k*HSCALE); u.sp.scale.x = k*HSCALE*u.dir; }
      for (const sp of hits){ const s=screenOf(sp._wx, sp._wy);
        sp.x=s.x; sp.y=s.y - fh*0.34*k; sp.scale.set(k*sp._size/sp._fs); }
    });
  }
  // ---------- боевая сводка после боя (таблица по каждому) ----------
  function setupReportPanel(ev){
    const rep = document.getElementById('rep'), title = document.getElementById('repTitle'),
          body = document.getElementById('repBody');
    title.innerHTML = (ev.won ? '🏆 Орда разбита' : '💀 Орки устояли')
      + ' · ' + (ev.n || 0) + ' дружин · ' + (ev.rounds || 0) + ' раундов';
    let html = '<table><tr><th>Боец</th><th>⚔ урон</th><th>🛡 блок</th>'
      + '<th>💥 крит</th><th>🪙 итог</th></tr>';
    for (const r of (ev.rows || [])){
      const rl = RL[r.role] || RL.ratnik;
      const nm = (r.fell ? '💀 ' : '') + rl[0] + ' ' + esc(r.name);
      const rew = ev.won
        ? ('+' + r.gold + (r.trophy ? ' 🎁' + esc(r.trophy) : ''))
        : ('' + r.gold);
      html += '<tr class="' + (r.mine ? 'me' : '') + '"><td>' + nm + '</td><td>'
        + r.dmg + '</td><td>' + r.blocked + '</td><td>' + r.crit
        + '</td><td class="gold">' + rew + '</td></tr>';
    }
    body.innerHTML = html + '</table>';
    rep.style.display = 'block';
    bar.style.display = 'none';            // на время сводки счётчик прячем
    try { localStorage.setItem('inv_seen', String(ev.id || '')); } catch(e){}  // больше не авто-показывать этот бой
  }
  document.getElementById('repx').onclick = () => {
    document.getElementById('rep').style.display = 'none';
    bar.style.display = '';                 // вернуть счётчик после закрытия сводки
  };

  function showEventCard(ev, e){
    if (e) e.stopPropagation();
    if (ev.report){ setupReportPanel(ev); return; }   // тап по орде — пересобрать и показать сводку
    document.getElementById('cnm').textContent = '⚔ ' + ev.name;
    document.getElementById('clv').textContent = ev.blurb || '';
    document.getElementById('crg').textContent = 'Событие';
    document.getElementById('cme').style.display = 'none';
    card.classList.add('show');
  }
  document.getElementById('cardx').onclick = () => card.classList.remove('show');

  // ---------- плашка регистрации на карте (фаза сбора живого ивента) ----------
  function setupRegPanel(ev){
    const reg = document.getElementById('reg'), btn = document.getElementById('regBtn'),
          sub = document.getElementById('regSub'), joined = document.getElementById('regJoined');
    reg.style.display = 'block';
    bar.style.display = 'none';            // плашка-счётчик не мешает регистрации
    function paintJoined(role){
      btn.style.display = 'none';
      const rl = RL[role] || RL.ratnik;
      joined.style.display = 'block';
      joined.textContent = '✅ Ты в строю · ' + rl[0] + ' ' + rl[1];
    }
    if (ev.me_registered) paintJoined(ev.my_role);
    // опрос на сборе: чужие записи тоже наливают полоску готовности дружины
    const poll = setInterval(async () => {
      try {
        const d = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json();
        const e = (d.events||[]).find(x => x.gather_secs != null && !x.demo);
        if (e && e.status === 'gathering'){
          if (e.ready != null) ev.ready = e.ready;
          if (e.n != null) ev.n = e.n;
          // синхронизируем БОЕВЫЕ данные с финальным составом — иначе у того, кто
          // открыл карту раньше остальных, анимация/сфера считались бы по старому
          // ростеру (и могли разойтись с реальным итогом боя).
          if (e.army_hp_max != null) ev.army_hp_max = e.army_hp_max;
          if (e.orc_hp_max != null) ev.orc_hp_max = e.orc_hp_max;
          if (e.timeline) ev.timeline = e.timeline;
          if (e.result) ev.result = e.result;
          if (e.battle_secs != null) ev.battle_secs = e.battle_secs;
          if (invSyncTroops && e.troops) invSyncTroops(e.troops);
        } else { clearInterval(poll); }
      } catch(_){}
    }, 4000);
    const start = performance.now()/1000 - (ev.elapsed || 0);
    app.ticker.add(() => {
      const left = Math.max(0, (ev.gather_secs || 0) - (performance.now()/1000 - start));
      if (left <= 0){ reg.style.display = 'none'; return; }   // сбор окончен — плашка уходит
      const rf = ev.ready!=null ? ev.ready : 0;
      const tag = rf>=0.7 ? '✅ состав победный' : (rf>=0.42 ? '⚠️ почти — зовите ещё' : '🔴 войска мало');
      sub.textContent = '⏳ Выход через ' + Math.floor(left/60) + ':'
        + String(Math.floor(left % 60)).padStart(2, '0') + ' · таверн: ' + (ev.n || 0)
        + ' · ' + tag;
    });
    btn.onclick = async () => {
      btn.disabled = true; const was = btn.textContent; btn.textContent = 'Поднимаем…';
      try {
        const r = await fetch('/api/invasion/join', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({initData: (tg && tg.initData) || ''})});
        const d = await r.json();
        if (d.ok){
          paintJoined(d.role);
          try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred('success'); } catch(e){}
          if (invAddTroop) invAddTroop({x: d.x, y: d.y});   // твоя дружина появляется на карте live
          if (d.ready != null) ev.ready = d.ready;          // полоска готовности доливается сразу
          if (d.n != null) ev.n = d.n;
        } else {
          btn.disabled = false; btn.textContent = was;
          sub.textContent = ({no_tavern: 'Сначала заведи кабак в боте (/start)',
            closed: 'Сбор уже закончился', testing: 'Ивент на тестировании — скоро откроем',
            auth: 'Не удалось войти — открой карту через бота'}[d.error]) || 'Не вышло, попробуй ещё';
        }
      } catch(e){ btn.disabled = false; btn.textContent = was; sub.textContent = 'Сеть подвела — ещё раз'; }
    };
  }
})();
</script>
</body></html>"""
