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

import json
import pathlib
from datetime import datetime, timedelta, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap
from bot.game import invasion as invmod

ASSETS_DIR = worldmap.ASSETS_DIR
# Собранный React-мини-апп (Vite → miniapp/dist; собирается в Docker, отдаётся под /app).
MINIAPP_DIST = pathlib.Path(__file__).resolve().parent.parent / "miniapp" / "dist"

# Аутентификация/гейты/держатель бота — вынесены в bot/webapi/core.py (распил
# монолита, move-only). Импорт сюда = ре-экспорт для внешних потребителей.
from bot.webapi.core import (  # noqa: E402,F401 — фасад
    _INITDATA_MAX_AGE, _auth, _init_user, _is_admin, _verify_init_data,
    base_url, get_bot, set_bot,
)


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
        _bot = get_bot()
        if _bot is not None:
            for cid in await repo.all_chat_ids(s):
                sent = await deliver(lambda c=cid: send_raid_announce(
                    _bot, c, boss, text, raid_gather_kb(boss.id)), what=f"raid→{cid}")
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


async def _api_notifications(request: web.Request) -> web.Response:
    """Лента уведомлений игрока (раздел «Уведомления») — зеркало ВСЕХ DM + счётчик непрочитанных."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        rows = await repo.feed_list(s, uid, 60)
        unread = await repo.feed_unread(s, uid)
    items = [{"text": r.text, "read": bool(r.read), "ago": _chron_ago(r.created_at, now)}
             for r in rows]
    return web.json_response({"ok": True, "items": items, "unread": unread},
                             headers={"Cache-Control": "no-store"})


async def _api_notifications_read(request: web.Request) -> web.Response:
    """Отметить все уведомления игрока прочитанными (гасит бейдж)."""
    uid, _body = await _auth(request)
    if uid is None:
        return _body
    async with session_factory() as s:
        await repo.feed_mark_read(s, uid)
        await s.commit()
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


def _all_notification_samples() -> list[str]:
    """Полный набор ИГРОВЫХ уведомлений с образцовыми данными — для теста ленты (админ).
    Каждый текст в try/except с фолбэком: проблемный объект не валит остальные."""
    from types import SimpleNamespace as NS
    from bot import texts as T

    def t(fn, fallback: str) -> str:
        try:
            r = fn()
            return r if isinstance(r, str) and r.strip() else fallback
        except Exception:   # noqa: BLE001 — образец, фолбэк ок
            return fallback

    bld = NS(emoji="🍺", name="Пивоварня")
    itm = NS(name="Дублёная кольчуга")
    boss = NS(boss_key=next(iter(__import__("bot.game.raid", fromlist=["BOSSES"]).BOSSES), "demon_slime"))
    try:
        from bot.game import season as _se
        seas = _se.SEASONS[_se.season_index(datetime.now(timezone.utc))]
    except Exception:   # noqa: BLE001
        seas = None
    we = NS(emoji="🌧", name="Проливные дожди", blurb="Небо прохудилось — дороги развезло.", good_price=1.0)
    cit = NS(pulse=("ale", -1, "скупает весь эль в округе"), emoji="💰", name="Купец Толстосум")
    hol = NS(emoji="🎉", name="Винокурня-fest", blurb="гуляет весь Недоливск")

    items: list[str] = [
        t(lambda: T.build_ready_notification(bld), "🍺 Пристройка достроена! Загляни в Пристройки."),
        t(lambda: T.craft_ready_notification(itm, 2), "⚒ Вещь готова! Мастер ждёт — забирай."),
        t(lambda: T.expedition_returned(["wood", "ore"]), "🎒 Бригады вернулись! Забирай добычу."),
        t(T.hunter_recovered_notification, "🩹 Охотник оклемался — снова в бой."),
        t(lambda: T.brew_ready_notification(2), "🍺 Эль дображивает — пора разливать."),
        t(lambda: T.brew_aged_notification(2), "🍺 Эль выдержан — особый вкус!"),
        t(lambda: T.meadery_ready_notification("mead"), "🍯 Медовуха поспела."),
        t(T.kitchen_ready_notification, "🍲 Кухня: жаркое готово."),
        t(T.winery_ready_notification, "🍷 Винокурня: вино готово."),
        t(T.malt_ready_notification, "🌾 Солод готов."),
        t(lambda: T.recipe_ready_notification("bread"), "🥖 Партия по рецепту готова."),
        t(lambda: T.auction_settled({"sold": True, "good": "ale1", "qty": 8, "gold": 140,
                                     "unit": 18, "npc": "merchant"}),
          "🔨 Молоток стукнул — лот ушёл! +140 🪙 в мошну."),
        "🔨 Твой лот 8×🍺 Эль заметили на торгах — ставка 22 🪙!",
        "⌛ Лот на бирже истёк — 8×🍺 Эль вернулись в погреб.",
        "⌛ Заявка «куплю» истекла — залог 160 🪙 вернулся.",
        t(lambda: T.bourse_news([("ale1", 20, 18), ("bread", 12, 9)], [("mead", 10, 24)]),
          "📦 Свежие лоты на бирже — загляни на торги."),
        "🚪 Странствующий монах ждёт тебя у стойки — загляни в таверну.",
        t(lambda: T.raid_push_dm(boss), "⚔️ Рейд-босс приближается — открой кабак!"),
        t(T.raid_fight_ping, "⚔️ Битва началась — бей босса!"),
        t(lambda: T.raid_cast_push(boss, ["enrage3"]), "🔥 Босс впал в бешенство — берегись!"),
        t(lambda: T.invasion_push_dm(None), "🪓 Орда орков прёт на Недоливск — в строй!"),
        t(lambda: T.invasion_reward_dm(True, 150, 8, {"wood": 10}, "🗡 Редкий клинок орка"),
          "🏆 Орда разбита! Твоя доля: +150 🪙, +8 репутации, 🪵×10."),
        t(lambda: T.invasion_reward_dm(False, -40, -3), "💀 Орда прорвалась — потери: −40 🪙."),
        t(lambda: T.mill_back_dm(35), "🌾 Телега привезла зерно +35."),
        t(T.bonus_ready_push, "🎁 Бонус дня готов — забери и активируй."),
        t(lambda: T.season_announce(seas) if seas else None, "🍂 Сменился сезон — спрос меняется."),
        t(lambda: T.worldevent_announce(we, None), "🌧 Мировое событие: проливные дожди."),
        t(lambda: T.market_pulse_announce(cit), "📈 Рынок качнуло — цены пошли."),
        "🌍 <b>ВЕСТИ ИЗ НЕДОЛИВСКА</b>\n\n🎪 Ярмарка открылась! Спрос на товары взлетел.",
        t(lambda: T.fair_open_announce(), "🎪 Ярмарка открылась — сбывай, пока берут!"),
        t(lambda: T.holiday_announce(hol), "🎉 В Недоливске праздник!"),
        t(lambda: T.idle_nudge(2), "🍺 Кабак простаивает — загляни, гости заждались."),
        t(lambda: T.onboard_nudge(True), "🏰 Ты завёл двор, но кабак так и не открыл — пора!"),
        "🎟 Зазывала сработал: твой гость дошёл до Недоливска — держи награду!",
    ]
    return [x[:1024] for x in items if x and x.strip()]


async def _api_notifications_seed_all(request: web.Request) -> web.Response:
    """АДМИН-тест: засеять в ленту по образцу ВСЕХ типов игровых уведомлений."""
    uid, _body = await _auth(request)
    if uid is None:
        return _body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    samples = _all_notification_samples()
    async with session_factory() as s:
        for txt in samples:
            repo.feed_push(s, uid, txt)
        await s.commit()
    return web.json_response({"ok": True, "count": len(samples)},
                             headers={"Cache-Control": "no-store"})


# Патчноут «перенос в мини-апп» — 3 части (≤1024 симв.), для доставки админу в ленту.
_PATCHNOTE_CHUNKS = [
    "📣 ПАТЧНОУТ (3/3) — дорожная карта\n\n"
    "🤝 Гильдии — общий чат, цели, помощь\n"
    "⚔️ Гильдейские войны за регионы на карте\n"
    "🏆 Рейтинги — топ таверн, короны на карте\n"
    "🪓 Вторжение Орды орков в приложении\n"
    "🗺 Карта для всех + действия прямо с карты\n"
    "🌫 Туман войны — открывай мир исследованием\n"
    "🎯 Сезоны и награды\n"
    "🛒 Прямая торговля между игроками\n"
    "✨ Живая карта — облака, точки интереса, события мира",
    "📣 ПАТЧНОУТ (2/3) — что нового\n\n"
    "🗺 Карта мира — общая карта для всех игроков. Таверны отмечены огоньками, "
    "у регионов есть названия, плавный зум на весь экран. Своя таверна выделена.\n\n"
    "🔔 Уведомления — все вести собираются прямо в игре (этот раздел). В чат бот "
    "присылает только короткое напоминание, без спама.\n\n"
    "🔨 Торги — продажи с аукциона, сводки биржи и ярмарка теперь приходят и в общий "
    "чат. Тексты обновили — понятнее и с деталями.\n\n"
    "⚔️ Рейд-босс — бой и призыв прямо в приложении.",
    "📣 ПАТЧНОУТ (1/3) — Недоливск переехал в приложение\n\n"
    "Вся игра теперь в Mini App прямо в Telegram. Управление кнопками, команды не нужны.\n\n"
    "🏰 Уже в приложении:\n"
    "• Таверна — доход, улучшение, сбыт гостям, бонус дня, грамота новосёла\n"
    "• Двор и пристройки — стройка и производство\n"
    "• Персонаж и кузница — статы, снаряжение, ковка, лечение\n"
    "• Вылазки — бригады, охота, ночные ходки\n"
    "• Торг, аукцион и биржа\n"
    "• Рейд-босс\n"
    "• Город — визитёры, летопись, репутация\n"
    "• Зазывала",
]


async def _api_notifications_seed_patchnote(request: web.Request) -> web.Response:
    """АДМИН: прислать себе в ленту патчноут «перенос в мини-апп» (3 части)."""
    uid, _body = await _auth(request)
    if uid is None:
        return _body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    async with session_factory() as s:
        for txt in _PATCHNOTE_CHUNKS:   # порядок: часть 1 окажется сверху ленты
            repo.feed_push(s, uid, txt)
        await s.commit()
    return web.json_response({"ok": True, "count": len(_PATCHNOTE_CHUNKS)},
                             headers={"Cache-Control": "no-store"})


# NPC → аватар (public/npc/N.png). Набор из 20 портретов раскидан по сословиям,
# женщины/иконичные — отдельно; выбор внутри сословия детерминирован по id.
# NPC-аватары — вынесены в bot/webapi/core.py (нужны и торгу, и стори-блоку).
from bot.webapi.core import _AV_BY_ESTATE, _npc_avatar  # noqa: E402,F401 — фасад


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
        "region": worldmap.continent_name(p.region, p.id),   # локация = континент своей зоны
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
        out["notif_unread"] = await repo.feed_unread(s, uid)  # бейдж колокольчика
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


# Торг/аукцион/биржа — вынесены в bot/webapi/torg.py (распил, move-only).
from bot.webapi.torg import (  # noqa: E402,F401 — фасад
    _api_auction, _api_auction_cancel, _api_auction_create, _api_auction_seed,
    _api_auction_seen, _api_auction_settle_now, _api_bourse, _api_bourse_act,
    _api_torg, _api_torg_buy,
)



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


# Доска почёта/тренд/короны/аватарки — вынесены в bot/webapi/rating.py
# (распил монолита, move-only). Импорт сюда = ре-экспорт для потребителей
# (notifier.snapshot_rating_ranks, тесты, _world_taverns ниже).
from bot.webapi.rating import (  # noqa: E402,F401 — фасад
    _AVATAR_CACHE, _RANK_SNAPS, _RATING_METRICS, _RATING_TOP, _api_avatar,
    _api_rating, _ava_sig, _ranked, _rating_board, _rating_entries,
    _rating_leaders, _trend_baseline, _trend_hydrate, _trend_record,
    snapshot_rating_ranks,
)



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

# Ночная ходка — bot/webapi/nightrun.py (распил, move-only).
from bot.webapi.nightrun import (  # noqa: E402,F401 — фасад
    _api_nightrun, _api_nightrun_bank, _api_nightrun_meet, _api_nightrun_pick,
    _api_nightrun_push, _api_nightrun_quiz, _api_nightrun_start,
)


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


# Карты мира (/map, /world, тайлы, таверны с коронами) — bot/webapi/world.py
# (распил, move-only). Импорт = ре-экспорт для build_app и внешних потребителей.
from bot.webapi.world import (  # noqa: E402,F401 — фасад
    _map_page, _world_continents, _world_page, _world_png, _world_slots,
    _world_taverns, _world_tile,
)


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
        raise web.HTTPNotFound() from None
    if not 1 <= n <= 9:
        raise web.HTTPNotFound() from None
    body = _trimmed_sprite_png(n)
    if body is None:
        raise web.HTTPNotFound() from None
    return web.Response(body=body, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


_EVENT_ANIMS = {"idle", "hurt", "die", "attack", "walk", "run"}


async def _event_sprite(request: web.Request) -> web.Response:
    # Стрип-анимация орка-ивента: ork{n}_{anim}.png — 10 кадров в ряд (AnimatedSprite).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound() from None
    anim = request.match_info.get("anim", "idle")
    if not (1 <= n <= 3) or anim not in _EVENT_ANIMS:
        raise web.HTTPNotFound() from None
    p = ASSETS_DIR / "boss" / f"ork{n}_{anim}.png"
    if not p.is_file():
        raise web.HTTPNotFound() from None
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _hero_sprite(request: web.Request) -> web.Response:
    # Стрип-анимация героя-воина (1..3): hero{n}_{anim}.png — войска из таверн.
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound() from None
    anim = request.match_info.get("anim", "walk")
    if not (1 <= n <= 6) or anim not in _EVENT_ANIMS:
        raise web.HTTPNotFound() from None
    p = ASSETS_DIR / "heroes" / f"hero{n}_{anim}.png"
    if not p.is_file():
        raise web.HTTPNotFound() from None
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _fx_sprite(request: web.Request) -> web.Response:
    # Стрип-эффект удара/взрыва: fire{n}.png — квадратные кадры (one-shot VFX).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound() from None
    p = ASSETS_DIR / "fx" / f"fire{n}.png"
    if not (1 <= n <= 10) or not p.is_file():
        raise web.HTTPNotFound() from None
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


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app() -> web.Application:
    app = web.Application(middlewares=[_api_errors])
    app.router.add_get("/", _health)   # healthcheck Railway
    app.router.add_get("/map", _map_page)
    app.router.add_get("/world", _world_page)                 # тайловый мир-атлас (Leaflet)
    app.router.add_get("/world/slots.json", _world_slots)
    app.router.add_get("/world/taverns.json", _world_taverns)
    app.router.add_get("/world/tiles/{z}/{x}/{y}.webp", _world_tile)
    app.router.add_get("/world/tiles/{z}/{x}/{y}.jpg", _world_tile)   # старый кэш → отдаём webp-байты
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
    app.router.add_post("/api/rating", _api_rating)              # доска почёта (топ таверн по ВВП)
    app.router.add_get("/avatar/{uid}", _api_avatar)            # фото профиля игрока (лидерборд)
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
    app.router.add_post("/api/notifications", _api_notifications)       # лента уведомлений (зеркало всех DM)
    app.router.add_post("/api/notifications/read", _api_notifications_read)  # отметить прочитанными
    app.router.add_post("/api/notifications/seed_all", _api_notifications_seed_all)  # АДМИН-тест: засеять все типы
    app.router.add_post("/api/notifications/seed_patchnote", _api_notifications_seed_patchnote)  # АДМИН: патчноут в ленту
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
        raise web.HTTPNotFound() from None
    p = ASSETS_DIR / "farm" / f"{name}.png"
    if not p.is_file():
        raise web.HTTPNotFound() from None
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


_ANIMALS = {"horse", "foal", "goat", "goatling", "goose", "gosling", "rabbit", "rabbit_cub"}


async def _animal_sprite(request: web.Request) -> web.Response:
    name = request.match_info.get("name", "")
    if name not in _ANIMALS:
        raise web.HTTPNotFound() from None
    p = ASSETS_DIR / "animals" / f"{name}.png"
    if not p.is_file():
        raise web.HTTPNotFound() from None
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _hud_globe(request: web.Request) -> web.Response:
    p = ASSETS_DIR / "hud" / "squad_globe.png"
    if not p.is_file():
        raise web.HTTPNotFound() from None
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _audio_track(request: web.Request) -> web.Response:
    p = ASSETS_DIR / "audio" / "festival.mp3"
    if not p.is_file():
        raise web.HTTPNotFound() from None
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def run_webapp(port: int, bot=None) -> web.AppRunner:
    """Запустить веб-сервер карты (вызывается из main параллельно с поллингом).
    bot — тот же aiogram-Bot (один event-loop): нужен, чтобы мини-апп-эндпоинты
    могли слать в чаты (напр. админский призыв рейд-босса)."""
    set_bot(bot)
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
