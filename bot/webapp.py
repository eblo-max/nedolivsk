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
from datetime import datetime, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import worldmap

ASSETS_DIR = worldmap.ASSETS_DIR
# Собранный React-мини-апп (Vite → miniapp/dist; собирается в Docker, отдаётся под /app).
MINIAPP_DIST = pathlib.Path(__file__).resolve().parent.parent / "miniapp" / "dist"

# Аутентификация/гейты/держатель бота — вынесены в bot/webapi/core.py (распил
# монолита, move-only). Импорт сюда = ре-экспорт для внешних потребителей.
from bot.webapi.core import (  # noqa: E402,F401 — фасад
    _INITDATA_MAX_AGE, _auth, _init_user, _is_admin, _verify_init_data,
    base_url, get_bot, set_bot,
)


# Старая карта/Орда — bot/webapi/invasion.py (распил, move-only).
from bot.webapi.invasion import (  # noqa: E402,F401 — фасад
    _api_invasion_join, _api_taverns, _invasion_event, _invasion_report_event,
)


# ── Рейд-босс (мини-апп): перенос боёвки из чата 1:1 ─────────────────────────
# Жизненный цикл (спавн → сбор → битва → уход) крутит НОТИФАЕР — здесь только
# чтение состояния и действия игрока (записаться/бить). Боевую логику НЕ дублируем:
# зовём raid.resolve_hit/settle и handlers.raid._drop_apply — те же, что и в чате.
# Рейд-босс — bot/webapi/raid.py (распил, move-only). RAID_REPORT_SEC и dto
# ре-экспортируются: их читает нотифаер-цикл и старые тесты.
from bot.webapi.raid import (  # noqa: E402,F401 — фасад
    RAID_REPORT_SEC, _api_raid, _api_raid_hit, _api_raid_join, _api_raid_seed,
    _api_raid_summon, _raid_dto, _raid_report_dto, _raid_start_if_due,
    _raid_summary,
)


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


# Уведомления мини-аппа — bot/webapi/notifications.py (распил, move-only).
from bot.webapi.notifications import (  # noqa: E402,F401 — фасад
    _api_notifications, _api_notifications_read, _api_notifications_seed_all,
    _api_notifications_seed_patchnote,
)
# NPC-аватары и «N назад» — bot/webapi/core.py (нужны стори-блоку и лентам).
from bot.webapi.core import _AV_BY_ESTATE, _chron_ago, _npc_avatar  # noqa: E402,F401 — фасад


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


# Персонаж/кузница — bot/webapi/character.py (распил, move-only).
from bot.webapi.character import (  # noqa: E402,F401 — фасад
    _api_character, _api_craft_claim, _api_forge, _api_forge_make, _api_heal,
)


# Двор/производство/охота — bot/webapi/production.py (распил, move-only).
from bot.webapi.production import (  # noqa: E402,F401 — фасад
    _api_brew_age, _api_build_start, _api_building, _api_buildings, _api_hunt,
    _api_hunt_fight, _api_prod_claim, _api_prod_start,
)


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
