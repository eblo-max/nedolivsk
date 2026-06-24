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

# initData живёт сутки — отсекаем устаревшие/реплей.
_INITDATA_MAX_AGE = 24 * 3600


def _verify_init_data(init_data: str) -> int | None:
    """Проверить Telegram WebApp initData (HMAC-SHA256 по токену бота). Возвращает
    user_id, если подпись верна и свежая, иначе None. Это аутентификация запросов
    с карты (без неё нельзя доверять, кто регистрируется)."""
    from bot.config import settings
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        recv = pairs.pop("hash", None)
        if not recv:
            return None
        if abs(time.time() - int(pairs.get("auth_date", "0"))) > _INITDATA_MAX_AGE:
            return None
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv):
            return None
        user = json.loads(pairs.get("user", "{}"))
        uid = user.get("id")
        return int(uid) if uid else None
    except (ValueError, KeyError, TypeError):
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
        "upgrade_pct": pct, "maxed": maxed,
    }


async def _api_state(request: web.Request) -> web.Response:
    """Снапшот Таверны (read-only)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        out = _tavern_state(p, p.tavern)
    return web.json_response(out, headers={"Cache-Control": "no-store"})


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
        await s.commit()
        st = _tavern_state(p, p.tavern)
    return web.json_response({"ok": True, "collected": collected, "state": st,
                              "retail": bool(order)},
                             headers={"Cache-Control": "no-store"})


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
        names = {"gold": "Золото", **bal.RESOURCE_NAMES}
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
    names = {"gold": "Золото", **bal.RESOURCE_NAMES}
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
                cost.append({"key": k, "name": names.get(k, k), "need": int(v), "have": have, "ok": have >= int(v)})
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


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/map", _map_page)
    app.router.add_get("/app", _spa)                  # React-мини-апп (каркас игры)
    app.router.add_get("/app/{tail:.*}", _spa)        # SPA-fallback + статика dist
    app.router.add_get("/api/taverns", _api_taverns)
    app.router.add_post("/api/invasion/join", _api_invasion_join)
    app.router.add_post("/api/mill/run", _api_mill_run)        # вылазка телеги за зерном
    app.router.add_post("/api/mill/collect", _api_mill_collect)
    app.router.add_post("/api/state", _api_state)        # снапшот Таверны (mini-app)
    app.router.add_post("/api/collect", _api_collect)    # собрать доход
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


async def run_webapp(port: int) -> web.AppRunner:
    """Запустить веб-сервер карты (вызывается из main параллельно с поллингом)."""
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
