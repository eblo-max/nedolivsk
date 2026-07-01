"""Общая инфраструктура HTTP-API: аутентификация initData, admin-гейт, base_url,
держатель aiogram-бота. Перенесено из bot/webapp.py дословно (move-only)."""

import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web

_INITDATA_MAX_AGE = 24 * 3600

_authlog = logging.getLogger("webapp.auth")

_BOT = None   # aiogram-Bot из main (один event-loop) — для рассылки в чаты из эндпоинтов


def set_bot(bot) -> None:
    """Запомнить экземпляр бота (зовёт run_webapp при старте)."""
    global _BOT
    _BOT = bot


def get_bot():
    """aiogram-Bot или None (до старта/в тестах)."""
    return _BOT


def _verify_init_data(init_data: str) -> int | None:
    """Проверить Telegram WebApp initData (HMAC-SHA256 по токену бота). Возвращает
    user_id, если подпись верна и свежая, иначе None. Это аутентификация запросов
    с карты (без неё нельзя доверять, кто регистрируется).

    На каждый отказ — лог с причиной (empty/no-hash/expired/bad-hash) и НЕдоверенным
    uid из user (для диагностики «у игрока пустая initData → видит демо-таверну»)."""
    from bot.config import settings
    if not init_data:
        _authlog.warning("auth fail: empty initData")
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        recv = pairs.pop("hash", None)
        try:                                  # untrusted — только для лога
            _uid_dbg = json.loads(pairs.get("user", "{}")).get("id")
        except (ValueError, TypeError):
            _uid_dbg = None
        if not recv:
            _authlog.warning("auth fail: no hash (uid~%s)", _uid_dbg)
            return None
        age = abs(time.time() - int(pairs.get("auth_date", "0")))
        if age > _INITDATA_MAX_AGE:
            _authlog.warning("auth fail: expired %ss (uid~%s)", int(age), _uid_dbg)
            return None
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv):
            _authlog.warning("auth fail: bad hash (uid~%s)", _uid_dbg)
            return None
        user = json.loads(pairs.get("user", "{}"))
        uid = user.get("id")
        if not uid:
            _authlog.warning("auth fail: no user.id")
            return None
        return int(uid)
    except (ValueError, KeyError, TypeError) as e:
        _authlog.warning("auth fail: parse %r", e)
        return None


async def _auth(request: web.Request):
    """Разобрать тело + проверить initData. -> (uid, body) | (None, Response-ошибка)."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    uid = _verify_init_data(body.get("initData") or "")
    if not uid:
        return None, web.json_response({"ok": False, "error": "auth"}, status=401)
    return uid, body


def _init_user(init_data: str) -> dict:
    """Имя/username из (уже проверенного) initData — для создания игрока в онбординге."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        u = json.loads(pairs.get("user", "{}"))
        return {"first_name": u.get("first_name"), "username": u.get("username")}
    except (ValueError, TypeError):
        return {}


def _is_admin(uid: int) -> bool:
    from bot.config import settings
    return uid == settings.admin_id


# Аватары NPC мини-аппа (карточка визитёра, реплики аукциона): фикс для именных
# персонажей, иначе стабильный выбор из пула сословия по хэшу id.
_AV_BY_ESTATE = {
    "nobles": [4, 8, 19, 1], "clergy": [3, 14, 7], "merchants": [19, 5, 18, 20],
    "guild": [5, 12, 18, 20, 9], "watch": [1, 6, 13, 4], "thieves": [16, 11, 15, 2],
    "peasants": [7, 12, 17, 9], "vagrants": [16, 17, 2, 15], "oddballs": [11, 14, 2, 6],
}
_AV_FIXED = {
    "countess": 10, "dowager": 10, "nun_smirenna": 10, "paraska": 10, "milkmaid": 10,
    "herbalist_zel": 10, "vedma": 11, "fortunet_rask": 11,
    "magnat": 19, "duke_pompad": 19, "heir_prozhig": 8, "baron_darm": 8,
}


def _npc_avatar(npc_id: str | None, estate: str | None) -> int | None:
    if not npc_id:
        return None
    if npc_id in _AV_FIXED:
        return _AV_FIXED[npc_id]
    pool = _AV_BY_ESTATE.get(estate or "")
    if not pool:
        return None
    return pool[sum(ord(c) for c in npc_id) % len(pool)]


def base_url() -> str:
    """Публичный https-адрес Mini App (для кнопки web_app). Из WEBAPP_BASE_URL,
    иначе из RAILWAY_PUBLIC_DOMAIN. Пусто → кнопку карты не показываем."""
    from bot.config import settings
    b = (getattr(settings, "webapp_base_url", "") or "").strip()
    if not b:
        dom = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if dom:
            b = f"https://{dom}"
    return b.rstrip("/")
