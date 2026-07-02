"""Ночная ходка (push-your-luck вылазка): состояние, старт, выборы, встречи,
кубик, банк. Перенесено из bot/webapp.py дословно (move-only)."""

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth

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
    from bot.game import production as prodm
    from bot.config import settings
    cd = 0 if p.id == settings.admin_id else nr.cooldown_left(p)   # админ — без кулдауна (тест)
    run = p.night_run or {}
    s = combat.player_stats(p)
    base = {"ok": True, "cooldown": cd, "active": nr.is_active(run),
            "max_legs": bal.NIGHTRUN_LEGS,
            "stats": {"armor": s.get("armor", 0), "luck": s.get("luck", 0)}}
    if not nr.is_active(run):
        base["run"] = None
        # фляга на дорожку: что есть в погребе (глоток красит подход на всю ночь)
        prods = (p.tavern.products if p.tavern else None) or {}
        base["flask"] = [
            {"key": k, "name": prodm.GOODS[k].name, "emoji": prodm.GOODS[k].emoji,
             "hint": hint, "qty": int(prods.get(k, 0))}
            for k, hint in (("ale1", "смелее в драке"), ("ale2", "смелее в драке"),
                            ("ale3", "смелее в драке"), ("mead", "легче тишком"),
                            ("wine", "фарт в лихо"), ("sbiten", "гасит дурноту города"))
            if k in prodm.GOODS and int(prods.get(k, 0)) > 0]
        return base
    st = run.get("state")
    r = {"leg": run["leg"], "state": st, "hp": run["hp"],
         "hp_max": run.get("hp_max", bal.BASE_HP),
         "satchel": _nr_items(run.get("satchel")),
         "satchel_value": nr.satchel_value(run.get("satchel")),
         "situation": run.get("situation"), "can_push": nr.can_push(run),
         "flask_drunk": run.get("flask") or [],
         "rest_heal": nr.rest_heal_amount(run),
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
        keys = [str(k) for k in ((body or {}).get("flask") or [])]
        used: list[str] = []
        if keys:                                    # глоток на дорожку — из погреба
            from bot.game import combat as cb
            _, used, _ = cb.flask_apply(p, keys, {}, 0)
        p.night_run = nr.start(p, p.region or "", situation=situation, flask=used)
        repo.add_log(s, "player", p.id, "🌙 ушёл в ночную ходку"
                     + (f" (фляга: {len(used)} порц.)" if used else ""))
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

