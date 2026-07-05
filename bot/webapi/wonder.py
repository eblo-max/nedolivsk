"""Общие стройки — «Чудеса города» (Фаза 1, сервер): состояние стройки и ВКЛАД.

Вклад атомарен по lock-then-compute: лочим строку игрока (get_player for_update) и
строку чуда (get_active_wonder lock) в одной транзакции — параллельные вклады
сериализуются, без двойного списания и потери прогресса. Мульти-игроцкий
перцентильный бонус и глоб-бафф на финише доплачивает НОТИФАЕР (там нет
параллельных вкладчиков → нет дедлока). См. docs/wonders.md.
"""

from datetime import datetime, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import wonder as wmod
from bot.webapi.core import _auth, _is_admin, touch_seen


def _gated(uid: int) -> bool:
    """Обкатка: стройка доступна только админу (WONDER_ADMIN_ONLY)."""
    return wmod.WONDER_ADMIN_ONLY and not _is_admin(uid)


def _wonder_dto(w, pid: int) -> dict:
    """Снимок стройки для экрана: чудо, фаза, прогресс/цель, твой вклад+зодары, доска."""
    wdef = wmod.get(w.key)
    phases = [{"key": p.key, "title": p.title} for p in (wdef.phases if wdef else [])]
    ph = int(w.phase)
    contribs = w.contributions or {}
    mine = contribs.get(str(pid)) or {}
    board = sorted(
        ({"name": c.get("name", "Зодчий"), "pts": int(c.get("pts", 0)),
          "zodar": int(c.get("zodar", 0))}
         for c in contribs.values() if int(c.get("pts", 0)) > 0),
        key=lambda x: -x["pts"])[:10]
    target = max(1, int(w.target))
    return {
        "key": w.key, "name": wdef.name if wdef else w.key,
        "emoji": wdef.emoji if wdef else "🏛", "blurb": wdef.blurb if wdef else "",
        "bonus": wdef.bonus if wdef else "", "sprite": wdef.sprite if wdef else "",
        "phase": ph, "phases": phases,
        "phase_title": phases[ph - 1]["title"] if 0 < ph <= len(phases) else "",
        "progress": int(w.progress), "target": int(w.target),
        "pct": min(100, round(int(w.progress) * 100 / target)),
        "status": w.status, "sealed": w.status in ("sealing", "done"),
        "mine_pts": int(mine.get("pts", 0)), "mine_zodar": int(mine.get("zodar", 0)),
        "board": board, "contributors": len(board),
    }


def _stock(p) -> dict | None:
    """Что игрок может НЕСТИ в стройку: сырьё (инвентарь), блюда (погреб), золото."""
    if p is None or p.tavern is None:
        return None
    from bot.game import balance as bal, production as prod
    inv = p.inventory or {}
    prods = p.tavern.products or {}
    return {
        "gold": int(p.gold),
        "res": [{"key": k, "name": bal.RESOURCE_NAMES.get(k, k), "qty": int(inv.get(k, 0))}
                for k in bal.RESOURCES if int(inv.get(k, 0)) > 0],
        "goods": [{"key": k, "name": prod.GOODS[k].name, "qty": int(v)}
                  for k, v in prods.items() if int(v) > 0 and k in prod.GOODS],
    }


async def _api_wonder(request: web.Request) -> web.Response:
    """Состояние текущей стройки (или её отсутствие) + баланс зодаров + склад. Чтение."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if _gated(uid):                                    # обкатка: не админ — «ничего не строят»
        return web.json_response({"ok": True, "wonder": None, "zodar": 0, "stock": None},
                                 headers={"Cache-Control": "no-store"})
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
        zodar = int(getattr(p, "zodar", 0) or 0) if p else 0
        w = await repo.get_active_wonder(s)
        dto = _wonder_dto(w, uid) if w is not None else None
        stock = _stock(p)
    return web.json_response({"ok": True, "wonder": dto, "zodar": zodar,
                              "stock": stock}, headers={"Cache-Control": "no-store"})


async def _api_wonder_contribute(request: web.Request) -> web.Response:
    """Вложить сырьё/блюда/золото в стройку → очки по ценности → зодары (с дневной
    убыв. отдачей и переносом остатка). Атомарно под локом игрока И чуда."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if _gated(uid):
        return web.json_response({"ok": False, "error": "closed"})
    from bot.game import (balance as bal, economy, inventory as invmod,
                          production as prod)
    items = body.get("items")
    if not isinstance(items, dict):
        return web.json_response({"ok": False, "error": "bad"})
    async with session_factory() as s:
        # ПОРЯДОК ЛОКОВ: чудо → игрок (тот же, что settle в нотифаере). Инверсия
        # (игрок→чудо) дала бы дедлок с доплатой бонуса. touch_seen (UPDATE игрока)
        # — только ПОСЛЕ лока чуда, иначе игрок лочится раньше чуда.
        w = await repo.get_active_wonder(s, lock=True)
        if w is None or w.status != "building":
            return web.json_response({"ok": False, "error": "no_wonder"})
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        await touch_seen(s, uid)                       # вкладчик — активен (игрок уже залочен)

        # нормализуем вклад: только сырьё/блюда/золото, обрезаем по наличию
        prods = dict(p.tavern.products or {})
        give: dict[str, int] = {}
        for k, qty in items.items():
            q = int(qty or 0)
            if q <= 0:
                continue
            if k == "gold":
                q = min(q, int(p.gold))
            elif k in prod.GOODS:
                q = min(q, int(prods.get(k, 0)))
            elif k in bal.RESOURCES:
                q = min(q, invmod.get(p, k))
            else:
                continue                                # чужой ключ — игнор
            if q > 0:
                give[k] = q
        raw = wmod.item_points(give)
        if raw <= 0:
            return web.json_response({"ok": False, "error": "empty"})

        # списываем ровно то, что зачли в очки
        gold_spent = 0
        for k, q in give.items():
            if k == "gold":
                p.gold -= q
                gold_spent = q
            elif k in prod.GOODS:
                prods[k] = int(prods.get(k, 0)) - q
            else:
                invmod.add(p, k, -q)
        p.tavern.products = prods
        if gold_spent:
            economy.record(p, "wonder", -gold_spent)

        # дневной учёт очков (для убыв. отдачи), окно — UTC-сутки
        today = datetime.now(timezone.utc).date().isoformat()
        st = dict(p.story or {})
        wd = st.get("wonder_day") or {}
        today_before = int(wd.get("pts", 0)) if wd.get("d") == today else 0
        eff = wmod.effective_points(raw, today_before)
        st["wonder_day"] = {"d": today, "pts": today_before + raw}
        p.story = st

        active = await repo.active_player_count(s)
        old_phase = int(w.phase)
        res = wmod.apply_contribution(w, str(p.id), p.first_name or "Зодчий",
                                      raw, eff, active)
        w.updated_at = datetime.now(timezone.utc)
        p.zodar = int(getattr(p, "zodar", 0) or 0) + int(res["award"])
        repo.add_log(s, "player", p.id,
                     f"🏛 вложил в стройку {raw} ценности (+{res['award']} ⚒)")
        if res["capstone"] and not res["wonder_done"]:
            wdef = wmod.get(w.key)
            title = (wdef.phases[old_phase - 1].title
                     if wdef and 0 < old_phase <= len(wdef.phases) else "фазы")
            repo.feed_push(s, uid, f"🧱 Ты заложил последний камень: «{title}»! "
                                   f"Артель это запомнит.", kind="wonder")
        await s.commit()
        out = {"ok": True, "award": int(res["award"]),
               "phase_done": bool(res["phase_done"]),
               "wonder_done": bool(res["wonder_done"]),
               "capstone": bool(res["capstone"]),
               "wonder": _wonder_dto(w, uid), "zodar": p.zodar, "stock": _stock(p)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})
