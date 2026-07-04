"""Орда орков: сводка боя для интерактивной карты (/world) и запись во вторжение
из мини-аппа (панель «в строй», модалка итогов). Позиции таверн — из worldmap."""

import json
from datetime import datetime, timedelta, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import worldmap
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
    # разбор боя (причина исхода + MVP + павшие) — считаем на report С pid, до стрипа
    pm = invmod.postmortem(report, invmod.trait_of(inv), bool(won))
    rows = [{k: v for k, v in r.items() if k != "pid"}
            | {"mine": bool(uid) and int(r.get("pid", 0)) == uid} for r in report]
    return {
        "id": inv.id, "sprite": inv.sprite, "x": invmod.POS[0], "y": invmod.POS[1],
        "name": invmod.NAME, "blurb": "Итог битвы с ордой орков",
        "report": True, "won": bool(won), "status": inv.status,
        "rounds": int(rounds or 0), "n": int(n or 0),
        "orc_hp_left": int(ohl or 0), "orc_hp_max": int(ohm or 1), "rows": rows,
        "postmortem": pm,
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
    # ВАЖНО: с тем же трейтом орды, что нотифаер и модалка итогов — иначе карта
    # показала бы один исход (HP тает без слабости), а начисление — другой.
    parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
    sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv),
                          trait=invmod.trait_of(inv)[0])
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


def _stances_dto(counter: str) -> list[dict]:
    """Стойки для выбора при записи (+флаг рекомендованной против трейта орды)."""
    return [{"id": k, "emoji": v["emoji"], "name": v["name"], "blurb": v["blurb"],
             "role": v["role"], "counter": k == counter}
            for k, v in invmod.STANCES.items()]


_PREP_STAT = {"armor": "брони", "hp": "HP", "dmg": "урона"}


def _prep_bonus_txt(bonus: dict) -> str:
    return " ".join(f"+{v} {_PREP_STAT.get(k, k)}" for k, v in bonus.items())


def _preps_dto() -> list[dict]:
    """Каталог военных приготовлений (ФАЗА 2) для панели: цена + бонус текстом."""
    return [{"id": k, "emoji": v["emoji"], "name": v["name"], "cost": v["cost"],
             "bonus": _prep_bonus_txt(v["bonus"]), "blurb": v["blurb"]}
            for k, v in invmod.PREPS.items()]


def _prep_have(player) -> dict:
    """Инвентарь игрока по ресурсам приготовлений (для affordability на фронте)."""
    need = {r for v in invmod.PREPS.values() for r in v["cost"]}
    inv = (getattr(player, "inventory", None) or {}) if player else {}
    return {r: int(inv.get(r, 0)) for r in need}


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
    from bot.config import settings
    if invmod.TEST_MODE and uid != settings.admin_id:     # обкатка: панель — только админу
        return web.json_response({"ok": True, "active": False},
                                 headers={"Cache-Control": "no-store"})
    async with session_factory() as s:
        inv = await repo.get_active_invasion(s)
        if inv is None or inv.status != "gathering":
            return web.json_response({"ok": True, "active": False},
                                     headers={"Cache-Control": "no-store"})
        parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
        tr = invmod.trait_of(inv)
        sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv), trait=tr[0])
        me = (inv.registered or {}).get(str(uid))
        player = await repo.get_player(s, uid)     # инвентарь для приготовлений (ФАЗА 2)
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
        "preps": _preps_dto(), "my_preps": (me or {}).get("preps") or [], "have": _prep_have(player),
    }, headers={"Cache-Control": "no-store"})


async def _api_invasion_prepare(request: web.Request) -> web.Response:
    """ФАЗА 2: военное приготовление. Записавшийся боец тратит ресурсы таверны и
    усиливает свою дружину (broня/HP/урон) — раз за нашествие на вид. Списание ресурсов
    и обновление записи — атомарно в одной транзакции. Возвращает свежую готовность."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    from bot.config import settings
    if invmod.TEST_MODE and uid != settings.admin_id:
        return web.json_response({"ok": False, "error": "testing"})
    prep = str((body or {}).get("prep") or "")
    if prep not in invmod.PREPS:
        return web.json_response({"ok": False, "error": "bad_prep"})
    from bot.game import inventory as inv_res
    async with session_factory() as s:
        player = await repo.get_player(s, uid)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        inv = await repo.get_active_invasion(s)
        if inv is None or inv.status != "gathering":
            return web.json_response({"ok": False, "error": "closed"})
        rec = (inv.registered or {}).get(str(uid))
        if not rec:
            return web.json_response({"ok": False, "error": "not_registered"})
        if prep in (rec.get("preps") or []):
            return web.json_response({"ok": False, "error": "already"})
        cost = invmod.prep_cost(prep)
        if not inv_res.can_afford(player, cost):
            return web.json_response({"ok": False, "error": "not_enough"})
        new_rec = invmod.apply_prep(rec, prep)
        # атомарно: записан + сбор + prep ЕЩЁ НЕ куплен (SQL-гард от двойного списания
        # при гонке двойного тапа) → списываем ТОЛЬКО если обновление реально прошло
        ok = await repo.invasion_prepare(s, inv.id, player.id, new_rec, prep)
        if not ok:
            return web.json_response({"ok": False, "error": "already"})
        inv_res.pay(player, cost)                                         # списываем в той же транзе
        repo.add_log(s, "player", player.id, f"🛠 приготовил «{invmod.PREPS[prep]['name']}» к обороне")
        await s.commit()
        fresh = await repo.get_active_invasion(s) or inv
        parts = [dict(r, pid=int(pid)) for pid, r in (fresh.registered or {}).items()]
        tr = invmod.trait_of(fresh)
        sim = invmod.simulate(parts, seed=fresh.id, escal=invmod.escal_of(fresh), trait=tr[0])
        me = (fresh.registered or {}).get(str(uid)) or {}
    return web.json_response({
        "ok": True, "ready": round(invmod.readiness(sim), 3), "comp": invmod.composition(parts),
        "my_preps": me.get("preps") or [], "have": _prep_have(player),
    }, headers={"Cache-Control": "no-store"})


async def _api_invasion_result(request: web.Request) -> web.Response:
    """Итог последнего боя с ордой — для МОДАЛКИ РЕЗУЛЬТАТОВ (всплывает на карте
    сразу после победы/провала). Read-only; admin-gated (фича в обкатке). Отдаёт
    полную сводку по бойцам (урон/крит/блок/пал/награда) + трейт + флаг наград.
    Доступно, пока бой недавний (REPORT_WINDOW_SEC) ИЛИ время боя вышло, но нотифаер
    ещё не зарезолвил (тогда — ПРЕДСКАЗАНИЕ той же детерминированной симуляции)."""
    from bot.webapi.core import _auth, _is_admin
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not invmod.MAP_PUBLIC and not _is_admin(uid):     # обкатка: сводка боя — только админу
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        inv = await repo.latest_invasion(s)
        avail = False
        if inv is not None:
            if inv.status in ("won", "lost") and inv.resolve_at:      # зарезолвлен и недавно
                ra = inv.resolve_at if inv.resolve_at.tzinfo else inv.resolve_at.replace(tzinfo=timezone.utc)
                avail = (now - ra).total_seconds() < REPORT_WINDOW_SEC
            elif inv.status in ("gathering", "battle") and invmod.registered_count(inv) > 0 and inv.gather_until:
                # Клиент показывает бой оконченным по ВРЕМЕНИ (elapsed), а нотифаер тикает
                # раз в 60с и отстаёт — статус может ещё висеть «gathering»/«battle», хотя
                # анимация уже добила орду. Считаем конец боя сами и ПРЕДСКАЗЫВАЕМ итог (та
                # же детерминированная симуляция) — иначе модалка ловила available:false и
                # мгновенно закрывалась (показ = действие: сервер соглашается с анимацией).
                gu = (inv.gather_until if inv.gather_until.tzinfo
                      else inv.gather_until.replace(tzinfo=timezone.utc))
                parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
                rounds = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv),
                                         trait=invmod.trait_of(inv)[0])["rounds"]
                end = gu + timedelta(seconds=invmod.MARCH_SECONDS + invmod.battle_secs_for(rounds))
                avail = now >= end - timedelta(seconds=3)          # +грейс на сетевой/тактовый перекос
        if not avail:
            return web.json_response({"ok": True, "available": False},
                                     headers={"Cache-Control": "no-store"})
        ev = _invasion_report_event(inv, uid)
        tr = invmod.trait_of(inv)
        ev.update({
            "ok": True, "available": True,
            "trait": {"id": tr[0], "emoji": tr[1], "name": tr[2], "counter": tr[3], "blurb": tr[4]},
            "rewards_enabled": bool(invmod.REWARDS_ENABLED),
            "escal": round(invmod.escal_of(inv), 2),
        })
    return web.json_response(ev, headers={"Cache-Control": "no-store"})


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
        world = await repo.get_or_create_world(s)
        inv.escal = invmod.escalation(getattr(world, "orc_wins", 0))
        # болваночную армию МАСШТАБИРУЕМ под текущую эскалацию — иначе после N побед
        # мира орда толстеет (escal↑), а фикс-ростер из 16 болванок гарантированно
        # проигрывает. Растущий ростер эмулирует «город вырос вместе с угрозой» →
        # тихий тест всегда даёт играбельный бой на грани при любом orc_wins.
        inv.registered = invmod.dummy_roster(invmod.dummy_count_for(inv.escal))
        world.invasion_next_at = None                   # активна — авто не спавнит поверх
        await s.flush()                                 # нужен inv.id
        invmod.set_gathering(inv.id)
        repo.add_log(s, "admin", uid, "🪓 тихо призвал Орду (мини-апп, тест карты)")
        await s.commit()
        iid = inv.id
    return web.json_response({"ok": True, "id": iid, "gather_secs": invmod.FAST_GATHER_SECONDS},
                             headers={"Cache-Control": "no-store"})
