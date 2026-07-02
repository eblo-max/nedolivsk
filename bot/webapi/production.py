"""Двор таверны: пристройки, стройка, производство (пивоварня/кухня/выдержка…)
и охота (бой со зверьём). Перенесено из bot/webapp.py дословно (move-only)."""

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth

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
    "upyr": "skeleton", "ogr": "golem", "wyvern": "dragon", "lich": "skeleton",
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
    chp, mhp = combat.current_hp(p), combat.max_hp(p)
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
                  "hp": combat.heal_amount(p, k), "qty": int(prods.get(k, 0))}
                 for k in bal.HEAL_VALUES if k in prod.GOODS and int(prods.get(k, 0)) > 0]
    return {
        "ok": True,
        "hp": {"cur": chp, "max": mhp, "regen": combat.regen_full_minutes(p)},
        "ready": {"can": ready, "minutes": mins},
        "stats": {"damage": (bal.BASE_DAMAGE + stats.get("damage", 0)
                             + bal.LEVEL_DAMAGE * stats.get("level", 0)),
                  "crit": min(bal.HUNT_CRIT_CAP, stats.get("crit", 0)),
                  "armor": stats.get("armor", 0), "luck": stats.get("luck", 0)},
        "heal": {"can": chp < mhp, "full": chp >= mhp, "options": heal_opts},
        "flask": {"slots": bal.FLASK_SLOTS, "options": [
            {"key": k, "name": prod.GOODS[k].name, "emoji": prod.GOODS[k].emoji,
             "label": bal.FLASK_EFFECTS[k]["label"], "qty": int(prods.get(k, 0))}
            for k in bal.FLASK_EFFECTS
            if k in prod.GOODS and int(prods.get(k, 0)) > 0]},
        "beasts": beasts,
    }


async def _api_hunt_forecast(request: web.Request) -> web.Response:
    """Живой прогноз боя С УЧЁТОМ выбранной фляги (dry-run, порции не списываются):
    «что в прогнозе — то и в бою», включая выпитое."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import balance as bal, combat
    eid = str(body.get("id") or "")
    flask = [str(k) for k in (body.get("flask") or [])][:bal.FLASK_SLOTS]
    enemy = combat.ENEMY.get(eid)
    if enemy is None:
        return web.json_response({"ok": False, "error": "unknown"})
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        stats = combat.player_stats(p)
        chp = combat.current_hp(p)
        chp, _used, labels = combat.flask_apply(p, flask, stats, chp, consume=False)
        win, est = combat.forecast(stats, enemy, chp)
    return web.json_response({"ok": True, "win": win, "est_hp": est, "flask": labels},
                             headers={"Cache-Control": "no-store"})


# Охота ВРЕМЕННО закрыта на обкатку боевого пересмотра (плашка в мини-аппе).
# Админ видит всё — тестирует новые полосы. Открыть всем: HUNT_CLOSED = False.
HUNT_CLOSED = False
HUNT_CLOSED_NOTE = ("Ловчие переучиваются: большое обновление механики и новых "
                    "фич боёвки. Доска розыска откроется в течение 3 часов.")


async def _api_hunt(request: web.Request) -> web.Response:
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.webapi.core import _is_admin
    if HUNT_CLOSED and not _is_admin(uid):
        return web.json_response({"ok": True, "closed": True, "note": HUNT_CLOSED_NOTE},
                                 headers={"Cache-Control": "no-store"})
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
    from bot.webapi.core import _is_admin
    if HUNT_CLOSED and not _is_admin(uid):
        return web.json_response({"ok": False, "error": "closed"})
    from bot.game import balance as bal, combat, production as prod
    eid = str(body.get("id") or "")
    flask = [str(k) for k in (body.get("flask") or [])][:bal.FLASK_SLOTS]
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        chp0 = combat.current_hp(p)                  # HP на старте — для шкалы анимации
        res = combat.hunt(p, eid, flask=flask)
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
        "player_hp0": chp0, "hp_max": combat.max_hp(p), "rounds": res.fight.log,
        "flask": res.flask or [],
        "rounds_n": res.fight.rounds, "crits": res.fight.crits, "overwhelmed": res.fight.overwhelmed,
        "loot": {"gold": (res.loot or {}).get("gold", 0) if res.fight.win else 0, "res": loot_res,
                 "trophies": (res.loot or {}).get("trophies", []) if res.fight.win else [],
                 "rep": (res.loot or {}).get("rep", 0) if res.fight.win else 0},
        "gold_lost": res.gold_lost, "hp_now": res.hp_now, "hunt": hunt,
    }, headers={"Cache-Control": "no-store"})

