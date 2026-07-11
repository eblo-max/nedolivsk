"""Mini App: React-приложение игры + интерактивная карта мира (Telegram Web App).

Маленький aiohttp-сервер РЯДОМ с ботом (тот же процесс, слушает $PORT — Railway
выдаёт публичный домен). Отдаёт:
  GET /            — health-check
  GET /app         — React-мини-апп (сборка miniapp/dist)
  GET /world       — тайловая интерактивная карта мира (Leaflet), встраивается в мини-апп
  /assets/...      — статика (спрайты)

Карта — тайловый мир-атлас на Leaflet (пирамида .webp-тайлов из assets/world25.jpg):
таверны-маркеры с кластеризацией, континенты, короны лидеров, Орда орков. Старая
PNG/PixiJS-карта (/map) удалена — карта живёт только здесь.
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
    _api_invasion_join, _api_invasion_prepare, _api_invasion_result, _api_invasion_seed,
    _api_invasion_state, _invasion_event, _invasion_report_event,
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
    _api_character, _api_craft_claim, _api_forge, _api_forge_make,
    _api_gear_equip, _api_gear_unequip, _api_heal, _api_sharpen,
)
# Двор/производство/охота — bot/webapi/production.py (распил, move-only).
from bot.webapi.production import (  # noqa: E402,F401 — фасад
    _api_brew_age, _api_build_start, _api_building, _api_buildings, _api_hunt,
    _api_hunt_fight, _api_hunt_forecast, _api_prod_claim, _api_prod_start,
)
# Тайные рецепты (ИИ-блюда, эксперимент в Кухне) — bot/webapi/recipes.py.
from bot.webapi.recipes import _api_recipe_experiment  # noqa: E402,F401 — фасад
# Карта мира (/world, тайлы, таверны с коронами) — bot/webapi/world.py
# (распил, move-only). Импорт = ре-экспорт для build_app и внешних потребителей.
from bot.webapi.world import (  # noqa: E402,F401 — фасад
    _world_continents, _world_invasion, _world_page, _world_raid,
    _world_slots, _world_taverns, _world_tile,
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

# Общие стройки «Чудеса города» — bot/webapi/wonder.py (Фаза 1).
from bot.webapi.wonder import _api_wonder, _api_wonder_contribute  # noqa: E402,F401

# Лавка Артели зодчих (сток зодаров) — bot/webapi/artel.py (Фаза 2).
from bot.webapi.artel import _api_artel, _api_artel_buy, _api_artel_prestige  # noqa: E402,F401


async def _api_whoami(request: web.Request) -> web.Response:
    """Кто я: флаг админа (для гейта вкладки «Карта» в мини-аппе). Auth — initData."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    return web.json_response({"ok": True, "admin": _is_admin(uid)},
                             headers={"Cache-Control": "no-store"})


# Статика: спрайты/SPA/аудио/phaser — bot/webapi/assets.py (распил, move-only).
from bot.webapi.assets import (  # noqa: E402,F401 — фасад
    _animal_sprite, _audio_track, _event_sprite, _farm_sprite, _fx_sprite,
    _hero_sprite, _hud_globe, _phaser_page, _spa, _tavern_sprite,
)


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
    app.router.add_get("/world", _world_page)                 # тайловый мир-атлас (Leaflet) — единственная карта
    app.router.add_get("/world/slots.json", _world_slots)
    app.router.add_get("/world/taverns.json", _world_taverns)
    app.router.add_get("/world/invasion.json", _world_invasion)   # орда орков на карте (поллинг)
    app.router.add_get("/world/raid.json", _world_raid)           # рейд-босс на карте (поллинг)
    app.router.add_get("/world/tiles/{z}/{x}/{y}.webp", _world_tile)
    app.router.add_get("/world/tiles/{z}/{x}/{y}.jpg", _world_tile)   # старый кэш → отдаём webp-байты
    app.router.add_get("/app", _spa)                  # React-мини-апп (каркас игры)
    app.router.add_get("/app/{tail:.*}", _spa)        # SPA-fallback + статика dist
    app.router.add_post("/api/invasion/join", _api_invasion_join)
    app.router.add_post("/api/invasion/state", _api_invasion_state)  # панель сбора: трейт/состав/стойки
    app.router.add_post("/api/invasion/prepare", _api_invasion_prepare)  # ФАЗА 2: военные приготовления
    app.router.add_post("/api/invasion/result", _api_invasion_result)  # модалка итогов боя (всплывает на карте)
    app.router.add_post("/api/invasion/seed", _api_invasion_seed)   # АДМИН: тихий призыв орды (тест карты)
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
    app.router.add_post("/api/sharpen", _api_sharpen)   # заточка вещи (кузница 2.0)
    app.router.add_post("/api/gear/equip", _api_gear_equip)      # надеть вещь из стока
    app.router.add_post("/api/gear/unequip", _api_gear_unequip)  # снять вещь в сток
    app.router.add_post("/api/buildings", _api_buildings)    # список пристроек
    app.router.add_post("/api/building", _api_building)       # деталь/производство здания
    app.router.add_post("/api/build_start", _api_build_start)  # заложить пристройку
    app.router.add_post("/api/prod_start", _api_prod_start)   # запустить партию
    app.router.add_post("/api/brew_age", _api_brew_age)       # выдержка эля (риск)
    app.router.add_post("/api/prod_claim", _api_prod_claim)   # забрать партию
    app.router.add_post("/api/recipe/experiment", _api_recipe_experiment)  # тайные рецепты: открыть/сварить
    app.router.add_post("/api/hunt", _api_hunt)               # меню охоты (бестиарий+прогноз)
    app.router.add_post("/api/hunt_fight", _api_hunt_fight)
    app.router.add_post("/api/hunt_forecast", _api_hunt_forecast)  # прогноз с флягой (dry-run)   # бой со зверем
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
    app.router.add_post("/api/wonder", _api_wonder)              # общая стройка: состояние
    app.router.add_post("/api/wonder/contribute", _api_wonder_contribute)  # вложить в стройку
    app.router.add_post("/api/artel", _api_artel)               # Лавка Артели: каталог+зодары
    app.router.add_post("/api/artel/buy", _api_artel_buy)       # купить награду за зодары
    app.router.add_post("/api/artel/prestige", _api_artel_prestige)  # выбрать титул/фасад к показу
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


async def run_webapp(port: int, bot=None) -> web.AppRunner:
    """Запустить веб-сервер карты (вызывается из main параллельно с поллингом).
    bot — тот же aiogram-Bot (один event-loop): нужен, чтобы мини-апп-эндпоинты
    могли слать в чаты (напр. админский призыв рейд-босса)."""
    set_bot(bot)
    runner = web.AppRunner(build_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner
