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

import os

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import balance, worldmap
from bot.game import raid as raidmod

ASSETS_DIR = worldmap.ASSETS_DIR

# Какой спрайт-орк рисуем для какого босса (арт CraftPix: 3 орка). Фолбэк — 1.
BOSS_SPRITE = {"rat_king": 1, "bog_troll": 2, "dragon": 3}
BOSS_POS = (0.5, 0.40)   # «логово» босса-ивента на карте (норм. координаты)


def _boss_payload(raid) -> dict | None:
    """Данные босса-ивента для карты из живого рейда (или None)."""
    if raid is None:
        return None
    spec = raidmod.BOSSES.get(raid.boss_key)
    if spec is None:
        return None
    return {
        "name": spec.name, "emoji": spec.emoji,
        "sprite": BOSS_SPRITE.get(raid.boss_key, 1),
        "x": BOSS_POS[0], "y": BOSS_POS[1],
        "hp": int(raid.hp or 0), "max_hp": int(raid.max_hp or 0),
        "status": raid.status,
    }


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
        raid = await repo.get_active_raid(s)
    # босс-ивент: живой рейд, либо демо для предпросмотра (?boss=demo)
    if request.query.get("boss") == "demo":
        boss = {"name": "Болотный Тролль", "emoji": "👹", "sprite": 2,
                "x": BOSS_POS[0], "y": BOSS_POS[1], "hp": 1400, "max_hp": 2000,
                "status": "active"}
    else:
        boss = _boss_payload(raid)
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
    return web.json_response(
        {"taverns": out, "regions": balance.REGIONS, "boss": boss},
        headers={"Cache-Control": "no-store"})


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


async def _boss_sprite(request: web.Request) -> web.Response:
    # IDLE-стрип орка-босса (1..3): 10 кадров в ряд для AnimatedSprite на карте.
    try:
        n = int(request.match_info["n"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    p = ASSETS_DIR / "boss" / f"ork{n}_idle.png"
    if not (1 <= n <= 3) or not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/map", _map_page)
    app.router.add_get("/api/taverns", _api_taverns)
    app.router.add_get("/assets/world.png", _world_png)   # земля диорамы
    app.router.add_get("/assets/map_tavern_{n}.png", _tavern_sprite)  # здания
    app.router.add_get("/assets/boss/ork{n}_idle.png", _boss_sprite)  # босс-ивент
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
  .bar{position:fixed;left:8px;top:8px;z-index:10;background:#241809d8;border:1px solid #5a4527;
    border-radius:10px;padding:6px 11px;font-size:12px;color:#e9d6a8;backdrop-filter:blur(3px)}
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
</style></head>
<body>
<div class="vig"></div>
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
  const markers = new PIXI.Container(); markers.sortableChildren = true;
  app.stage.addChild(markers);
  const bossLayer = new PIXI.Container(); app.stage.addChild(bossLayer);  // босс-ивент поверх
  let bossNode = null;

  // минимальный зум = «вся карта в экране» с небольшим запасом → вокруг материка
  // видна кайма моря/тумана (плюс виньетка). Снапится по центру, меньше не сжать.
  const SEA_FRAME = 0.9;   // <1 → материк чуть меньше экрана, вокруг полоса моря
  let minScale = Math.min(app.screen.width/W, app.screen.height/H) * SEA_FRAME;
  world.scale.set(minScale); clampCam();

  // --- таверны ---
  const demoBoss = new URLSearchParams(location.search).get('boss');  // ?boss=demo — предпросмотр
  let data;
  try { data = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId)
        + (demoBoss ? '&boss='+encodeURIComponent(demoBoss) : ''))).json(); }
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
    if (bossNode){ const s = screenOf(bossNode.wx, bossNode.wy);
      bossNode.x = s.x; bossNode.y = s.y; bossNode.scale.set(k * 0.62); }  // босс крупнее таверн
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
  bar.textContent = '🗺 Недоливск · таверн на карте: ' + taverns.length;
  const mine = taverns.find(t=>t.mine);
  if (mine) centerOn(mine.wx, mine.wy, Math.max(minScale, 0.85)); else refresh();
  window.addEventListener('resize', () => {
    minScale = Math.min(app.screen.width/W, app.screen.height/H) * SEA_FRAME;
    if (world.scale.x < minScale) world.scale.set(minScale);
    clampCam(); refresh();
  });

  // ---------- босс-ивент (анимированный) ----------
  if (data.boss){
    try {
      const b = data.boss;
      const tex = await PIXI.Assets.load('/assets/boss/ork'+b.sprite+'_idle.png');
      const fw = tex.width/10, fh = tex.height;   // стрип = 10 равных кадров в ряд
      const frames = [];
      for (let i=0;i<10;i++)
        frames.push(new PIXI.Texture({source:tex.source, frame:new PIXI.Rectangle(i*fw,0,fw,fh)}));
      bossNode = buildBoss(b, frames, fw, fh);
      bossLayer.addChild(bossNode);
      app.ticker.add(() => { if (bossNode) bossNode._aura.alpha =
        0.10 + 0.12*(0.5 + 0.5*Math.sin(performance.now()/650)); });   // пульс ауры
      refresh();
    } catch(e){ console.log('boss load fail', e); }
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
  function buildBoss(b, frames, fw, fh){
    const node = new PIXI.Container(); node.wx = b.x*W; node.wy = b.y*H;
    const aura = new PIXI.Graphics().ellipse(0, -fh*0.42, fw*0.62, fh*0.5).fill({color:0xff3b30, alpha:0.16});
    node.addChild(aura); node._aura = aura;
    node.addChild(new PIXI.Graphics().ellipse(0,0, fw*0.4, fw*0.13).fill({color:0x000000, alpha:0.42}));
    const anim = new PIXI.AnimatedSprite(frames); anim.animationSpeed = 0.12; anim.anchor.set(0.5,1); anim.play();
    anim.eventMode='static'; anim.cursor='pointer'; anim.on('pointertap', e=> showBossCard(b, e));
    node.addChild(anim);
    const barW = fw*0.82, barH = 12, by = -fh - 18;   // HP-бар над боссом
    node.addChild(new PIXI.Graphics().roundRect(-barW/2, by, barW, barH, 4)
      .fill({color:0x140d06, alpha:0.85}).stroke({color:0x6b522e, width:1}));
    const frac = b.max_hp>0 ? Math.max(0, Math.min(1, b.hp/b.max_hp)) : 1;
    if (frac > 0) node.addChild(new PIXI.Graphics()
      .roundRect(-barW/2+1.5, by+1.5, (barW-3)*frac, barH-3, 3).fill({color:0xc0392b}));
    const lab = new PIXI.Text({text:'⚔ '+(b.emoji||'')+' '+b.name, style:{fontFamily:'Georgia,serif',
      fontSize:15, fontWeight:'700', fill:0xffd9a8, stroke:{color:0x140d06, width:4}}});
    lab.anchor.set(0.5,1); lab.y = by - 5; node.addChild(lab);
    return node;
  }
  function showBossCard(b, e){
    if (e) e.stopPropagation();
    const pct = b.max_hp>0 ? Math.round(100*b.hp/b.max_hp) : 100;
    document.getElementById('cnm').textContent = '⚔ ' + b.name;
    document.getElementById('clv').textContent = 'HP ' + pct + '%';
    document.getElementById('crg').textContent = b.status==='gathering'
      ? 'Сбор бойцов — вступай в таверне' : 'РЕЙД-БОСС — бей в таверне!';
    document.getElementById('cme').style.display = 'none';
    card.classList.add('show');
  }
  document.getElementById('cardx').onclick = () => card.classList.remove('show');
})();
</script>
</body></html>"""
