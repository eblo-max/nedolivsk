"""Снапшот-контракт HTTP-роутов webapp — страховка распила на модули.

Если тест упал — роут исчез/переименовался/сменил путь. Осознанное изменение
API = обновить снапшот В ТОМ ЖЕ коммите, что и правка роутов.
"""

import os

os.environ.setdefault("BOT_TOKEN", "test:test")

ROUTES = [
    "GET / _health",
    "GET /api/taverns _api_taverns",
    "GET /app _spa",
    "GET /app/{tail} _spa",
    "GET /assets/animals/{name}.png _animal_sprite",
    "GET /assets/audio/festival.mp3 _audio_track",
    "GET /assets/boss/ork{n}_{anim}.png _event_sprite",
    "GET /assets/farm/{name}.png _farm_sprite",
    "GET /assets/fx/fire{n}.png _fx_sprite",
    "GET /assets/heroes/hero{n}_{anim}.png _hero_sprite",
    "GET /assets/hud/squad_globe.png _hud_globe",
    "GET /assets/map_tavern_{n}.png _tavern_sprite",
    "GET /assets/world.png _world_png",
    "GET /avatar/{uid} _api_avatar",
    "GET /map _map_page",
    "GET /phasertest _phaser_page",
    "GET /world _world_page",
    "GET /world/slots.json _world_slots",
    "GET /world/invasion.json _world_invasion",
    "GET /world/taverns.json _world_taverns",
    "GET /world/tiles/{z}/{x}/{y}.jpg _world_tile",
    "GET /world/tiles/{z}/{x}/{y}.webp _world_tile",
    "POST /api/auction _api_auction",
    "POST /api/auction/cancel _api_auction_cancel",
    "POST /api/auction/create _api_auction_create",
    "POST /api/auction/seed _api_auction_seed",
    "POST /api/auction/seen _api_auction_seen",
    "POST /api/auction/settle_now _api_auction_settle_now",
    "POST /api/bonus _api_bonus",
    "POST /api/bourse _api_bourse",
    "POST /api/bourse/act _api_bourse_act",
    "POST /api/brew_age _api_brew_age",
    "POST /api/build_start _api_build_start",
    "POST /api/building _api_building",
    "POST /api/buildings _api_buildings",
    "POST /api/character _api_character",
    "POST /api/chronicle _api_chronicle",
    "POST /api/collect _api_collect",
    "POST /api/craft_claim _api_craft_claim",
    "POST /api/expedition _api_expedition",
    "POST /api/expedition_start _api_expedition_start",
    "POST /api/forge _api_forge",
    "POST /api/forge_make _api_forge_make",
    "POST /api/heal _api_heal",
    "POST /api/hunt _api_hunt",
    "POST /api/hunt_fight _api_hunt_fight",
    "POST /api/hunt_forecast _api_hunt_forecast",
    "POST /api/invasion/join _api_invasion_join",
    "POST /api/invasion/result _api_invasion_result",
    "POST /api/invasion/seed _api_invasion_seed",
    "POST /api/invasion/state _api_invasion_state",
    "POST /api/mill/collect _api_mill_collect",
    "POST /api/mill/run _api_mill_run",
    "POST /api/newbie _api_newbie",
    "POST /api/nightrun _api_nightrun",
    "POST /api/nightrun/bank _api_nightrun_bank",
    "POST /api/nightrun/meet _api_nightrun_meet",
    "POST /api/nightrun/pick _api_nightrun_pick",
    "POST /api/nightrun/push _api_nightrun_push",
    "POST /api/nightrun/quiz _api_nightrun_quiz",
    "POST /api/nightrun/start _api_nightrun_start",
    "POST /api/notifications _api_notifications",
    "POST /api/notifications/read _api_notifications_read",
    "POST /api/notifications/seed_all _api_notifications_seed_all",
    "POST /api/notifications/seed_patchnote _api_notifications_seed_patchnote",
    "POST /api/onboard _api_onboard",
    "POST /api/panel _api_panel",
    "POST /api/prod_claim _api_prod_claim",
    "POST /api/prod_start _api_prod_start",
    "POST /api/raid _api_raid",
    "POST /api/raid/hit _api_raid_hit",
    "POST /api/raid/join _api_raid_join",
    "POST /api/raid/seed _api_raid_seed",
    "POST /api/raid/summon _api_raid_summon",
    "POST /api/rating _api_rating",
    "POST /api/referral _api_referral",
    "POST /api/reputation _api_reputation",
    "POST /api/retail_hold _api_retail_hold",
    "POST /api/retail_sell _api_retail_sell",
    "POST /api/sharpen _api_sharpen",
    "POST /api/state _api_state",
    "POST /api/story_choice _api_story_choice",
    "POST /api/torg _api_torg",
    "POST /api/torg/buy _api_torg_buy",
    "POST /api/trade _api_trade",
    "POST /api/upgrade _api_upgrade",
    "POST /api/whoami _api_whoami",
]


def _actual() -> list[str]:
    from bot import webapp
    app = webapp.build_app()
    rows = []
    for r in app.router.routes():
        if r.method == "HEAD":          # aiohttp сам добавляет HEAD к GET
            continue
        res = r.resource.canonical if r.resource else "?"
        rows.append(f"{r.method} {res} {getattr(r.handler, '__name__', '?')}")
    return sorted(rows)


def test_route_table_unchanged():
    actual = _actual()
    missing = sorted(set(ROUTES) - set(actual))
    extra = sorted(set(actual) - set(ROUTES))
    assert not missing and not extra, (
        "роуты разъехались! Пропали: %r Появились: %r" % (missing, extra))


def test_webapi_modules_have_no_undefined_names():
    """Гард распила: в вынесенном модуле не осталось ссылок на имена, живущие в
    монолите (компиляция такого не ловит — упало бы в рантайме у игрока). Ровно
    так при выносе nightrun чуть не потерялись _NR_KIND/_NR_HINT."""
    import ast
    import builtins
    import pathlib

    def undefined(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined, used = {"__file__", "__name__"}, set()

        class V(ast.NodeVisitor):
            def visit_FunctionDef(self, n):
                defined.add(n.name)
                args = n.args.args + n.args.kwonlyargs
                for extra in (n.args.vararg, n.args.kwarg):
                    if extra:
                        args.append(extra)
                for a in args:
                    defined.add(a.arg)
                self.generic_visit(n)
            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Lambda(self, n):
                for a in n.args.args + n.args.kwonlyargs:
                    defined.add(a.arg)
                self.generic_visit(n)

            def visit_ClassDef(self, n):
                defined.add(n.name)
                self.generic_visit(n)

            def visit_Name(self, n):
                (defined if isinstance(n.ctx, (ast.Store, ast.Del)) else used).add(n.id)

            def visit_Import(self, n):
                for a in n.names:
                    defined.add((a.asname or a.name).split(".")[0])

            def visit_ImportFrom(self, n):
                for a in n.names:
                    defined.add(a.asname or a.name)

            def visit_comprehension(self, n):
                for t in ast.walk(n.target):
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
                self.generic_visit(n)

            def visit_ExceptHandler(self, n):
                if n.name:
                    defined.add(n.name)
                self.generic_visit(n)

            def visit_With(self, n):
                for item in n.items:
                    if item.optional_vars:
                        for t in ast.walk(item.optional_vars):
                            if isinstance(t, ast.Name):
                                defined.add(t.id)
                self.generic_visit(n)
            visit_AsyncWith = visit_With

            def visit_For(self, n):
                for t in ast.walk(n.target):
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
                self.generic_visit(n)
            visit_AsyncFor = visit_For

            def visit_Global(self, n):
                for nm in n.names:
                    defined.add(nm)

        V().visit(tree)
        return sorted(u for u in used - defined if not hasattr(builtins, u))

    pkg = pathlib.Path(__file__).resolve().parent.parent / "bot" / "webapi"
    problems = {p.name: bad for p in sorted(pkg.glob("*.py"))
                if (bad := undefined(p))}
    assert not problems, f"неопределённые имена в webapi: {problems}"


def test_real_request_through_middleware():
    """Живой HTTP-запрос сквозь всю цепочку (middleware → хендлер), без БД.
    Ловит класс ошибок, невидимый снапшоту: на распиле декоратор @web.middleware
    уехал с вырезом — app собирался, но КАЖДЫЙ запрос падал 500 в проде."""
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from bot import webapp

    async def run():
        async with TestClient(TestServer(webapp.build_app())) as c:
            r = await c.get("/")                      # health сквозь middleware
            assert r.status == 200 and (await r.text()) == "ok"
            r = await c.post("/api/state", json={})   # без initData → чистый 401
            assert r.status == 401
            assert (await r.json())["error"] == "auth"
            r = await c.get("/avatar/1.badsig")       # подпись мимо → 404
            assert r.status == 404

    asyncio.run(run())


def test_facade_exports_for_outside_users():
    """Внешние потребители webapp (main, notifier, тесты) — фасад обязан отдавать."""
    from bot import webapp
    for name in ("run_webapp", "build_app", "base_url", "snapshot_rating_ranks",
                 "_ranked", "_rating_board", "_rating_entries", "_rating_leaders",
                 "_trend_record", "_trend_baseline", "_trend_hydrate", "_ava_sig",
                 "_RANK_SNAPS", "_RATING_METRICS", "_RATING_TOP", "_world_continents"):
        assert hasattr(webapp, name), "фасад потерял " + name
