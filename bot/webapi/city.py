"""Городская социалка: репутация (фракции/горожане), летопись, зазывала
(рефералка). Перенесено из bot/webapp.py дословно (move-only)."""

from datetime import datetime, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth, _chron_ago, _npc_avatar

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
            r = factions.rank_of(v)
            facs.append({"id": fid, "name": factions.name(fid), "emoji": _FAC_EMOJI.get(fid, "•"),
                         "value": v, "rank": label, "tone": tone,
                         "rank_n": r, "rank_title": factions.rank_label(r),
                         "perks": factions.perk_lines(p, fid),
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
        rows = (await s.execute(          # None → летопись общего мирового города
            select(Chronicle.text, Chronicle.ts)
            .where(Chronicle.chat_id == repo.player_city_id(p))
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


