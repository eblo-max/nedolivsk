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

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap
from bot.game import invasion as invmod

ASSETS_DIR = worldmap.ASSETS_DIR

# initData живёт сутки — отсекаем устаревшие/реплей.
_INITDATA_MAX_AGE = 24 * 3600


def _verify_init_data(init_data: str) -> int | None:
    """Проверить Telegram WebApp initData (HMAC-SHA256 по токену бота). Возвращает
    user_id, если подпись верна и свежая, иначе None. Это аутентификация запросов
    с карты (без неё нельзя доверять, кто регистрируется)."""
    from bot.config import settings
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        recv = pairs.pop("hash", None)
        if not recv:
            return None
        if abs(time.time() - int(pairs.get("auth_date", "0"))) > _INITDATA_MAX_AGE:
            return None
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv):
            return None
        user = json.loads(pairs.get("user", "{}"))
        uid = user.get("id")
        return int(uid) if uid else None
    except (ValueError, KeyError, TypeError):
        return None


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
        sim = invmod.simulate(parts, seed=inv.id)
        plan = invmod.settle(inv, sim)
        report = invmod.build_report(inv, sim, plan)
        won, rounds, n = sim["won"], sim["rounds"], sim["n"]
        ohl, ohm = sim["orc_hp_left"], sim["orc_hp_max"]
    rows = [{k: v for k, v in r.items() if k != "pid"}
            | {"mine": bool(uid) and int(r.get("pid", 0)) == uid} for r in report]
    return {
        "id": inv.id, "sprite": inv.sprite, "x": invmod.POS[0], "y": invmod.POS[1],
        "name": invmod.NAME, "blurb": "Итог битвы с ордой орков",
        "report": True, "won": bool(won), "status": inv.status,
        "rounds": int(rounds or 0), "n": int(n or 0),
        "orc_hp_left": int(ohl or 0), "orc_hp_max": int(ohm or 1), "rows": rows,
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
    parts = [dict(r, pid=int(pid)) for pid, r in (inv.registered or {}).items()]
    sim = invmod.simulate(parts, seed=inv.id)
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
    }

# Самостоятельные анимированные ивент-объекты на карте (НЕ связаны с рейдами).
# Каждый: sprite (орк 1..3), норм. позиция x/y (на суше!), имя и описание.
# Список — чтобы легко добавлять новые ивенты. Полная механика — отдельно, позже.
MAP_EVENTS = [
    {"sprite": 1, "x": 0.62, "y": 0.16,
     "name": "Орда орков",
     "blurb": "Дикая орда встала лагерем в северных снегах. Зреет буря."},
]


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


async def _api_taverns(request: web.Request) -> web.Response:
    # uid — telegram-id зрителя (из initDataUnsafe), чтобы подсветить ЕГО таверну.
    # Чужие id наружу НЕ отдаём (приватность) — только флаг mine у своей.
    try:
        uid = int(request.query.get("uid", "0"))
    except ValueError:
        uid = 0
    async with session_factory() as s:
        rows = await repo.get_map_taverns(s)
        latest = await repo.latest_invasion(s)
    now = datetime.now(timezone.utc)
    live = latest if (latest and latest.status in ("gathering", "battle")) else None
    report_inv = None
    # время боя ВЫШЛО (now ≥ resolve_at) → показываем сводку СРАЗУ (предсказанием),
    # не дожидаясь, пока нотифаер переключит статус/зарезолвит (лаг до тика ~60с).
    # Важно: НЕ только при status=='battle' — нотифаер мог ещё не флипнуть gathering→battle.
    if live is not None:
        # реальный конец боя = сбор + марш + раунды×темп (из той же симуляции, что и
        # анимация). НЕ полагаемся на resolve_at: при спавне он = дефолт, а нотифаер
        # уточняет его лишь на тике (лаг ≤60с) — иначе сводка отставала бы от полоски.
        end = None
        if invmod.registered_count(live) > 0 and live.gather_until:
            gu = (live.gather_until if live.gather_until.tzinfo
                  else live.gather_until.replace(tzinfo=timezone.utc))
            parts = [dict(r, pid=int(pid)) for pid, r in (live.registered or {}).items()]
            rounds = invmod.simulate(parts, seed=live.id)["rounds"]
            end = gu + timedelta(seconds=invmod.MARCH_SECONDS + invmod.battle_secs_for(rounds))
        elif live.resolve_at:
            end = (live.resolve_at if live.resolve_at.tzinfo
                   else live.resolve_at.replace(tzinfo=timezone.utc))
        if end is not None and now >= end:
            report_inv, live = live, None
    # уже зарезолвлен и недавно — показываем сводку из снимка
    if live is None and report_inv is None and latest and latest.status in ("won", "lost") and latest.resolve_at:
        ra = latest.resolve_at
        if ra.tzinfo is None:
            ra = ra.replace(tzinfo=timezone.utc)
        if (now - ra).total_seconds() < REPORT_WINDOW_SEC:
            report_inv = latest
    out = []
    for tav, pl in rows:
        # Со слотом — фикс. позиция; без слота (зона полна) — детерминированная
        # по региону: на интерактивной карте лимита нет, видны ВСЕ таверны.
        pos = (worldmap.slot_norm_pos(tav.map_slot) if tav.map_slot is not None
               else worldmap.region_point(pl.region or "", pl.id))
        if pos is None:
            continue
        out.append({
            "x": round(pos[0], 4), "y": round(pos[1], 4),
            "name": tav.name or pl.first_name or "Таверна",
            "level": tav.level, "region": pl.region or "",
            "tier": worldmap.sprite_tier(tav.level),   # какой спрайт-здание рисовать
            "mine": bool(uid) and pl.id == uid,
        })
    # Живой ивент (реальный таймлайн) > свежая сводка боя > статичный маркер орды.
    if live is not None:
        events = [_invasion_event(live, uid)]
    elif report_inv is not None:
        events = [_invasion_report_event(report_inv, uid)]
    else:
        events = MAP_EVENTS
    return web.json_response(
        {"taverns": out, "regions": balance.REGIONS, "events": events},
        headers={"Cache-Control": "no-store"})


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
                                 combat.player_stats(player))
        if not already:
            ok = await repo.invasion_register(s, inv.id, player.id, rec)
            if ok:
                repo.add_log(s, "player", player.id, "⚔️ поднял войско (с карты)")
                await s.commit()
            else:
                already = True
    out = {"role": rec["role"], "dmg": round(rec["dmg"]), "crit": rec["crit"],
           "armor": rec["armor"], "dodge": rec["dodge"], "hp": rec["hp"],
           "x": rec["tx"], "y": rec["ty"], "already": already}
    out["ok"] = True
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def _map_page(request: web.Request) -> web.Response:
    return web.Response(text=_MAP_HTML, content_type="text/html")


async def _world_png(request: web.Request) -> web.Response:
    return web.FileResponse(worldmap.MAP_FILE)


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
        raise web.HTTPNotFound()
    if not 1 <= n <= 9:
        raise web.HTTPNotFound()
    body = _trimmed_sprite_png(n)
    if body is None:
        raise web.HTTPNotFound()
    return web.Response(body=body, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


_EVENT_ANIMS = {"idle", "hurt", "die", "attack", "walk", "run"}


async def _event_sprite(request: web.Request) -> web.Response:
    # Стрип-анимация орка-ивента: ork{n}_{anim}.png — 10 кадров в ряд (AnimatedSprite).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    anim = request.match_info.get("anim", "idle")
    if not (1 <= n <= 3) or anim not in _EVENT_ANIMS:
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "boss" / f"ork{n}_{anim}.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _hero_sprite(request: web.Request) -> web.Response:
    # Стрип-анимация героя-воина (1..3): hero{n}_{anim}.png — войска из таверн.
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    anim = request.match_info.get("anim", "walk")
    if not (1 <= n <= 6) or anim not in _EVENT_ANIMS:
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "heroes" / f"hero{n}_{anim}.png"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


async def _fx_sprite(request: web.Request) -> web.Response:
    # Стрип-эффект удара/взрыва: fire{n}.png — квадратные кадры (one-shot VFX).
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "fx" / f"fire{n}.png"
    if not (1 <= n <= 10) or not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/map", _map_page)
    app.router.add_get("/api/taverns", _api_taverns)
    app.router.add_post("/api/invasion/join", _api_invasion_join)
    app.router.add_get("/assets/world.png", _world_png)   # земля диорамы
    app.router.add_get("/assets/map_tavern_{n}.png", _tavern_sprite)  # здания
    app.router.add_get("/assets/boss/ork{n}_{anim}.png", _event_sprite)  # ивент-анимации
    app.router.add_get("/assets/heroes/hero{n}_{anim}.png", _hero_sprite)  # войска-герои
    app.router.add_get("/assets/fx/fire{n}.png", _fx_sprite)  # эффекты ударов
    return app


async def run_webapp(port: int) -> web.AppRunner:
    """Запустить веб-сервер карты (вызывается из main параллельно с поллингом)."""
    runner = web.AppRunner(build_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner


_MAP_HTML = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Карта Недоливска</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.jsdelivr.net/npm/pixi.js@8.6.6/dist/pixi.min.js"></script>
<style>
  html,body{margin:0;padding:0;height:100%;width:100%;overflow:hidden;
    position:fixed;inset:0;overscroll-behavior:none;background:#0e1822;
    font:14px/1.4 Georgia,serif;color:#f3e6c8;-webkit-tap-highlight-color:transparent}
  canvas{display:block;touch-action:none}
  .bar{position:fixed;left:10px;bottom:10px;z-index:6;background:#241809cc;
    border:1px solid #5a452788;border-radius:20px;padding:5px 13px;font-size:11px;
    color:#d8c39a;letter-spacing:.2px;backdrop-filter:blur(4px);pointer-events:none;
    box-shadow:0 2px 10px #0006;transition:opacity .2s}
  .card{position:fixed;left:50%;bottom:14px;transform:translateX(-50%) translateY(140%);
    z-index:10;width:min(92vw,420px);background:#241809f2;border:1px solid #6b522e;
    border-radius:14px;padding:12px 14px;box-shadow:0 8px 26px #000a;transition:transform .22s ease}
  .card.show{transform:translateX(-50%) translateY(0)}
  .card .nm{font-size:17px;color:#f6dca0;font-weight:700;margin:0 0 4px}
  .card .rw{display:flex;gap:14px;font-size:13px;color:#d8c39a;flex-wrap:wrap}
  .card .rg{color:#c2a878}
  .card .me{margin-top:7px;color:#ffd24a;font-weight:700}
  .card .x{position:absolute;right:9px;top:6px;font-size:20px;color:#a98c5c;cursor:pointer;line-height:1}
  .hint{position:fixed;right:8px;top:8px;z-index:10;font-size:11px;color:#9a8052;opacity:.85}
  .vig{position:fixed;inset:0;pointer-events:none;z-index:5;
    background:radial-gradient(ellipse 78% 78% at 50% 50%, transparent 58%, #060a12 100%)}
  .ev{position:fixed;left:50%;bottom:calc(18px + env(safe-area-inset-bottom,0px));
    transform:translateX(-50%);z-index:10;display:none;
    background:#2a160af2;border:1px solid #c9803a;border-radius:22px;padding:8px 18px;
    font-size:13px;color:#ffe2a8;font-weight:700;letter-spacing:.2px;
    box-shadow:0 4px 18px #000b;white-space:nowrap;backdrop-filter:blur(3px)}
  .reg{position:fixed;left:50%;bottom:16vh;transform:translateX(-50%);z-index:11;display:none;
    width:min(92vw,420px);background:#241809f5;border:1px solid #c9803a;border-radius:14px;
    padding:12px 14px;text-align:center;box-shadow:0 8px 28px #000b}
  .reg .rt{font-size:16px;color:#ffd9a8;font-weight:700;margin-bottom:3px}
  .reg .rs{font-size:12px;color:#d8c39a;margin-bottom:9px;min-height:15px}
  .reg .rb{width:100%;padding:12px;border:none;border-radius:11px;background:#c0392b;
    color:#fff;font:700 15px Georgia,serif;cursor:pointer}
  .reg .rb:active{transform:scale(.98)} .reg .rb:disabled{opacity:.55}
  .reg .rj{font-size:14px;color:#ffd24a;font-weight:700}
  .rep{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:12;display:none;
    width:min(88vw,410px);max-height:76vh;overflow:auto;background:#1c1206f8;
    border:1px solid #c9803a;border-radius:14px;padding:12px 11px 15px;
    box-shadow:0 10px 34px #000d}
  .rep h3{margin:0 0 9px;font-size:15px;color:#ffd9a8;text-align:center;padding-right:18px}
  .rep .x{position:absolute;right:11px;top:8px;font-size:20px;color:#a98c5c;cursor:pointer;line-height:1}
  .rep table{width:100%;border-collapse:collapse;font-size:11.5px}
  .rep th{color:#a98c5c;font-weight:600;text-align:right;padding:3px 4px}
  .rep th:first-child{text-align:left}
  .rep td{padding:5px 4px;text-align:right;border-top:1px solid #3a2a16;color:#e6d3a8}
  .rep td:first-child{text-align:left;white-space:nowrap}
  .rep tr.me td{background:#43301266;color:#ffe2a8;font-weight:700}
  .rep .gold{color:#ffd24a;white-space:nowrap}
</style></head>
<body>
<div class="vig"></div>
<div class="ev" id="ev"></div>
<div class="reg" id="reg">
  <div class="rt" id="regTitle">🪓 Орда орков — сбор войск</div>
  <div class="rs" id="regSub"></div>
  <button class="rb" id="regBtn">⚔ Поднять войско</button>
  <div class="rj" id="regJoined" style="display:none"></div>
</div>
<div class="rep" id="rep">
  <span class="x" id="repx">×</span>
  <h3 id="repTitle"></h3>
  <div id="repBody"></div>
</div>
<div class="bar" id="bar">🗺 Недоливск · загрузка…</div>
<div class="hint">тащи · щипок/колесо — зум · тап по кружку — раскрыть</div>
<div class="card" id="card">
  <span class="x" id="cardx">×</span>
  <div class="nm" id="cnm"></div>
  <div class="rw"><span id="clv"></span><span class="rg" id="crg"></span></div>
  <div class="me" id="cme" style="display:none">🏠 Твоя таверна</div>
</div>
<script>
const tg = window.Telegram?.WebApp;
if (tg){ tg.ready(); tg.expand();
  // отключаем вертикальный свайп Telegram (тянет/закрывает мини-апп) — иначе
  // нельзя протащить карту вниз, чтобы посмотреть север. 7.7+; на старых — no-op.
  try { tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch(e){}
}
const myId = tg?.initDataUnsafe?.user?.id || 0;
const bar = document.getElementById('bar');
const card = document.getElementById('card');
const RING = {north_wilds:0x6ea8ff, green_valleys:0x6fd07a, red_wastes:0xe07a55};
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const SCREEN_W = 58;          // ширина здания НА ЭКРАНЕ (постоянная, не зависит от зума)
const CLUSTER_T = 50;         // ближе этого (px на экране) — таверны сливаются в кластер
const LABEL_MIN = 0.22;       // ниже этого масштаба подписи названий скрыты
const MAXS = 9;               // максимальный зум; минимальный = «вся карта в экране»

(async () => {
  const app = new PIXI.Application();
  await app.init({resizeTo: window, antialias: true, background: 0x0e1822,
                  resolution: Math.min(window.devicePixelRatio||1, 2), autoDensity: true});
  document.body.appendChild(app.canvas);

  let bgTex;
  try { bgTex = await PIXI.Assets.load('/assets/world.png'); }
  catch(e){ bar.textContent='⚠ карта не загрузилась'; return; }
  const W = bgTex.width, H = bgTex.height;

  // мир (фон) — зумится/двигается нативно; маркеры — ОТДЕЛЬНЫЙ слой поверх,
  // постоянного экранного размера (как пины на гео-картах), позиционируем вручную.
  const world = new PIXI.Container();
  const bg = new PIXI.Sprite(bgTex); world.addChild(bg);
  app.stage.addChild(world);
  const pathLayer = new PIXI.Graphics(); app.stage.addChild(pathLayer);  // пунктир маршрутов
  const markers = new PIXI.Container(); markers.sortableChildren = true;
  app.stage.addChild(markers);
  const eventLayer = new PIXI.Container(); app.stage.addChild(eventLayer);  // ивенты поверх
  const eventNodes = [];   // самостоятельные анимированные ивент-объекты

  // минимальный зум = «вся карта в экране» с небольшим запасом → вокруг материка
  // видна кайма моря/тумана (плюс виньетка). Снапится по центру, меньше не сжать.
  const SEA_FRAME = 0.9;   // <1 → материк чуть меньше экрана, вокруг полоса моря
  let minScale = Math.min(app.screen.width/W, app.screen.height/H) * SEA_FRAME;
  world.scale.set(minScale); clampCam();

  // --- таверны ---
  let data;
  try { data = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json(); }
  catch(e){ bar.textContent='⚠ не загрузить таверны'; return; }
  const regions = data.regions || {};
  const taverns = data.taverns.map(t => ({...t, wx: t.x*W, wy: t.y*H}));  // мировые px

  // предзагрузим только нужные спрайты-здания
  const tiers = [...new Set(taverns.map(t=>t.tier))];
  const tex = {};
  await Promise.all(tiers.map(async n => {
    try { tex[n] = await PIXI.Assets.load('/assets/map_tavern_'+n+'.png'); } catch(e){}
  }));

  // мировые → экранные координаты (world только масштаб+сдвиг, без поворота)
  const screenOf = (wx, wy) => ({x: wx*world.scale.x + world.x, y: wy*world.scale.y + world.y});

  // ---------- здание (одиночная таверна) ----------
  function makeBuilding(t){
    const node = new PIXI.Container(); node.wx = t.wx; node.wy = t.wy; node.zIndex = t.wy;
    const st = tex[t.tier]; const w = SCREEN_W;
    const hs = st ? w*(st.height/st.width) : w;
    node.addChild(new PIXI.Graphics().ellipse(0,0, w*0.42, w*0.15).fill({color:0x000000, alpha:0.34}));
    if (t.mine)
      node.addChild(new PIXI.Graphics().ellipse(0,0, w*0.5, w*0.19).stroke({color:0xffd24a, width:3, alpha:0.95}));
    else
      node.addChild(new PIXI.Graphics().ellipse(0,0, w*0.46, w*0.17).stroke({color:RING[t.region]||0xcaa23f, width:2, alpha:0.5}));
    if (st){
      const sp = new PIXI.Sprite(st); sp.anchor.set(0.5,1); sp.scale.set(w/st.width);
      sp.y = Math.round(w*0.05); node.addChild(sp);
      sp.eventMode='static'; sp.cursor='pointer'; sp.on('pointertap', e=> showCard(t, e));
    } else {
      const g = new PIXI.Graphics().circle(0,-w*0.4, w*0.32).fill({color: t.mine?0xffd24a:(RING[t.region]||0xcaa23f)});
      node.addChild(g); g.eventMode='static'; g.cursor='pointer'; g.on('pointertap', e=> showCard(t, e));
    }
    // подпись: ЕДИНАЯ рамка [чип уровня][название] под зданием.
    // Текст всегда помещается в рамку (ширина считается по тексту). Видимость
    // решает декластеризация подписей (declutterLabels) — чтобы не налезали.
    const raw = (t.name || '').trim();
    const nm = raw.length > 20 ? raw.slice(0,19)+'…' : (raw || 'Таверна');
    const lab = new PIXI.Container(); lab.eventMode = 'none'; lab.y = 8;
    const fh = 21, padX = 6, gap = 5, chipR = 8.5;
    const txt = new PIXI.Text({text:nm, style:{fontFamily:'Georgia,serif',
      fontSize:12, fontWeight:'600', fill:0xf3e6c8}});
    const totalW = padX + chipR*2 + gap + Math.ceil(txt.width) + padX;
    lab.addChild(new PIXI.Graphics().roundRect(-totalW/2, 0, totalW, fh, 7)
      .fill({color:0x140d06, alpha:0.76}).stroke({color:0x6b522e, width:1.2, alpha:0.7}));
    const chipX = -totalW/2 + padX + chipR;
    const chipCol = t.mine ? 0xffd24a : (RING[t.region] || 0xcaa23f);
    lab.addChild(new PIXI.Graphics().circle(chipX, fh/2, chipR)
      .fill({color:chipCol}).stroke({color:0x140d06, width:1.5}));
    const lt = new PIXI.Text({text:String(t.level), style:{fontFamily:'Georgia,serif',
      fontSize:11, fontWeight:'700', fill:0x201202}});
    lt.anchor.set(0.5); lt.position.set(chipX, fh/2); lab.addChild(lt);
    txt.anchor.set(0, 0.5); txt.position.set(chipX + chipR + gap, fh/2); lab.addChild(txt);
    node.addChild(lab);
    node._label = lab; node._labelBox = {w: totalW, h: fh};
    node._pri = (t.mine ? 1e6 : 0) + t.level;   // приоритет в борьбе за место
    return node;
  }

  // ---------- кластер (несколько таверн рядом) ----------
  function makeCluster(grp, wx, wy){
    const node = new PIXI.Container(); node.wx = wx; node.wy = wy; node.zIndex = wy;
    const hasMine = grp.some(m=>m.mine);
    const cnt = {}; grp.forEach(m=>{cnt[m.region]=(cnt[m.region]||0)+1;});
    const dom = Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a])[0];
    const col = hasMine ? 0xffd24a : (RING[dom] || 0xcaa23f);
    const r = 15 + Math.min(11, grp.length);
    node.addChild(new PIXI.Graphics().ellipse(0, r*0.7, r*0.95, r*0.32).fill({color:0x000000, alpha:0.32}));
    node.addChild(new PIXI.Graphics().circle(0,0,r).fill({color:col, alpha:0.93}).stroke({color:0x241809, width:2}));
    const txt = new PIXI.Text({text:String(grp.length), style:{fontFamily:'Georgia,serif',
      fontSize:Math.round(r*0.95), fontWeight:'700', fill:0x201202}});
    txt.anchor.set(0.5); node.addChild(txt);
    node.eventMode='static'; node.cursor='pointer';
    node.on('pointertap', e=>{ e.stopPropagation(); const s = screenOf(node.wx, node.wy);
      zoomAt(s.x, s.y, 2.1); refresh(); });
    return node;
  }

  // размер маркеров привязан к зуму (sublinear, с полом/потолком): при отдалении
  // здания УМЕНЬШАЮТСЯ (видно отдельные), при приближении растут до предела.
  function markerK(){ return Math.max(0.45, Math.min(1.2, Math.sqrt(world.scale.x/minScale) * 0.52)); }

  // ---------- кластеризация (жадная, по экранной дистанции) ----------
  function buildClusters(){
    for (const c of markers.children) c.destroy({children:true});
    markers.removeChildren();
    const T = CLUSTER_T * markerK();   // порог слияния тоже масштабируется с маркерами
    const pts = taverns.map(t => ({t, s: screenOf(t.wx, t.wy)}));
    // приоритет посева: своя таверна и более высокий уровень — «центры» кластеров
    pts.sort((a,b)=> (Number(b.t.mine)-Number(a.t.mine)) || (b.t.level - a.t.level));
    const used = new Array(pts.length).fill(false);
    for (let i=0;i<pts.length;i++){
      if (used[i]) continue; used[i]=true;
      const grp = [pts[i].t];
      for (let j=i+1;j<pts.length;j++){
        if (used[j]) continue;
        if (Math.hypot(pts[j].s.x-pts[i].s.x, pts[j].s.y-pts[i].s.y) < T){ used[j]=true; grp.push(pts[j].t); }
      }
      let node;
      if (grp.length === 1) node = makeBuilding(grp[0]);
      else {
        let cx=0, cy=0; grp.forEach(m=>{cx+=m.wx; cy+=m.wy;}); cx/=grp.length; cy/=grp.length;
        node = makeCluster(grp, cx, cy);
      }
      markers.addChild(node);
    }
    declutterLabels();
    reposition();
  }

  // greedy label placement: рамка-подпись видна, только если её экранный бокс не
  // налезает на другое здание и на уже размещённые подписи. Приоритет — своя
  // таверна и более высокий уровень (сортировка по _pri убыванием).
  function declutterLabels(){
    const k = markerK();   // боксы коллизий — в текущем масштабе маркеров
    const blds = markers.children.filter(n => n._label);
    const foot = blds.map(n => { const s = screenOf(n.wx, n.wy);
      return {n, l:s.x-SCREEN_W*0.5*k, r:s.x+SCREEN_W*0.5*k, t:s.y-SCREEN_W*1.05*k, b:s.y+3}; });
    const hit = (a,b) => !(a.r < b.l || a.l > b.r || a.b < b.t || a.t > b.b);
    blds.sort((a,b) => b._pri - a._pri);
    const placed = [];
    for (const n of blds){
      const s = screenOf(n.wx, n.wy), bw = n._labelBox.w*k, bh = n._labelBox.h*k;
      const box = {l:s.x-bw/2, r:s.x+bw/2, t:s.y+8*k, b:s.y+8*k+bh};
      let ok = true;
      for (const f of foot){ if (f.n !== n && hit(box, f)){ ok = false; break; } }
      if (ok) for (const p of placed){ if (hit(box, p)){ ok = false; break; } }
      n._labelAllowed = ok;
      if (ok) placed.push(box);
    }
  }
  function reposition(){
    const showLabels = world.scale.x > LABEL_MIN;   // на сильном отдалении подписи прячем
    const k = markerK();
    for (const node of markers.children){
      const s = screenOf(node.wx, node.wy); node.x = s.x; node.y = s.y; node.scale.set(k);
      if (node._label) node._label.visible = showLabels && node._labelAllowed;
    }
    for (const ev of eventNodes){ const s = screenOf(ev.wx, ev.wy);
      ev.x = s.x; ev.y = s.y; ev.scale.set(k * 0.52); }   // ивенты крупнее таверн
  }

  // перерисовку коалесцируем по кадрам: пан — только перепозиционируем (дёшево),
  // зум (заметное изменение масштаба) — пересобираем кластеры.
  let dirty = true, lastClusterScale = -1;
  app.ticker.add(() => {
    if (!dirty) return; dirty = false;
    if (Math.abs(world.scale.x - lastClusterScale) > Math.max(lastClusterScale,0.0001)*0.02){
      buildClusters(); lastClusterScale = world.scale.x;
    } else reposition();
  });
  const refresh = () => { dirty = true; };

  // ---------- pan / zoom ----------
  app.stage.eventMode = 'static';
  app.stage.hitArea = {contains:()=>true};
  const ptrs = new Map(); let lastDist = null;

  // привязка камеры к границам: карта всегда покрывает экран, а если по оси меньше
  // (на минимальном зуме) — снапится по центру; за край утащить нельзя, меньше не сжать.
  function clampCam(){
    const s = world.scale.x, mw = W*s, mh = H*s;
    if (mw <= app.screen.width) world.x = (app.screen.width - mw)/2;
    else world.x = Math.min(0, Math.max(app.screen.width - mw, world.x));
    if (mh <= app.screen.height) world.y = (app.screen.height - mh)/2;
    else world.y = Math.min(0, Math.max(app.screen.height - mh, world.y));
  }
  function zoomAt(sx, sy, factor){
    const ns = Math.min(MAXS, Math.max(minScale, world.scale.x*factor));
    const f = ns/world.scale.x;
    world.x = sx - (sx-world.x)*f;
    world.y = sy - (sy-world.y)*f;
    world.scale.set(ns); clampCam(); refresh();
  }
  function centerOn(wx, wy, s){
    world.scale.set(Math.min(MAXS, Math.max(minScale, s)));
    world.x = app.screen.width/2  - wx*world.scale.x;
    world.y = app.screen.height/2 - wy*world.scale.y; clampCam(); refresh();
  }

  app.stage.on('pointerdown', e => ptrs.set(e.pointerId, {x:e.global.x, y:e.global.y}));
  const drop = e => { ptrs.delete(e.pointerId); if (ptrs.size<2) lastDist=null; };
  app.stage.on('pointerup', drop);
  app.stage.on('pointerupoutside', drop);
  app.stage.on('pointermove', e => {
    if (!ptrs.has(e.pointerId)) return;
    const prev = ptrs.get(e.pointerId);
    const cur = {x:e.global.x, y:e.global.y};
    ptrs.set(e.pointerId, cur);
    if (ptrs.size === 1){ world.x += cur.x-prev.x; world.y += cur.y-prev.y; clampCam(); refresh(); }
    else if (ptrs.size === 2){
      const p = [...ptrs.values()];
      const d = Math.hypot(p[0].x-p[1].x, p[0].y-p[1].y);
      const mx = (p[0].x+p[1].x)/2, my = (p[0].y+p[1].y)/2;
      if (lastDist) zoomAt(mx, my, d/lastDist);
      lastDist = d;
    }
  });
  app.canvas.addEventListener('wheel', e => {
    e.preventDefault(); zoomAt(e.offsetX, e.offsetY, e.deltaY<0 ? 1.12 : 0.89);
  }, {passive:false});
  app.stage.on('pointertap', () => card.classList.remove('show'));  // тап по пустому — закрыть

  // ---------- старт ----------
  bar.textContent = '🗺 Недоливск · ' + taverns.length + ' таверн';
  const mine = taverns.find(t=>t.mine);
  if (mine) centerOn(mine.wx, mine.wy, Math.max(minScale, 0.85)); else refresh();
  window.addEventListener('resize', () => {
    minScale = Math.min(app.screen.width/W, app.screen.height/H) * SEA_FRAME;
    if (world.scale.x < minScale) world.scale.set(minScale);
    clampCam(); refresh();
  });

  // ---------- ивент-объекты (анимированные, самостоятельные) ----------
  const RL = {tank:['🛡','Авангард'], archer:['⚔️','Рубаки'],
              scout:['🔭','Разведка'], ratnik:['🗡','Ратники']};
  let liveInv = null, reportEv = null;      // живой ивент / сводка боя
  let invAddTroop = null;                    // добавить свою дружину на карту live
  for (const ev of (data.events || [])){
    try {
      const tex = await PIXI.Assets.load('/assets/boss/ork'+ev.sprite+'_idle.png');
      const fw = tex.width/10, fh = tex.height;   // стрип = 10 равных кадров в ряд
      const node = buildEvent(ev, sliceFrames(tex, 10), fw, fh);
      eventLayer.addChild(node); eventNodes.push(node);
      if (ev.gather_secs != null) await setupInvasion(ev, node, fw, fh);   // полноценный ивент с боем
      if (ev.gather_secs != null && !ev.demo) liveInv = ev;                // настоящий ивент
      if (ev.report) reportEv = ev;                                        // сводка после боя
    } catch(e){ console.log('event load fail', e); }
  }
  if (liveInv){
    centerOn(liveInv.x*W, liveInv.y*H, Math.max(minScale, 1.1));   // открываемся на орде
    if (liveInv.status === 'gathering') setupRegPanel(liveInv);    // плашка регистрации
  } else if (reportEv){
    centerOn(reportEv.x*W, reportEv.y*H, Math.max(minScale, 1.1));
    let seen = ''; try { seen = localStorage.getItem('inv_seen') || ''; } catch(e){}
    if (String(reportEv.id) !== seen) setupReportPanel(reportEv);  // авто-показ только ОДИН раз
    // иначе сводка доступна тапом по орде (showEventCard), сама не лезет
  }
  if (eventNodes.length){
    app.ticker.add(() => { const a = 0.10 + 0.12*(0.5 + 0.5*Math.sin(performance.now()/700));
      for (const ev of eventNodes) ev._glow.alpha = a; });   // мягкий пульс свечения
    refresh();
  }

  // ---------- карточка ----------
  function showCard(t, e){
    if (e) e.stopPropagation();
    document.getElementById('cnm').textContent = t.name;
    document.getElementById('clv').textContent = 'Уровень ' + t.level;
    document.getElementById('crg').textContent = regions[t.region] || t.region || '';
    document.getElementById('cme').style.display = t.mine ? 'block' : 'none';
    card.classList.add('show');
  }
  function sliceFrames(tex, count){
    const fw = tex.width/count, fh = tex.height, fr = [];
    for (let i=0;i<count;i++)
      fr.push(new PIXI.Texture({source:tex.source, frame:new PIXI.Rectangle(i*fw,0,fw,fh)}));
    return fr;
  }
  function buildEvent(ev, frames, fw, fh){
    const node = new PIXI.Container(); node.wx = ev.x*W; node.wy = ev.y*H; node._fh = fh; node._fw = fw;
    // мягкое тёплое свечение под ивентом (пульсирует) + тень
    const glow = new PIXI.Graphics().ellipse(0, -fh*0.06, fw*0.5, fw*0.2).fill({color:0xffb347, alpha:0.2});
    node.addChild(glow); node._glow = glow;
    node.addChild(new PIXI.Graphics().ellipse(0,0, fw*0.4, fw*0.13).fill({color:0x000000, alpha:0.42}));
    const anim = new PIXI.AnimatedSprite(frames); anim.animationSpeed = 0.12; anim.anchor.set(0.5,1); anim.play();
    anim.eventMode='static'; anim.cursor='pointer'; anim.on('pointertap', e=> showEventCard(ev, e));
    node.addChild(anim); node._anim = anim; node._idle = frames;
    // статичная подпись-банер — только для idle-маркера (у ивента с боем банер сверху, в HTML)
    if (ev.gather_secs == null){
      const txt = new PIXI.Text({text:'⚔ '+ev.name, style:{fontFamily:'Georgia,serif',
        fontSize:14, fontWeight:'700', fill:0xffe2a8}});
      txt.anchor.set(0.5, 1); txt.y = -fh - 8;
      const bw = txt.width + 18, by = -fh - 8 - txt.height - 4;
      node.addChild(new PIXI.Graphics().roundRect(-bw/2, by, bw, txt.height + 6, 7)
        .fill({color:0x2a160a, alpha:0.9}).stroke({color:0xc9803a, width:1.4, alpha:0.9}));
      node.addChild(txt);
    }
    return node;
  }
  // полноценный ивент: сбор → марш войск из таверн → авто-бой → итог.
  // Драйвится таймлайном (демо — локальная петля; реальный — серверное время).
  async function setupInvasion(ev, node, fw, fh){
    const anim = node._anim, idle = node._idle;
    const A = {};
    for (const a of ['hurt','die','attack']){
      try { A[a] = sliceFrames(await PIXI.Assets.load('/assets/boss/ork'+ev.sprite+'_'+a+'.png'), 10); } catch(e){}
    }
    const bx = ev.x*W, by = ev.y*H;
    // HP-бар орды (рисуем по ходу боя)
    const hp = new PIXI.Graphics(); hp.visible = false; node.addChild(hp);
    const barW = fw*0.8, barY = -fh - 16;
    function drawHp(frac, warded){     // под щитом (бронёй) бар синеет и обводится
      frac = Math.max(0, Math.min(1, frac)); hp.clear();
      hp.roundRect(-barW/2, barY, barW, 11, 4).fill({color:0x140d06, alpha:0.85})
        .stroke({color: warded?0x6ea8ff:0x6b522e, width: warded?2:1});
      if (frac>0) hp.roundRect(-barW/2+1.5, barY+1.5, (barW-3)*frac, 8, 3)
        .fill({color: warded?0x3d6fb0:0xc0392b});
    }
    // иконки активных баффов орды над полоской (по реальному таймлайну)
    const buffTxt = new PIXI.Text({text:'', style:{fontFamily:'Georgia,serif', fontSize:15,
      fontWeight:'700', fill:0xffe2a8, stroke:{color:0x140d06, width:4}}});
    buffTxt.anchor.set(0.5, 1); buffTxt.y = barY - 3; buffTxt.visible = false; node.addChild(buffTxt);
    // спрайты героев (3 модели) — раздаём таверне стабильно по координатам
    const HERO_COUNT = 6;
    const HERO = {};
    for (let h=1; h<=HERO_COUNT; h++){ HERO[h] = {};
      for (const a of ['walk','attack','die','idle']){
        try { HERO[h][a] = sliceFrames(await PIXI.Assets.load('/assets/heroes/hero'+h+'_'+a+'.png'), 10); } catch(e){}
      }
    }
    const hashCoord = (x,y) => Math.abs(Math.floor(x*1000)*31 + Math.floor(y*1000)*17);
    function uAnim(u, name){ if (u.anim===name) return; const fr=HERO[u.hero][name]; if (!fr) return;
      u.sp.textures = fr; u.sp.loop = (name!=='die'); u.sp.gotoAndPlay(0); u.anim = name; }
    // войска — герои, выходят из таверн
    function makeUnit(t, i){
      const h = 1 + (hashCoord(t.x, t.y) % HERO_COUNT);
      const sp = new PIXI.AnimatedSprite(HERO[h].walk || [PIXI.Texture.EMPTY]);
      sp.anchor.set(0.5, 1); sp.animationSpeed = 0.22; sp.play(); sp.visible = false;
      eventLayer.addChild(sp);
      return {sp, hero:h, anim:'walk', dir:1, ox:t.x*W, oy:t.y*H, wx:t.x*W, wy:t.y*H,
              ang:Math.random()*6.28, rad:fw*(0.30+0.25*Math.random()), delay:(i%6)*0.06};
    }
    const units = (ev.troops||[]).map((t,i)=>makeUnit(t,i));
    invAddTroop = (t) => { units.push(makeUnit(t, units.length)); };   // своя дружина live
    const HSCALE = 0.44;   // размер героя относительно карты
    // пунктир маршрута таверна→орда (экранные коорд., экранно-постоянный шаг)
    function drawDotted(x1,y1,x2,y2,prog){
      const dx=x2-x1, dy=y2-y1, len=Math.hypot(dx,dy)||1, ux=dx/len, uy=dy/len, end=len*prog;
      for (let d=0; d<end; d+=15){ const a=d, b=Math.min(end, d+8);
        pathLayer.moveTo(x1+ux*a, y1+uy*a).lineTo(x1+ux*b, y1+uy*b); }
    }
    // эффекты ударов (огонь/взрыв) — one-shot, спавним по орку в бою
    const FX = [];
    for (let n=1; n<=10; n++){
      try { const tx = await PIXI.Assets.load('/assets/fx/fire'+n+'.png');
        FX.push(sliceFrames(tx, Math.max(1, Math.round(tx.width/tx.height)))); } catch(e){}
    }
    const hits = [];
    function spawnHit(wx, wy, size){
      if (!FX.length) return;
      const fr = FX[(Math.random()*FX.length)|0];
      const sp = new PIXI.AnimatedSprite(fr); sp.anchor.set(0.5); sp.loop=false;
      sp.animationSpeed = 0.4; sp._wx=wx; sp._wy=wy; sp._size=size; sp._fs=fr[0].height||128;
      sp.onComplete = () => { const i=hits.indexOf(sp); if(i>=0) hits.splice(i,1); sp.destroy(); };
      sp.play(); eventLayer.addChild(sp); hits.push(sp);
    }
    const G=ev.gather_secs, M=ev.march_secs, B=ev.battle_secs, END=4, TOTAL=G+M+B+END;
    const evEl = document.getElementById('ev');
    // демо крутит локально; живой ивент синхронизируем серверным elapsed (сек с
    // начала сбора) — сдвигаем старт так, чтобы t совпало с фазой на сервере.
    let start = performance.now()/1000 - (ev.demo ? 0 : (ev.elapsed||0));
    let cur='', dieStarted=false, lastHurt=0, reportFetched=false;
    let retStarted=false, retStart=0;
    const RETURN_SECS = 7;        // дружины уходят домой так же неспешно, как шли к орде
    // конец боя — подтянуть сводку с сервера (предсказание готово сразу) и показать
    // ПРЯМО НА КАРТЕ, без перезагрузки. Несколько попыток на случай сетевой заминки.
    async function pollReport(){
      for (let i=0;i<60;i++){
        try {
          const d = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json();
          const e = (d.events||[]).find(x=>x.report);
          if (e){ setupReportPanel(e); return; }
        } catch(_){}
        await new Promise(r=>setTimeout(r, 700));
      }
    }
    function setAnim(name){
      if (cur===name) return;
      const fr = name==='idle' ? idle : A[name]; if (!fr) return;
      anim.textures = fr; anim.loop = (name!=='die'); anim.gotoAndPlay(0); cur=name;
    }
    function fmt(s){ s=Math.max(0,Math.ceil(s)); return Math.floor(s/60)+':'+String(s%60).padStart(2,'0'); }
    function reset(){ start=performance.now()/1000; cur=''; dieStarted=false; node.alpha=1; anim.tint=0xffffff;
      setAnim('idle');
      for (const sp of hits.splice(0)) sp.destroy();   // убрать активные вспышки
      for (const u of units){ u.wx=u.ox; u.wy=u.oy; u.sp.alpha=1; u.sp.visible=false; uAnim(u,'walk'); } }
    setAnim('idle');

    app.ticker.add(() => {
      let t = (performance.now()/1000) - start;
      if (t > TOTAL){ if (ev.demo) { reset(); t = 0; } else t = TOTAL; }
      const k = markerK();
      pathLayer.clear();
      const bs = screenOf(bx, by);
      evEl.style.display = 'block';                  // баннер фазы (внизу); на живом сборе скроем
      buffTxt.visible = false;                       // баффы орды — только в бою
      if (t < G){                                   // СБОР: войска СТОЯТ у таверн + пунктир к орде
        evEl.style.display = ev.demo ? 'block' : 'none';   // на сборе отсчёт показывает плашка регистрации
        evEl.textContent = '⚔ Сбор войск · выход через '+Math.ceil(G-t)+'с · таверн: '+units.length;
        setAnim('idle'); hp.visible=false;
        for (const u of units){ u.wx=u.ox; u.wy=u.oy; u.sp.visible=true;
          u.dir=(bx>=u.ox)?1:-1; uAnim(u,'idle');
          const us=screenOf(u.ox,u.oy); drawDotted(us.x,us.y, bs.x,bs.y, t/G); }
      } else if (t < G+M){                            // МАРШ: герои идут по пунктиру
        const p=(t-G)/M;
        evEl.textContent = '⚔ Войска идут к орде!'; setAnim('idle'); hp.visible=false;
        for (const u of units){
          const lp = Math.max(0, Math.min(1, (p-u.delay)/(1-u.delay)));
          u.wx = u.ox + (bx-u.ox)*lp; u.wy = u.oy + (by-u.oy)*lp;
          u.sp.visible = lp>0; u.dir = (bx>=u.ox)?1:-1; uAnim(u,'walk');
          const us=screenOf(u.ox,u.oy); drawDotted(us.x,us.y, bs.x,bs.y, 1);
        }
      } else if (t < G+M+B){                          // БОЙ
        const bp=(t-(G+M))/B;
        evEl.textContent = '⚔ Битва · '+fmt(B*(1-bp));
        hp.visible=true;
        let warded=false, bf='';
        if (ev.timeline && ev.timeline.length && ev.orc_hp_max){    // РЕАЛЬНАЯ динамика
          const tl=ev.timeline, idx=Math.min(tl.length-1, Math.max(0, Math.floor(bp*tl.length)));
          const st=tl[idx]; warded=!!st.ward;
          drawHp(st.hp/ev.orc_hp_max, warded);
          if (st.ward) bf+='🛡'; if (st.curse) bf+='💀'; if (st.adds>0) bf+='🐺'; if (st.enraged) bf+='🗣';
        } else { drawHp(1-bp); }                                    // демо — по таймеру
        buffTxt.visible = !!bf; buffTxt.text = bf;
        if (bp > 0.88 && !ev.demo && !reportFetched){ reportFetched=true; pollReport(); }  // итог пораньше
        for (const u of units){ u.ang+=0.03;
          u.wx = bx + Math.cos(u.ang)*u.rad*0.55; u.wy = by + Math.sin(u.ang)*u.rad*0.30 - fh*0.06;
          u.sp.visible=true; u.dir = (bx>=u.wx)?1:-1; uAnim(u,'attack'); }
        const s = performance.now()/1000;
        if (s-lastHurt > 0.55){ lastHurt=s; anim.tint=0xff7a6a; setAnim('hurt');
          const n = 2 + (Math.random()*2|0);   // 2–3 вспышки за удар — кучно по орку
          for (let q=0;q<n;q++)
            spawnHit(bx + (Math.random()-0.5)*fw*0.22, by - Math.random()*fh*0.1, 120 + Math.random()*60); }
        else if (s-lastHurt > 0.22){ anim.tint=0xffffff; setAnim('idle'); }
      } else {                                        // ИТОГ
        const won = ev.result!=='lost';
        evEl.textContent = won ? '🏆 Орда разбита! Победа за городом' : '💀 Орки устояли…';
        if (won){
          hp.visible=false;
          if (!dieStarted && A.die){ dieStarted=true; anim.tint=0xffffff; setAnim('die');
            spawnHit(bx, by - fh*0.2, 280);                              // большой взрыв
            spawnHit(bx-fw*0.3, by, 150); spawnHit(bx+fw*0.3, by, 150); }  // + по бокам
          node.alpha = Math.max(0, node.alpha - 0.012);
          if (!retStarted){ retStarted=true; retStart=performance.now()/1000;
            for (const u of units){ u.rx0=u.wx; u.ry0=u.wy; } }   // откуда уходят
          const rp = Math.min(1, (performance.now()/1000 - retStart)/RETURN_SECS);
          for (const u of units){                       // победа — дружины НЕСПЕШНО идут домой
            u.wx = u.rx0 + (u.ox-u.rx0)*rp; u.wy = u.ry0 + (u.oy-u.ry0)*rp;
            u.dir = (u.ox>=u.wx)?1:-1; uAnim(u, rp<1 ? 'walk' : 'idle');
          }
        } else {
          let lf=0.35;
          if (ev.timeline && ev.timeline.length && ev.orc_hp_max)
            lf = ev.timeline[ev.timeline.length-1].hp / ev.orc_hp_max;   // реальный остаток HP орды
          hp.visible=true; drawHp(lf); setAnim('idle'); anim.tint=0xffffff;
          for (const u of units){ uAnim(u,'die'); }
        }
        if (!ev.demo && !reportFetched){ reportFetched=true; pollReport(); }   // сводка live, без reload
      }
      pathLayer.stroke({color:0xffe2a8, width:Math.max(1.4, 2*k), alpha:0.5});
      for (const u of units){ const s=screenOf(u.wx,u.wy); u.sp.x=s.x; u.sp.y=s.y;
        u.sp.scale.set(k*HSCALE); u.sp.scale.x = k*HSCALE*u.dir; }
      for (const sp of hits){ const s=screenOf(sp._wx, sp._wy);
        sp.x=s.x; sp.y=s.y - fh*0.34*k; sp.scale.set(k*sp._size/sp._fs); }
    });
  }
  // ---------- боевая сводка после боя (таблица по каждому) ----------
  function setupReportPanel(ev){
    const rep = document.getElementById('rep'), title = document.getElementById('repTitle'),
          body = document.getElementById('repBody');
    title.innerHTML = (ev.won ? '🏆 Орда разбита' : '💀 Орки устояли')
      + ' · ' + (ev.n || 0) + ' дружин · ' + (ev.rounds || 0) + ' раундов';
    let html = '<table><tr><th>Боец</th><th>⚔ урон</th><th>🛡 блок</th>'
      + '<th>💥 крит</th><th>🪙 итог</th></tr>';
    for (const r of (ev.rows || [])){
      const rl = RL[r.role] || RL.ratnik;
      const nm = (r.fell ? '💀 ' : '') + rl[0] + ' ' + esc(r.name);
      const rew = ev.won
        ? ('+' + r.gold + (r.trophy ? ' 🎁' + esc(r.trophy) : ''))
        : ('' + r.gold);
      html += '<tr class="' + (r.mine ? 'me' : '') + '"><td>' + nm + '</td><td>'
        + r.dmg + '</td><td>' + r.blocked + '</td><td>' + r.crit
        + '</td><td class="gold">' + rew + '</td></tr>';
    }
    body.innerHTML = html + '</table>';
    rep.style.display = 'block';
    bar.style.display = 'none';            // на время сводки счётчик прячем
    try { localStorage.setItem('inv_seen', String(ev.id || '')); } catch(e){}  // больше не авто-показывать этот бой
  }
  document.getElementById('repx').onclick = () => {
    document.getElementById('rep').style.display = 'none';
  };

  function showEventCard(ev, e){
    if (e) e.stopPropagation();
    if (ev.report){ setupReportPanel(ev); return; }   // тап по орде — пересобрать и показать сводку
    document.getElementById('cnm').textContent = '⚔ ' + ev.name;
    document.getElementById('clv').textContent = ev.blurb || '';
    document.getElementById('crg').textContent = 'Событие';
    document.getElementById('cme').style.display = 'none';
    card.classList.add('show');
  }
  document.getElementById('cardx').onclick = () => card.classList.remove('show');

  // ---------- плашка регистрации на карте (фаза сбора живого ивента) ----------
  function setupRegPanel(ev){
    const reg = document.getElementById('reg'), btn = document.getElementById('regBtn'),
          sub = document.getElementById('regSub'), joined = document.getElementById('regJoined');
    reg.style.display = 'block';
    bar.style.display = 'none';            // плашка-счётчик не мешает регистрации
    function paintJoined(role){
      btn.style.display = 'none';
      const rl = RL[role] || RL.ratnik;
      joined.style.display = 'block';
      joined.textContent = '✅ Ты в строю · ' + rl[0] + ' ' + rl[1];
    }
    if (ev.me_registered) paintJoined(ev.my_role);
    const start = performance.now()/1000 - (ev.elapsed || 0);
    app.ticker.add(() => {
      const left = Math.max(0, (ev.gather_secs || 0) - (performance.now()/1000 - start));
      if (left <= 0){ reg.style.display = 'none'; return; }   // сбор окончен — плашка уходит
      sub.textContent = '⏳ Выход через ' + Math.floor(left/60) + ':'
        + String(Math.floor(left % 60)).padStart(2, '0') + ' · таверн: ' + (ev.n || 0);
    });
    btn.onclick = async () => {
      btn.disabled = true; const was = btn.textContent; btn.textContent = 'Поднимаем…';
      try {
        const r = await fetch('/api/invasion/join', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({initData: (tg && tg.initData) || ''})});
        const d = await r.json();
        if (d.ok){
          paintJoined(d.role);
          try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred('success'); } catch(e){}
          if (invAddTroop) invAddTroop({x: d.x, y: d.y});   // твоя дружина появляется на карте live
        } else {
          btn.disabled = false; btn.textContent = was;
          sub.textContent = ({no_tavern: 'Сначала заведи кабак в боте (/start)',
            closed: 'Сбор уже закончился', testing: 'Ивент на тестировании — скоро откроем',
            auth: 'Не удалось войти — открой карту через бота'}[d.error]) || 'Не вышло, попробуй ещё';
        }
      } catch(e){ btn.disabled = false; btn.textContent = was; sub.textContent = 'Сеть подвела — ещё раз'; }
    };
  }
})();
</script>
</body></html>"""
