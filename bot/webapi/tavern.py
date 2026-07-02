"""Таверна — главный экран мини-аппа: снапшот состояния (/api/state), сбор дохода,
торг с купцом, апгрейд, панели действий, бригады, бонус дня, грамота, розница,
мельница, story-выборы и онбординг. Перенесено из bot/webapp.py дословно (move-only)."""

import json
from datetime import datetime, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import worldmap
from bot.webapi.core import (
    _AV_BY_ESTATE, _auth, _init_user, _is_admin, _npc_avatar, _verify_init_data,
    touch_seen,
)
from bot.webapi.raid import _raid_summary

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
        await repo.feed_mark_read_kind(s, uid, ["mill"])
        await s.commit()
        note = "rich" if grain >= base * 1.3 else ("mishap" if grain <= base * 0.75 else "")
        st = millmod.state(player)
    return web.json_response({"ok": True, "grain": grain, "note": note, "mill": st},
                             headers={"Cache-Control": "no-store"})


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
        "gold": int(p.gold), "income_rate": logic.income_rate_quote(p, t),
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
        "mood_line": offer.get("mood_line") or None,
        "intro": offer.get("intro"), "fv": offer.get("fv"),
        "prices": offer.get("prices"), "counter": offer.get("counter"), "choice": offer.get("choice"),
    }


async def _api_state(request: web.Request) -> web.Response:
    """Снапшот Таверны. При открытии — шанс на внезапного визитёра (story-движок),
    как в текстовом боте при заходе в таверну."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import story_engine as se, buff as buffmod
    async with session_factory() as s:
        await touch_seen(s, uid)   # апп-активность: нуджи/рейд-пуши видят игрока живым
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


async def _api_story_choice(request: web.Request) -> web.Response:
    """Резолв выбора у визитёра (story_engine.resolve): применить эффекты, записать
    летопись, эхо в общий чат (через очередь нотифаера), вернуть исход + дельты."""
    uid, body = await _auth(request)
    if uid is None:
        return body
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
        from bot.game import factions as _fac
        ranks0 = {f: _fac.rank(p, f) for f in _fac.NAMES}
        outcome, ctx = se.resolve(p, city, st, idx, now, shielded=shielded)
        if outcome is None:
            return web.json_response({"ok": False, "error": "unavailable"})
        if p.chat_id is not None:
            for line in ctx.chronicle:
                await repo.add_chronicle(s, p.chat_id, line)
            for line in ctx.chat_echo:               # эхо в группу — через очередь нотифаера
                repo.queue_notify(s, p.chat_id, line)
        repo.add_log(s, "player", p.id, f"🚪 {st.title}")
        _dg, _dr = int(p.gold) - g0, int(p.reputation or 0) - r0
        _bits = ([f"{_dg:+d} 🪙"] if _dg else []) + ([f"{_dr:+d} ⭐"] if _dr else [])
        repo.feed_push(s, uid, f"🚪 {st.title}: выбор сделан"
                       + (" — " + ", ".join(_bits) if _bits else ""), kind="story")
        for f, r1 in {f: _fac.rank(p, f) for f in _fac.NAMES}.items():
            if r1 != ranks0[f]:                      # смена ранга — громкая весть
                up = r1 > ranks0[f]
                repo.feed_push(s, uid, (
                    f"{'⚖️' if up else '🕳'} {_fac.name(f)} теперь зовёт тебя "
                    f"«{_fac.rank_label(r1)}»"
                    + (" — открылись новые милости, загляни в Репутацию."
                       if up else " — жди худших цен и косых взглядов.")), kind="rep")
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
                chance = _trade.visit_chance(
                    _bal.TRADE_FAIR_CHANCE if _wld.is_fair() else _bal.TRADE_CHANCE)
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
        st = {"result": None, "react": None, "qty": 0, "gold": 0, "unit": 0,
              "asked": 0, "short": False}

        def _finish(unit: int, kind: str, qty_cap: int | None = None) -> None:
            asked = int(offer.get("qty", 0))
            if qty_cap is not None:          # выбранный вариант вилки: ровно столько
                offer["qty"] = int(qty_cap)
            qn, gn = _sell(p, offer, unit)
            ss.set_trade(p, None)
            if qn:
                if offer.get("cit"):                 # купец запомнит сделку
                    ss.adjust_npc_rel(p, offer["cit"], 2 if kind == "accept_high" else 1)
                from bot.game import rumors
                rumors.note("trade", p, gn)          # хваткая сделка — пища для сплетен
                newbie.mark(p, "nb_sale")
                gn_name = prod.GOODS[offer["good"]].name if offer["good"] in prod.GOODS else offer["good"]
                repo.add_log(s, "player", p.id, f"🤝 продал купцу {qn}×{gn_name} за {gn} 🪙 (мини-апп)")
                market.nudge(world, offer["good"], qn * bal.MARKET_WHOLESALE_WEIGHT)
                react = trademod.reaction(offer, kind)
                # мошна не резиновая: согласился на цену, но взял меньше заявленного —
                # СКАЗАТЬ об этом прямо (иначе игрок думает, что его обсчитали)
                short = qn < min(asked, int((p.tavern.products or {}).get(offer["good"], 0)) + qn)
                if short:
                    react += f" «Мошна не резиновая — по такой цене беру {qn}, не обессудь»"
                st.update(result="sold", react=react, qty=qn, gold=gn, unit=unit,
                          asked=asked, short=short)
            else:
                st.update(result="walk", react=trademod.reaction(offer, "walk"))

        if op == "decline":
            if offer.get("cit"):                     # прогнал — купец затаит обиду
                ss.adjust_npc_rel(p, offer["cit"], -1)
            ss.set_trade(p, None)
            st.update(result="walk", react=trademod.reaction(offer, "walk"))
        elif op == "accept":                          # согласие на контр-цену
            unit = int(offer.get("counter", offer["max_unit"]))
            stock = int((p.tavern.products or {}).get(offer["good"], 0))
            want = min(int(offer.get("qty", 0)), stock)
            fork = trademod.deal_options(offer, unit, want)
            if fork:
                offer["choice"] = fork
                ss.set_trade(p, offer)
                st.update(result="choice", choice=fork,
                          react=(f"«По {fork['mine']['unit']} 🪙 утяну лишь "
                                 f"{fork['mine']['qty']}. По {fork['full']['unit']} 🪙 — "
                                 f"заберу все {fork['full']['qty']}. Решай»"))
            else:
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
                stock = int((p.tavern.products or {}).get(offer["good"], 0))
                want = min(int(offer.get("qty", 0)), stock)
                fork = trademod.deal_options(offer, unit, want)
                if fork:                      # мошна не тянет всё — честная вилка
                    offer["choice"] = fork
                    ss.set_trade(p, offer)
                    st.update(result="choice", choice=fork,
                              react=(f"«По {fork['mine']['unit']} 🪙 возьму лишь "
                                     f"{fork['mine']['qty']} — мошна не резиновая. "
                                     f"А уступишь по {fork['full']['unit']} 🪙 — "
                                     f"заберу все {fork['full']['qty']}. Ну?»"))
                else:
                    _finish(unit, "accept_high" if unit >= offer["fv"] * 1.15 else "accept")
            elif decision == "counter":
                offer["counter"] = price
                ss.set_trade(p, offer)
                st.update(result="counter", react=trademod.reaction(offer, "counter", price))
            else:
                ss.set_trade(p, None)
                st.update(result="walk", react=trademod.reaction(offer, "walk"))
        elif op == "take":                            # выбор из вилки (choice)
            fork = offer.get("choice") or {}
            variant = str(body.get("variant") or "")
            deal = fork.get(variant)
            if not deal:
                return web.json_response({"ok": False, "error": "bad"})
            kind = "accept_high" if deal["unit"] >= offer["fv"] * 1.15 else "accept"
            _finish(int(deal["unit"]), kind, qty_cap=int(deal["qty"]))
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
    from bot.game import balance as bal, buff as buffmod, logic, newbie as nb

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
            {"label": "Доход/ч",
             "frm": logic.income_rate_quote(p, t),
             "to": int(logic.income_rate_quote(p, t) / max(1, t.income_rate)
                       * ns["income_rate"])},
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
    goals, _tot = logic.expedition_goals(p, t)
    goal_list = [{"label": label,
                  "items": [{"key": r, "name": bal.RESOURCE_NAMES.get(r, r), "qty": q}
                            for r, q in short.items()]}
                 for label, short in goals]
    resources = []
    if c.free > 0:
        for res in bal.RESOURCES:
            amt = logic.expedition_gain_quote(p, t, res)   # как реальное начисление
            resources.append({"key": res, "name": bal.RESOURCE_NAMES.get(res, res), "amount": amt})
    return {"kind": "expedition", "free": c.free, "total": c.total, "out": c.out,
            "ready": c.ready, "next_minutes": c.next_minutes,
            "pay": (_q := logic.expedition_quote(p, t))[0], "hours": round(_q[1], 1),
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
        await repo.feed_mark_read_kind(s, uid, ["bonus"])
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
        await repo.feed_mark_read_kind(s, uid, ["exped"])   # весть погашена делом
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
            repo.feed_push(s, uid, f"🍻 Налил гостям: +{gold} 🪙, +{rep} ⭐", kind="retail")
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






# ===== Ночная ходка (порт bot/game/nightrun.py — соло push-your-luck) =====
# Server-authoritative: ВЕСЬ RNG (бросок Лихо, успех испытаний) — на сервере;
# фронт лишь анимирует к результату (анти-чит, как в охоте).

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




