"""Mini App: интерактивная карта мира (Telegram Web App).

Маленький aiohttp-сервер РЯДОМ с ботом (тот же процесс, слушает $PORT — Railway
выдаёт публичный домен). Отдаёт:
  GET /            — health-check
  GET /map         — HTML-страница карты (Leaflet CRS.Simple + кластеры)
  GET /api/taverns — JSON таверн (норм. координаты слота, имя, уровень, регион)
  /assets/...      — статика (world.png, спрайты)

Карта — НЕ гео: это наш нарисованный world.png. Leaflet с CRS.Simple кладёт его
как imageOverlay, маркеры группируются кластерами — лимита на число таверн нет.
Платных картсервисов не нужно; Leaflet/markercluster тянутся с CDN.
"""

import os

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap

ASSETS_DIR = worldmap.ASSETS_DIR


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
            "mine": bool(uid) and pl.id == uid,
        })
    return web.json_response(
        {"taverns": out, "regions": balance.REGIONS},
        headers={"Cache-Control": "no-store"})


async def _map_page(request: web.Request) -> web.Response:
    return web.Response(text=_MAP_HTML, content_type="text/html")


async def _world_png(request: web.Request) -> web.Response:
    return web.FileResponse(worldmap.MAP_FILE)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/map", _map_page)
    app.router.add_get("/api/taverns", _api_taverns)
    app.router.add_get("/assets/world.png", _world_png)   # только карта, не вся папка
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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
  html,body{margin:0;height:100%;background:#140d06;font:14px/1.4 Georgia,serif;color:#f3e6c8}
  #map{position:absolute;inset:0;background:#140d06}
  .leaflet-container{background:#140d06}
  .pin{display:flex;align-items:center;justify-content:center;width:26px;height:26px;
    border-radius:50%;border:2px solid #2a1a0a;color:#fff;font:700 12px Georgia,serif;
    box-shadow:0 2px 6px rgba(0,0,0,.6)}
  .pin.me{border-color:#ffd24a;box-shadow:0 0 0 3px #ffd24a88,0 2px 8px #000}
  .leaflet-popup-content-wrapper{background:#2a1d10;color:#f3e6c8;border:1px solid #5a4527}
  .leaflet-popup-tip{background:#2a1d10}
  .leaflet-popup-content b{color:#f6dca0}
  .bar{position:absolute;left:8px;top:8px;z-index:1000;background:#241809cc;border:1px solid #5a4527;
    border-radius:10px;padding:6px 10px;font-size:12px;color:#e9d6a8;backdrop-filter:blur(3px)}
  .leaflet-bar a{background:#2a1d10;color:#f3e6c8;border-bottom:1px solid #5a4527}
</style></head>
<body>
<div id="map"></div>
<div class="bar" id="bar">🗺 Карта Недоливска · загрузка…</div>
<script>
const tg = window.Telegram?.WebApp; if (tg){ tg.ready(); tg.expand(); }
const myId = tg?.initDataUnsafe?.user?.id || 0;
const COLORS = {north_wilds:'#5b8def', green_valleys:'#5fb36a', red_wastes:'#c9603f'};

const img = new Image();
img.src = '/assets/world.png';
img.onload = () => {
  const W = img.naturalWidth, H = img.naturalHeight;
  const map = L.map('map', {crs: L.CRS.Simple, minZoom: -5, maxZoom: 4,
                           zoomControl: true, attributionControl: false});
  const bounds = [[0,0],[H,W]];
  L.imageOverlay(img.src, bounds).addTo(map);
  map.fitBounds(bounds);
  map.setMaxBounds(L.latLngBounds(bounds).pad(0.2));

  fetch('/api/taverns?uid=' + encodeURIComponent(myId)).then(r => r.json()).then(data => {
    const regions = data.regions || {};
    const cluster = L.markerClusterGroup({maxClusterRadius: 44, showCoverageOnHover:false});
    let mine = null;
    data.taverns.forEach(t => {
      const lat = (1 - t.y) * H, lng = t.x * W;        // норм.(от верха) → CRS.Simple
      const me = !!t.mine;
      const col = COLORS[t.region] || '#caa23f';
      const icon = L.divIcon({className:'', iconSize:[26,26],
        html:`<div class="pin ${me?'me':''}" style="background:${col}">${t.level}</div>`});
      const m = L.marker([lat,lng], {icon});
      m.bindPopup(`<b>${esc(t.name)}</b><br>Уровень ${t.level}<br>`+
                  `<span style="color:#c2a878">${esc(regions[t.region]||t.region)}</span>`+
                  (me?'<br>🏠 <b>Твоя таверна</b>':''));
      if (me) mine = [lat,lng];
      cluster.addLayer(m);
    });
    map.addLayer(cluster);
    document.getElementById('bar').textContent =
      `🗺 Недоливск · таверн на карте: ${data.taverns.length}`;
    if (mine) map.setView(mine, 1);
  }).catch(e => { document.getElementById('bar').textContent = '⚠ не загрузить таверны'; });
};
img.onerror = () => { document.getElementById('bar').textContent = '⚠ карта не загрузилась'; };
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
</script>
</body></html>"""
