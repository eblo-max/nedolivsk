"""Персонаж и кузница: статы/снаряга, ковка, лечение, забор вещи.
Перенесено из bot/webapp.py дословно (move-only)."""

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth

_GAIN_ICO = {"damage": "⚔", "crit": "💥%", "armor": "🛡", "luck": "🍀", "vitality": "❤"}


def _gain_str(g: dict) -> str:
    """{'armor': 1, 'luck': 1} → «+1 🛡 · +1 🍀» (что даст уровень заточки)."""
    parts = []
    for k, v in g.items():
        ico = _GAIN_ICO.get(k, k)
        parts.append(f"+{v} {ico.rstrip('%')}" + ("%" if ico.endswith("%") else ""))
    return " · ".join(parts)


def _character_state(p) -> dict:
    """Состояние Персонажа для мини-аппа — статы/снаряжение/кузница из тех же
    функций бота (items/combat/logic)."""
    from bot.game import balance as bal, combat, items as it, logic

    eq = p.equipment or {}
    cs = combat.player_stats(p)          # ЕДИНЫЙ каркас: уровень, кап брони, бафы
    dmg = bal.BASE_DAMAGE + cs["damage"] + bal.LEVEL_DAMAGE * cs["level"]
    crit = min(bal.HUNT_CRIT_CAP, cs["crit"])   # крит развязан с удачей (везде)

    slots = []
    for slot_key, slot_name in it.SLOTS.items():
        entry = eq.get(slot_key)
        item = it.CATALOG.get(it.parse_entry(entry)[0]) if entry else None
        if item:
            _, tier, plus, _aff = it.parse_full(entry)
            row = {"slot": slot_key, "slot_name": slot_name, "id": item.id,
                   "name": it.display_name(entry), "tier": tier,
                   "sprite": item.sprite or item.id, "trophy": not item.craftable,
                   "plus": plus}
            gain_nxt = it.item_combat_gain(entry, plus + 1) if plus < it.PLUS_MAX else {}
            if gain_nxt:                          # точить есть смысл (боевые статы)
                nxt = plus + 1
                row["sharpen"] = {
                    "next": nxt,
                    "cost": int(bal.SHARPEN_COST_GOLD[nxt] * it.TIER_ECON_MULT[tier]),
                    "chance": int(bal.SHARPEN_SUCCESS[nxt] * 100),
                    "gain": _gain_str(gain_nxt),
                }
            slots.append(row)
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
    hp_cur, hp_max = combat.current_hp(p), combat.max_hp(p)
    prods = (p.tavern.products if p.tavern else None) or {}
    heal_opts = [{"key": k, "name": prod.GOODS[k].name, "emoji": prod.GOODS[k].emoji,
                  "hp": combat.heal_amount(p, k), "qty": int(prods.get(k, 0))}
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
            for k, v in it.craft_cost(p, item, nxt).items():
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
           if i.craftable and not (i.id in it.REGION_GEAR and it.REGION_GEAR[i.id] != p.region)
           and not it.wonder_gear_locked(p, i.id)]   # эксклюзив зодчих виден лишь с рецептом
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


async def _api_sharpen(request: web.Request) -> web.Response:
    """Заточить надетую вещь: золото сгорает всегда, уровень растёт по шансу."""
    import random
    from bot.game import balance as bal, items as it

    uid, body = await _auth(request)
    if uid is None:
        return body
    slot = str((body or {}).get("slot") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None:
            return web.json_response({"ok": False, "error": "no_player"})
        eq = dict(p.equipment or {})
        entry = eq.get(slot)
        if not entry:
            return web.json_response({"ok": False, "error": "empty_slot"})
        item_id, tier, plus, aff = it.parse_full(entry)
        if plus >= it.PLUS_MAX:
            return web.json_response({"ok": False, "error": "max"})
        nxt = plus + 1
        cost = int(bal.SHARPEN_COST_GOLD[nxt] * it.TIER_ECON_MULT[tier])
        if (p.gold or 0) < cost:
            return web.json_response({"ok": False, "error": "gold", "cost": cost})
        p.gold -= cost                             # плата кузнецу — в обе стороны
        from bot.game import economy
        economy.record(p, "sharpen", -cost)
        success = random.random() < bal.SHARPEN_SUCCESS[nxt]
        if success:
            eq[slot] = it.make_entry(item_id, tier, nxt, aff)
            p.equipment = eq
        repo.add_log(s, "player", p.id,
                     f"⚒ заточка {it.display_name(eq[slot])}: "
                     f"{'удача' if success else 'сорвалась'} (−{cost} 🪙)")
        await s.commit()
        gain = _gain_str(it.item_combat_gain(entry, nxt)) if success else ""
        return web.json_response({
            "ok": True, "success": success, "plus": nxt if success else plus,
            "gold": int(p.gold), "name": it.display_name(eq[slot]),
            "gain": gain,
        }, headers={"Cache-Control": "no-store"})


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
        await repo.feed_mark_read_kind(s, uid, ["craft"])
        await s.commit()
        ch, fg = _character_state(p), _forge_state(p)
    return web.json_response({"ok": True, "character": ch, "forge": fg,
                              "item": r.item.name, "tier": r.tier},
                             headers={"Cache-Control": "no-store"})


# ===== Пристройки + Производство (порт bot/handlers/buildings.py) =====
