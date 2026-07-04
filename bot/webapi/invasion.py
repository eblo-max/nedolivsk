"""Старая карта (/api/taverns: таверны+события для PNG-карты бота) и Орда орков
(запись в вторжение из мини-аппа). Перенесено из bot/webapp.py дословно (move-only)."""

import json
from datetime import datetime, timedelta, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap
from bot.game import invasion as invmod
from bot.webapi.core import _verify_init_data

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
        sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv),
                              trait=invmod.trait_of(inv)[0])
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
            rounds = invmod.simulate(parts, seed=live.id, escal=invmod.escal_of(live),
                                     trait=invmod.trait_of(live)[0])["rounds"]
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


def _stances_dto(counter: str) -> list[dict]:
    """Стойки для выбора при записи (+флаг рекомендованной против трейта орды)."""
    return [{"id": k, "emoji": v["emoji"], "name": v["name"], "blurb": v["blurb"],
             "role": v["role"], "counter": k == counter}
            for k, v in invmod.STANCES.items()]


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
    stance = str((body or {}).get("stance") or "")
    if stance not in invmod.STANCES:
        stance = ""                                      # без выбора — авто из билда
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
                                 combat.player_stats(player), stance)
        if not already:
            ok = await repo.invasion_register(s, inv.id, player.id, rec)
            if ok:
                repo.add_log(s, "player", player.id,
                             f"⚔️ поднял войско ({invmod.STANCES.get(stance, {}).get('name', 'в резерв')})")
                await s.commit()
            else:
                already = True
        # пересчёт готовности после записи — чтобы полоска дружины долилась сразу
        fresh = await repo.get_active_invasion(s) or inv
        parts = [dict(r, pid=int(pid)) for pid, r in (fresh.registered or {}).items()]
        tr = invmod.trait_of(fresh)
        sim = invmod.simulate(parts, seed=fresh.id, escal=invmod.escal_of(fresh), trait=tr[0])
    out = {"role": rec["role"], "stance": rec.get("stance", ""),
           "dmg": round(rec["dmg"]), "crit": rec["crit"],
           "armor": rec["armor"], "dodge": rec["dodge"], "hp": rec["hp"],
           "x": rec["tx"], "y": rec["ty"], "already": already,
           "ready": round(invmod.readiness(sim), 3), "n": invmod.registered_count(fresh),
           "trait": {"id": tr[0], "emoji": tr[1], "name": tr[2], "counter": tr[3], "blurb": tr[4]},
           "comp": invmod.composition(parts), "hint": invmod.need_hint(parts, tr),
           "stances": _stances_dto(tr[3])}
    out["ok"] = True
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _api_invasion_state(request: web.Request) -> web.Response:
    """Состояние сбора орды для панели «в строй» (ФАЗА 1): трейт-слабость, состав
    по ролям, готовность, стойки, моя запись. Read-only peek — не регистрирует."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    from datetime import datetime, timezone
    async with session_factory() as s:
        inv = await repo.get_active_invasion(s)
        if inv is None or inv.status != "gathering":
            return web.json_response({"ok": True, "active": False},
                                     headers={"Cache-Control": "no-store"})
        parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
        tr = invmod.trait_of(inv)
        sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv), trait=tr[0])
        me = (inv.registered or {}).get(str(uid))
        gu = inv.gather_until
        if gu is not None and gu.tzinfo is None:
            gu = gu.replace(tzinfo=timezone.utc)
        left = max(0, int((gu - datetime.now(timezone.utc)).total_seconds())) if gu else 0
    return web.json_response({
        "ok": True, "active": True, "id": inv.id, "n": invmod.registered_count(inv),
        "ready": round(invmod.readiness(sim), 3), "gather_left": left,
        "registered": me is not None, "my_stance": (me or {}).get("stance") if me else None,
        "trait": {"id": tr[0], "emoji": tr[1], "name": tr[2], "counter": tr[3], "blurb": tr[4]},
        "comp": invmod.composition(parts), "hint": invmod.need_hint(parts, tr),
        "stances": _stances_dto(tr[3]),
    }, headers={"Cache-Control": "no-store"})


async def _api_invasion_seed(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): ТИХО призвать Орду орков — БЕЗ анонсов в чаты и пушей
    игрокам (в отличие от /orc). Fast-режим + болванка-армия (отриц. pid → в наградах
    пропускаются, никого не уведомляет). Появится на карте /world (гейт админа).
    Весь жизненный цикл тихий: inv.messages пуст → нотифаер ничего не постит/правит."""
    from bot.webapi.core import _auth, _is_admin
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from datetime import datetime, timezone
    async with session_factory() as s:
        if await repo.get_active_invasion(s) is not None:
            return web.json_response({"ok": False, "error": "busy"})
        now = datetime.now(timezone.utc)
        threshold = invmod.horde_threshold(await repo.world_might_sum(s))
        g_until, r_at = invmod.schedule(now, fast=True)
        inv = repo.create_invasion(s, sprite=invmod.SPRITE, threshold=threshold,
                                   gather_until=g_until, resolve_at=r_at)
        inv.registered = invmod.dummy_roster()          # болванка — сразу виден марш
        world = await repo.get_or_create_world(s)
        inv.escal = invmod.escalation(getattr(world, "orc_wins", 0))
        world.invasion_next_at = None                   # активна — авто не спавнит поверх
        await s.flush()                                 # нужен inv.id
        invmod.set_gathering(inv.id)
        repo.add_log(s, "admin", uid, "🪓 тихо призвал Орду (мини-апп, тест карты)")
        await s.commit()
        iid = inv.id
    return web.json_response({"ok": True, "id": iid, "gather_secs": invmod.FAST_GATHER_SECONDS},
                             headers={"Cache-Control": "no-store"})
