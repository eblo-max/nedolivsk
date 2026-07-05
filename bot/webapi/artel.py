"""Лавка Артели зодчих (Фаза 2): каталог наград за зодары и покупка.

Покупка атомарна под локом строки игрока (get_player for_update) — двойной тап
не спишет дважды и не купит одно дважды. Зодар — bind-on-earn, не золото → в
faucet/sink-учёт НЕ пишем (это не эмиссия/сжигание золота). См. docs/wonders.md.
"""

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import artel_shop
from bot.game import wonder as wmod
from bot.webapi.core import _auth, _is_admin


def _gated(uid: int) -> bool:
    """Обкатка: Лавка Артели — только админу (тот же флаг, что и стройка)."""
    return wmod.WONDER_ADMIN_ONLY and not _is_admin(uid)


def _state(p) -> dict:
    return {"ok": True, "zodar": int(getattr(p, "zodar", 0) or 0) if p else 0,
            "catalog": artel_shop.catalog_dto(p) if p else []}


async def _api_artel(request: web.Request) -> web.Response:
    """Каталог Лавки + баланс зодаров игрока (что куплено / по карману). Чтение."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if _gated(uid):
        return web.json_response({"ok": True, "zodar": 0, "catalog": []},
                                 headers={"Cache-Control": "no-store"})
    async with session_factory() as s:
        p = await repo.get_player(s, uid)
    return web.json_response(_state(p), headers={"Cache-Control": "no-store"})


async def _api_artel_buy(request: web.Request) -> web.Response:
    """Купить награду за зодары — атомарно под локом игрока."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if _gated(uid):
        return web.json_response({"ok": False, "error": "closed"})
    item_id = str(body.get("id") or "")
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None:
            return web.json_response({"ok": False, "error": "no_player"})
        r = artel_shop.get(item_id)
        if r is None:
            return web.json_response({"ok": False, "error": "bad"})
        if artel_shop.owns(p, r):
            return web.json_response({"ok": False, "error": "owned", **_state(p)})
        if int(getattr(p, "zodar", 0) or 0) < r.cost:
            return web.json_response({"ok": False, "error": "not_enough", **_state(p)})
        p.zodar = int(p.zodar) - r.cost           # зодар — не золото: не в econ-учёт
        artel_shop.apply(p, r)
        repo.add_log(s, "player", p.id,
                     f"⚒ Лавка Артели: {r.name} (−{r.cost} ⚒)")
        await s.commit()
        out = {"ok": True, "bought": r.id, **_state(p)}
    return web.json_response(out, headers={"Cache-Control": "no-store"})
