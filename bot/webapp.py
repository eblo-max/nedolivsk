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

import pathlib

from aiohttp import web

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


# Таверна: состояние/действия (сбор, торг, апгрейд, панели, бригады, бонус,
# розница, мельница, онбординг) — bot/webapi/tavern.py (распил, move-only).
from bot.webapi.tavern import (  # noqa: E402,F401 — фасад
    _api_bonus, _api_collect, _api_expedition, _api_expedition_start,
    _api_mill_collect, _api_mill_run, _api_newbie, _api_onboard, _api_panel,
    _api_retail_hold, _api_retail_sell, _api_state, _api_story_choice,
    _api_trade, _api_upgrade, _tavern_state,
)
# Персонаж/кузница — bot/webapi/character.py (распил, move-only).
from bot.webapi.character import (  # noqa: E402,F401 — фасад
    _api_character, _api_craft_claim, _api_forge, _api_forge_make, _api_heal,
)
# Двор/производство/охота — bot/webapi/production.py (распил, move-only).
from bot.webapi.production import (  # noqa: E402,F401 — фасад
    _api_brew_age, _api_build_start, _api_building, _api_buildings, _api_hunt,
    _api_hunt_fight, _api_prod_claim, _api_prod_start,
)
# Карты мира (/map, /world, тайлы, таверны с коронами) — bot/webapi/world.py
# (распил, move-only). Импорт = ре-экспорт для build_app и внешних потребителей.
from bot.webapi.world import (  # noqa: E402,F401 — фасад
    _map_page, _world_continents, _world_page, _world_png, _world_slots,
    _world_taverns, _world_tile,
)


# Уведомления мини-аппа — bot/webapi/notifications.py (распил, move-only).
from bot.webapi.notifications import (  # noqa: E402,F401 — фасад
    _api_notifications, _api_notifications_read, _api_notifications_seed_all,
    _api_notifications_seed_patchnote,
)
# NPC-аватары и «N назад» — bot/webapi/core.py (нужны стори-блоку и лентам).
from bot.webapi.core import _AV_BY_ESTATE, _chron_ago, _npc_avatar  # noqa: E402,F401 — фасад


# Репутация/летопись/зазывала — bot/webapi/city.py (распил, move-only).
from bot.webapi.city import (  # noqa: E402,F401 — фасад
    _api_chronicle, _api_referral, _api_reputation,
)
# Торг/аукцион/биржа — вынесены в bot/webapi/torg.py (распил, move-only).
from bot.webapi.torg import (  # noqa: E402,F401 — фасад
    _api_auction, _api_auction_cancel, _api_auction_create, _api_auction_seed,
    _api_auction_seen, _api_auction_settle_now, _api_bourse, _api_bourse_act,
    _api_torg, _api_torg_buy,
)
# Доска почёта/тренд/короны/аватарки — вынесены в bot/webapi/rating.py
# (распил монолита, move-only). Импорт сюда = ре-экспорт для потребителей
# (notifier.snapshot_rating_ranks, тесты, _world_taverns ниже).
from bot.webapi.rating import (  # noqa: E402,F401 — фасад
    _AVATAR_CACHE, _RANK_SNAPS, _RATING_METRICS, _RATING_TOP, _api_avatar,
    _api_rating, _ava_sig, _ranked, _rating_board, _rating_entries,
    _rating_leaders, _trend_baseline, _trend_hydrate, _trend_record,
    snapshot_rating_ranks,
)


# Ночная ходка — bot/webapi/nightrun.py (распил, move-only).
from bot.webapi.nightrun import (  # noqa: E402,F401 — фасад
    _api_nightrun, _api_nightrun_bank, _api_nightrun_meet, _api_nightrun_pick,
    _api_nightrun_push, _api_nightrun_quiz, _api_nightrun_start,
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
