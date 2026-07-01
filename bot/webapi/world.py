"""Карты мира: старая PNG-карта (/map) и тайловый мир-атлас (/world) с тавернами,
континентами, коронами лидеров. Перенесено из bot/webapp.py дословно (move-only)."""

import pathlib

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import worldmap
from bot.webapi.rating import _rating_entries, _rating_leaders

# Пирамида тайлов мира (генерится в Docker из assets/world25.jpg тайлером worldgen/tiler.py).
WORLD_TILES = pathlib.Path(__file__).resolve().parent.parent.parent / "world_tiles"

async def _map_page(request: web.Request) -> web.Response:
    return web.Response(text=_MAP_HTML, content_type="text/html")


async def _world_png(request: web.Request) -> web.Response:
    return web.FileResponse(worldmap.MAP_FILE)


# ── Новый мир-атлас: тайловая Leaflet-карта (огромный бесшовный мир из 25 континентов) ──
_WORLD_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=PT+Serif:wght@700&display=swap">
<title>Мир Недоливска</title>
<style>
:root{--serif:'PT Serif',Georgia,'Times New Roman',serif}
html,body{margin:0;height:100%;background:#0f1828;overflow:hidden;font-family:system-ui,sans-serif}
#map{height:100%}.leaflet-container{background:transparent;font-family:inherit}
/* LQIP: мгновенное размытое превью мира (z0-тайл) — карта появляется без тёмной паузы */
#lqip{position:fixed;inset:0;z-index:0;pointer-events:none;background:#0f1828 center/cover no-repeat;
  filter:blur(14px) saturate(1.15) brightness(.92);transform:scale(1.14);transition:opacity .7s ease;will-change:opacity}
#lqip.gone{opacity:0}
/* маяк своей таверны — «сонар»-пульс, всегда видно дом (1 объект → перф ок) */
.tav-pin.mine .beacon{position:absolute;left:50%;top:54%;width:78%;height:78%;transform:translate(-50%,-50%);
  border-radius:50%;border:2px solid rgba(255,214,130,.85);box-shadow:0 0 10px rgba(255,200,110,.5);
  animation:ping 2.3s cubic-bezier(.2,.7,.3,1) infinite;pointer-events:none}
@keyframes ping{0%{transform:translate(-50%,-50%) scale(.45);opacity:.95}70%{opacity:0}100%{transform:translate(-50%,-50%) scale(1.7);opacity:0}}
@media (prefers-reduced-motion:reduce){.tav-pin.mine .beacon{animation:none;opacity:.45;transform:translate(-50%,-50%) scale(1.1)}}
/* кинематографичное обрамление: виньетка по краям + тёплый световой грейд (статично, без blur) */
#frame{position:fixed;inset:0;z-index:480;pointer-events:none;transform:translateZ(0);
  box-shadow:inset 0 0 110px 26px rgba(5,8,16,.82),inset 0 0 280px 70px rgba(5,8,16,.34);
  background:radial-gradient(125% 95% at 50% 40%,rgba(255,208,128,.05),rgba(8,12,24,0) 46%,rgba(5,8,16,.34) 100%)}
.leaflet-control-zoom{margin-bottom:16px!important;margin-right:12px!important;border:none!important}
.leaflet-control-zoom a{background:rgba(16,22,38,.85)!important;color:#f3dca0!important;
  border:1px solid #4a3a1e!important;width:34px!important;height:34px!important;line-height:32px!important}
/* шапка-баннер */
#hud{position:fixed;left:0;right:0;top:0;z-index:1000;display:flex;align-items:center;gap:8px;
  padding:calc(env(safe-area-inset-top,0px) + 9px) 12px 12px;pointer-events:none;
  background:linear-gradient(180deg,rgba(7,10,20,.95),rgba(7,10,20,.5) 62%,rgba(7,10,20,0))}
#title{font-family:var(--serif);font-weight:700;font-size:16px;color:#f3dca0;text-shadow:0 1px 5px #000;
  flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#title b{color:#ffd57a}#cnt{color:#c0a26a;font-weight:400;font-size:13px}
#mine{pointer-events:auto;flex:none;white-space:nowrap;border:1px solid #c79a44;border-radius:999px;
  padding:6px 14px;font-weight:700;font-size:13px;color:#241405;cursor:pointer;font-family:var(--serif);
  background:linear-gradient(180deg,#ffe09a,#dca03c);box-shadow:0 2px 9px rgba(220,160,40,.45),inset 0 1px 0 rgba(255,255,220,.5)}
/* баннер рейда */
#raidbar{position:fixed;left:8px;right:8px;top:calc(env(safe-area-inset-top,0px) + 48px);z-index:1000;
  display:none;align-items:center;gap:9px;padding:9px 13px;border-radius:14px;cursor:pointer;font-family:var(--serif);
  color:#fff;font-weight:700;font-size:14px;background:linear-gradient(180deg,#d23a18,#9a2a10);
  border:1px solid #ff7a4a;box-shadow:0 4px 16px rgba(210,58,24,.5);animation:rb 1.6s ease-in-out infinite}
@keyframes rb{0%,100%{box-shadow:0 4px 16px rgba(210,58,24,.45)}50%{box-shadow:0 4px 26px rgba(255,90,50,.8)}}
#raidbar .go{margin-left:auto;opacity:.85}
/* названия регионов — «гравировка»: разрядка + halo, без плашки, ПОД пинами */
.cont-label{width:240px!important;display:flex;align-items:center;justify-content:center;
  pointer-events:none;transition:opacity .18s}
.cl-plate{display:inline-flex;align-items:center;gap:7px;white-space:nowrap;font-family:var(--serif);
  font-weight:700;font-size:15px;letter-spacing:.10em;color:#f4e7c8;
  text-shadow:0 0 5px #000,0 0 11px rgba(0,0,0,.95),0 1px 2px #000}
.cl-plate .ci{font-size:13px;letter-spacing:0;filter:drop-shadow(0 0 3px #000)}
/* подпись таверны (на близком зуме) */
.leaflet-tooltip.tav-label{background:rgba(10,14,24,.85);border:1px solid #6b522e;color:#f3dca0;
  font-family:var(--serif);font-weight:700;font-size:11px;border-radius:7px;padding:1px 7px;
  box-shadow:0 1px 6px rgba(0,0,0,.5);opacity:0;transition:opacity .18s}
.leaflet-tooltip.tav-label::before{display:none}
/* пин таверны: спрайт-здание + тень на земле + бейдж уровня */
.tav-pin .sh{position:absolute;left:50%;bottom:1px;width:60%;height:13%;transform:translateX(-50%);
  background:radial-gradient(ellipse,rgba(0,0,0,.5),rgba(0,0,0,0) 70%);border-radius:50%}
.tav-pin img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
  filter:drop-shadow(0 2px 3px rgba(0,0,0,.55))}
/* «огонёк» таверны — на далёком зуме вместо здания (плотность = густота огней, без цифр) */
.tav-pin .glow{position:absolute;left:50%;top:54%;width:18px;height:18px;transform:translate(-50%,-50%);
  border-radius:50%;background:radial-gradient(circle,#fff4d6 0%,#ffcf6a 22%,rgba(255,170,60,.55) 46%,rgba(255,150,40,0) 74%);
  box-shadow:0 0 11px 3px rgba(255,185,90,.65),0 0 4px 1px rgba(255,225,160,.95);opacity:0;transition:opacity .28s}
.tav-pin .sh,.tav-pin img,.tav-pin .lv{transition:opacity .28s}
body.far .tav-pin .glow{opacity:1}
body.far .tav-pin img,body.far .tav-pin .sh,body.far .tav-pin .lv,body.far .tav-pin .beacon{opacity:0}
.tav-pin.mine .glow{width:24px;height:24px;background:radial-gradient(circle,#fffaf0 0%,#ffe09a 24%,rgba(255,200,90,.6) 48%,rgba(255,170,50,0) 74%);
  box-shadow:0 0 16px 5px rgba(255,205,110,.8),0 0 6px 2px rgba(255,235,180,1)}
body.far .tav-pin.mine .glow{animation:glowpulse 1.9s ease-in-out infinite}
@keyframes glowpulse{0%,100%{opacity:1;transform:translate(-50%,-50%) scale(1)}50%{opacity:.7;transform:translate(-50%,-50%) scale(1.22)}}
@media (prefers-reduced-motion:reduce){body.far .tav-pin.mine .glow{animation:none}}
/* корона лидера города (топ-1 по ВВП/славе/уровню) — парит над зданием */
.tav-pin .crown{position:absolute;left:50%;top:-15px;transform:translateX(-50%);font-size:15px;line-height:1;
  filter:drop-shadow(0 0 5px rgba(255,210,100,.95)) drop-shadow(0 2px 3px rgba(0,0,0,.6));transition:opacity .28s;z-index:3}
body.far .tav-pin .crown{opacity:0}
.tav-pin.crowned .glow{width:24px;height:24px;box-shadow:0 0 15px 5px rgba(255,200,95,.85),0 0 6px 2px rgba(255,235,180,1)}
.leaflet-tooltip.tav-label.tl-crown{border-color:#c9a24f;color:#ffe9a8;box-shadow:0 0 8px rgba(231,180,74,.5)}
.tav-pop .title{margin:2px 0;font:700 11.5px/1.3 var(--serif);color:#ffd97a}
.tav-pin .lv{position:absolute;top:-3px;right:-3px;min-width:15px;height:15px;padding:0 3px;box-sizing:border-box;
  display:flex;align-items:center;justify-content:center;border-radius:999px;font:700 10px/1 var(--serif);
  color:#241405;background:linear-gradient(180deg,#ffe09a,#d99a36);border:1px solid #8a6a22;
  box-shadow:0 1px 3px rgba(0,0,0,.5)}
.tav-pin.mine img{filter:drop-shadow(0 0 8px #ffd27a) drop-shadow(0 2px 3px rgba(0,0,0,.6))}
.tav-pin.mine .lv{background:linear-gradient(180deg,#fff0c0,#f0b840)}
/* карточка таверны */
.tav-pop{font-family:var(--serif);font-weight:400;font-size:13px;line-height:1.5;color:#e9dcc2;min-width:178px}
.tav-pop .h{font-weight:700;font-size:15px;color:#ffcf6a;margin-bottom:1px}
.tav-pop .o{color:#bfa775;font-size:12px;margin-bottom:6px}
.tav-pop .loc{color:#8fb0d8;font-size:12px}
.tav-pop .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:5px;font-size:12px;color:#d8c8a6}
.tav-pop .mine{margin-top:7px;color:#ffd27a;font-weight:700}
.leaflet-popup-content-wrapper{background:#1a140c;border:1px solid #6b522e;border-radius:12px}
.leaflet-popup-tip{background:#1a140c}
/* лоадер */
#loader{position:fixed;inset:0;z-index:1500;display:flex;align-items:center;justify-content:center;
  background:#0f1828;color:#caa86a;font-weight:700;font-size:15px;transition:opacity .4s}
#loader.hide{opacity:0;pointer-events:none}
</style></head>
<body>
<div id="lqip"></div>
<div id="map"></div>
<div id="frame"></div>
<div id="hud"><div id="title">🗺 <b>Мир Недоливска</b> <span id="cnt"></span></div>
  <button id="mine">🏰 Моя таверна</button></div>
<div id="raidbar"></div>
<div id="loader">Разворачиваем карту мира…</div>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var tg=window.Telegram&&Telegram.WebApp;
if(tg){tg.ready();tg.expand();try{tg.setHeaderColor&&tg.setHeaderColor('#0f1828');}catch(e){}}
var W=11020,H=11020,TILE=256,MAXZ=6;
for(var _i=1;_i<=9;_i++){(new Image()).src='/assets/map_tavern_'+_i+'.png';}  // прелоад спрайтов — без «пыхов»
var map=L.map('map',{crs:L.CRS.Simple,maxZoom:MAXZ+1,attributionControl:false,zoomControl:false,
  zoomSnap:0,zoomDelta:.6,wheelPxPerZoomLevel:90,inertia:true});
L.control.zoom({position:'bottomright'}).addTo(map);
// слой названий регионов — ПОД пинами/монетами (как в стратегиях: имя региона на фоне)
map.createPane('contPane');map.getPane('contPane').style.zIndex=450;map.getPane('contPane').style.pointerEvents='none';
function px(x,y){return map.unproject([x,y],MAXZ);}
var bounds=L.latLngBounds(px(0,H),px(W,0));
var _lq=document.getElementById('lqip');if(_lq){_lq.style.backgroundImage="url('/world/tiles/0/0/0.webp')";}
function _hideLqip(){if(_lq)_lq.classList.add('gone');}
var tiles=L.tileLayer('/world/tiles/{z}/{x}/{y}.webp',{tileSize:TILE,noWrap:true,bounds:bounds,
  maxNativeZoom:MAXZ,maxZoom:MAXZ+1,keepBuffer:8,updateWhenZooming:true,updateWhenIdle:false,detectRetina:true}).addTo(map);
tiles.on('load',_hideLqip);setTimeout(_hideLqip,3500);  // гасим превью после загрузки (или по таймауту)
// прелоад нижней пирамиды z0-3 (~50 мелких webp) — обзор/зум-аут мгновенные, при зуме всегда есть базовый слой
function _prefetch(){for(var z=0;z<=3;z++){var n=Math.ceil(W*Math.pow(2,z-MAXZ)/TILE);
  for(var x=0;x<n;x++)for(var y=0;y<n;y++){(new Image()).src='/world/tiles/'+z+'/'+x+'/'+y+'.webp';}}}
setTimeout(_prefetch,1400);
// стартовый валидный вид сразу (на случай, если cover-расчёт задержится в WebView)
map.setView(px(W/2,H/2),2);
map.setMaxBounds(bounds.pad(0.04));
// «Cover»: мир ЗАПОЛНЯЕТ экран (без чёрных полей). minZoom = зум покрытия, старт по центру.
// В WebView/iframe контейнер на whenReady часто ещё нулевой высоты → getSize()=0 →
// log2(0)=-Infinity ломает карту. Поэтому пересчитываем размер и ждём, пока разложится.
function fit(){
  map.invalidateSize(false);
  var s=map.getSize();
  if(!s||s.x<40||s.y<40){setTimeout(fit,100);return;}
  var cz=MAXZ+Math.log2(Math.max(s.x,s.y)/W*1.02);
  if(!isFinite(cz)){cz=2;}
  map.setMinZoom(cz);
  if(!map._c){map.setView(px(W/2,H/2),cz,{animate:false});map._c=true;}
}
map.whenReady(fit);window.addEventListener('load',fit);
setTimeout(fit,350);setTimeout(fit,1200);
window.addEventListener('resize',function(){map._c=false;fit();});
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
var uid=(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user&&tg.initDataUnsafe.user.id)||parseInt(new URLSearchParams(location.search).get('uid')||'0',10)||0;
// ── подписи континентов (видны на дальнем зуме) ──
var contLayer=L.layerGroup();var contMarkers=[];
var BICON={snow:'❄',green:'🌿',desert:'☀'};
fetch('/world/slots.json').then(function(r){return r.json();}).then(function(cs){
  cs.forEach(function(c){
    var bi=BICON[c.biome]||'•';
    var cm=L.marker(px(c.x*W,c.y*H),{interactive:false,keyboard:false,pane:'contPane',
      icon:L.divIcon({className:'cont-label',iconSize:[240,26],iconAnchor:[120,30],
        html:'<span class="cl-plate"><span class="ci">'+bi+'</span>'+esc(c.name)+'</span>'})}).addTo(contLayer);
    contMarkers.push({m:cm});
  });
  queueRelayout();
}).catch(function(){});
// ── Коллайдер подписей (механика антикаши): имена таверн рисуются по приоритету
//    (своя > уровень+реп); налезающие на монеты/пины/друг друга — плавно прячутся.
//    Континенты — на дальнем зуме. Пересчёт на zoomend/moveend и сменах кластеров.
var mapEl=document.getElementById('map');
function _box(el,pad){var r=el.getBoundingClientRect();if(!r.width)return null;var m=mapEl.getBoundingClientRect();
  pad=pad||0;return {x0:r.left-m.left-pad,y0:r.top-m.top-pad,x1:r.right-m.left+pad,y1:r.bottom-m.top+pad};}
function _hit(a,b){return a.x0<b.x1&&a.x1>b.x0&&a.y0<b.y1&&a.y1>b.y0;}
var _rq=false;
function relayout(){_rq=false;var z=map.getZoom(),i;
  document.body.classList.toggle('far', z<3.0);   // далёкий зум → «огни»; здания проступают раньше (z>=3.0)
  var showCont=z<=3;
  if(showCont){if(!map.hasLayer(contLayer))contLayer.addTo(map);}
  else{if(map.hasLayer(contLayer))map.removeLayer(contLayer);}
  var showNames=z>=3.6,occ=[],cand=[];
  // названия регионов: раскладка без ВЗАИМНЫХ наложений (они под пинами/монетами; halo)
  if(showCont){contMarkers.forEach(function(o){var el=o.m.getElement&&o.m.getElement();if(!el)return;
    var b=_box(el,4);if(!b){el.style.opacity=0;return;}
    var ok=true;for(var j=0;j<occ.length;j++){if(_hit(b,occ[j])){ok=false;break;}}
    if(ok){el.style.opacity=1;occ.push(b);}else{el.style.opacity=0;}});}
  tavMarkers.forEach(function(o){var tt=o.m.getTooltip&&o.m.getTooltip();var el=tt&&tt.getElement&&tt.getElement();
    if(!el)return;o._el=el;
    if(!showNames){el.style.opacity=o.mine?1:0;return;}
    cand.push(o);});
  if(showNames){cand.sort(function(a,b){return b.prio-a.prio;});
    cand.forEach(function(o){var b=_box(o._el,2);if(!b){o._el.style.opacity=0;return;}
      var ok=true;for(var i=0;i<occ.length;i++){if(_hit(b,occ[i])){ok=false;break;}}
      if(ok||o.mine){o._el.style.opacity=1;occ.push(b);}else{o._el.style.opacity=0;}});}
}
function queueRelayout(){if(_rq)return;_rq=true;requestAnimationFrame(relayout);}
map.on('zoomend moveend',queueRelayout);
// ── таверны ── БЕЗ кластеризации: на далёком зуме каждая таверна = «огонёк»
// (плотность видна густотой огней, без счётчиков), при приближении огонёк → здание-пин.
var cluster=null;var layer=map;var myLL=null;var myMarker=null;var tavMarkers=[];
var TITLES={gdp:'👑 Богатейший кабак города',rep:'⭐ Самый славный кабак',level:'🏰 Высочайший кабак'};
function crownEmoji(cr){return cr.indexOf('gdp')>=0?'👑':(cr.indexOf('rep')>=0?'⭐':'🏆');}
function card(t){
  var titles=(t.crowns||[]).map(function(k){return '<div class="title">'+TITLES[k]+'</div>';}).join('');
  return '<div class="tav-pop"><div class="h">🏰 '+esc(t.name)+'</div>'+
    '<div class="o">хозяин: '+esc(t.owner)+'</div>'+titles+
    '<div class="loc">📍 '+esc(t.continent)+'</div>'+
    '<div class="row"><span>⚜️ ур. '+t.level+'</span><span>⭐ реп. '+t.rep+'</span>'+
    '<span>👥 '+t.cap+'</span><span>☕ уют '+t.comfort+'</span><span>🏛 '+t.builds+'</span></div>'+
    (t.mine?'<div class="mine">★ твоя таверна</div>':'')+'</div>';
}
fetch('/world/taverns.json?uid='+uid).then(function(r){return r.json();}).then(function(d){
  var tv=d.taverns||[];
  document.getElementById('cnt').textContent='· '+(d.total||tv.length)+' таверн';
  tv.forEach(function(t){
    var crowned=(t.crowns||[]).length>0;
    var sz=t.mine?56:42;var ll=px(t.x*W,t.y*H);
    var icon=L.divIcon({className:'tav-pin'+(t.mine?' mine':'')+(crowned?' crowned':''),iconSize:[sz,sz],
      iconAnchor:[sz/2,sz*0.9],popupAnchor:[0,-sz*0.82],
      html:'<div class="glow"></div>'+(t.mine?'<div class="beacon"></div>':'')+
        (crowned?'<div class="crown">'+crownEmoji(t.crowns)+'</div>':'')+
        '<div class="sh"></div><img src="/assets/map_tavern_'+t.tier+'.png" alt="" decoding="async"><div class="lv">'+t.level+'</div>'});
    var m=L.marker(ll,{icon:icon,zIndexOffset:t.mine?1000:(crowned?900:0)}).addTo(layer).bindPopup(card(t));
    m.bindTooltip(esc(t.name),{permanent:true,direction:'top',className:'tav-label'+(t.mine?' tl-mine':'')+(crowned?' tl-crown':''),offset:[0,-sz*0.78]});
    tavMarkers.push({m:m,mine:!!t.mine,prio:t.mine?1e9:(crowned?5e8:0)+(t.level*1000+(t.rep||0))});
    if(t.mine){myLL=ll;myMarker=m;}
  });
  if(cluster){map.addLayer(cluster);cluster.on('animationend',queueRelayout);}
  queueRelayout();setTimeout(queueRelayout,300);
  // баннер рейда
  if(d.raid){var rb=document.getElementById('raidbar');
    rb.innerHTML=d.raid.emoji+' <span>'+esc(d.raid.name)+' — '+(d.raid.status==='gathering'?'идёт сбор!':'В БОЙ!')+'</span><span class="go">играть ›</span>';
    rb.style.display='flex';rb.onclick=function(){(window.top||window).location.href='/app/?startapp=raid';};}
  // кнопка «моя таверна»
  var mb=document.getElementById('mine');
  if(myMarker){mb.onclick=function(){
    if(cluster&&cluster.zoomToShowLayer){cluster.zoomToShowLayer(myMarker,function(){myMarker.openPopup();});}
    else{map.flyTo(myLL,MAXZ-1,{duration:.8});setTimeout(function(){myMarker.openPopup();},850);}};}
  else{mb.style.display='none';}
  document.getElementById('loader').classList.add('hide');
}).catch(function(){document.getElementById('loader').textContent='Карта не загрузилась — обнови';});
</script></body></html>"""


async def _world_page(request: web.Request) -> web.Response:
    return web.Response(text=_WORLD_HTML, content_type="text/html")


# Названия 25 континентов по биому (порядок = снег ×5 → зелень ×14 → пустыни ×6).
CONTINENT_NAMES = worldmap.CONTINENT_NAMES   # единый источник имён (см. bot/game/worldmap.py)
_WORLD_CONT: list[dict] | None = None


def _world_continents() -> list[dict]:
    """25 континентов (центр/биом/имя) — единый источник из worldmap."""
    return worldmap.continents() or [{"i": 0, "x": 0.5, "y": 0.5, "biome": "", "name": "Недоливск"}]


async def _world_slots(request: web.Request) -> web.Response:
    """Континенты с именами/биомом — для подписей на карте."""
    return web.json_response(_world_continents(), headers={"Cache-Control": "public, max-age=3600"})


async def _world_taverns(request: web.Request) -> web.Response:
    """Таверны на мире-атласе с ПОЛНОЙ инфой (имя/владелец/уровень/репутация/вместимость/
    уют/пристройки/континент). Позиция ВЫЧИСЛЯЕТСЯ на лету (игрок→континент pid%25, внутри —
    слот спиралью-подсолнухом) — без миграции БД и правки игровых регионов. + активный рейд."""
    import math
    try:
        uid = int(request.query.get("uid", "0"))
    except ValueError:
        uid = 0
    conts = _world_continents()
    nc = len(conts)
    async with session_factory() as s:
        rows = await repo.get_map_taverns(s)
        boss = await repo.get_active_raid(s)
    # Позиция СТАБИЛЬНА (не зависит от явки соседей — раньше спираль шла по индексу
    # сортировки и таверны «прыгали» при появлении нового игрока на континенте). Берём
    # её прямо из ХЭША id игрока, полярно и равномерно по площади диска вокруг центра
    # континента — без наложений (непрерывно, а не по сетке слотов).
    R = 0.095
    crown_of = _rating_leaders(_rating_entries(rows)[0])   # короны лидеров (👑/⭐/🏰)
    out = []
    for tav, pl in rows:
        c = worldmap.continent_for(pl.region, pl.id) or conts[pl.id % nc]  # континент ЗОНЫ игрока
        h1 = (pl.id * 2654435761) & 0xFFFFFFFF
        h2 = (pl.id * 40503 + 0x9E3779B1) & 0xFFFFFFFF
        a = (h1 / 4294967296.0) * 6.2831853                  # угол
        rr = R * math.sqrt(h2 / 4294967296.0)                # радиус (равномерно по площади)
        x = min(0.997, max(0.003, c["x"] + rr * math.cos(a)))
        y = min(0.997, max(0.003, c["y"] + rr * math.sin(a)))
        out.append({
            # income/доход НЕ отдаём: mine определяется по ?uid (подделываемому на публичном
            # /world), иначе утекал бы чужой доход. Прочие поля — публичные игровые статы.
            "x": round(x, 4), "y": round(y, 4),
            "name": tav.name or "Таверна", "owner": pl.first_name or "Кабатчик",
            "level": tav.level, "tier": worldmap.sprite_tier(tav.level),
            "rep": tav.reputation, "cap": tav.capacity, "comfort": tav.comfort,
            "builds": len(tav.buildings or []), "continent": c["name"],
            "mine": bool(uid) and pl.id == uid,
            "crowns": crown_of.get(pl.id, []),   # титулы лидера (gdp/rep/level)
        })
    raid = None
    if boss is not None and boss.status in ("gathering", "active"):
        from bot.game import raid as rd
        spec = rd.BOSSES.get(boss.boss_key)
        if spec is not None:
            raid = {"name": spec.name, "emoji": spec.emoji, "status": boss.status}
    return web.json_response({"taverns": out, "raid": raid, "total": len(out)},
                             headers={"Cache-Control": "no-store"})


async def _world_tile(request: web.Request) -> web.Response:
    """Тайл пирамиды мира {z}/{x}/{y}.webp (статика из world_tiles, сгенерён в Docker).
    Расширение запроса игнорируем — всегда отдаём .webp (плавный переход со старого .jpg-кэша)."""
    try:
        z = int(request.match_info["z"]); x = int(request.match_info["x"]); y = int(request.match_info["y"])
    except (ValueError, KeyError):
        return web.Response(status=404)
    p = WORLD_TILES / str(z) / str(x) / f"{y}.webp"
    if not p.is_file():
        return web.Response(status=404)
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=604800"})



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
  .snd{position:fixed;left:10px;top:calc(8px + env(safe-area-inset-top,0px));z-index:13;
    width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-size:17px;cursor:pointer;background:#241809cc;border:1px solid #6b522e;color:#ffe2a8;
    user-select:none;-webkit-user-select:none;box-shadow:0 2px 8px #0008}
  .snd:active{transform:scale(.94)}
  .vig{position:fixed;inset:0;pointer-events:none;z-index:5;
    background:radial-gradient(ellipse 78% 78% at 50% 50%, transparent 58%, #060a12 100%)}
  .ev{position:fixed;left:50%;top:calc(12px + env(safe-area-inset-top,0px));
    transform:translateX(-50%);z-index:10;display:none;
    background:#2a160af2;border:1px solid #c9803a;border-radius:22px;padding:8px 18px;
    font-size:13px;color:#ffe2a8;font-weight:700;letter-spacing:.2px;
    box-shadow:0 4px 18px #000b;white-space:nowrap;backdrop-filter:blur(3px)}
  .reg{position:fixed;left:50%;bottom:calc(172px + env(safe-area-inset-bottom,0px));
    transform:translateX(-50%);z-index:11;display:none;
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
  .reg .x{position:absolute;right:11px;top:7px;font-size:20px;color:#a98c5c;cursor:pointer;line-height:1}
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
<div class="reg" id="millPanel" style="display:none">
  <span class="x" id="millx">×</span>
  <div class="rt" id="millTitle">🌀 Мельница</div>
  <div class="rs" id="millSub"></div>
  <button class="rb" id="millBtn">🛒 Снарядить телегу</button>
</div>
<div class="bar" id="bar">🗺 Недоливск · загрузка…</div>
<div class="hint">тащи · щипок/колесо — зум · тап по кружку — раскрыть</div>
<audio id="bgm" loop preload="auto" src="/assets/audio/festival.mp3"></audio>
<div class="snd" id="snd">🔊</div>
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
// фоновая музыка ярмарки — луп, с памятью вкл/выкл. Мобильные блокируют автоплей
// до жеста — поэтому стартуем и сразу, и при первом касании; кнопка 🔊/🔇 глушит.
(function(){
  const bgm = document.getElementById('bgm'), btn = document.getElementById('snd');
  if (!bgm || !btn) return;
  bgm.volume = 0.42;
  let muted = false; try { muted = localStorage.getItem('map_mute') === '1'; } catch(e){}
  const paint = () => { btn.textContent = muted ? '🔇' : '🔊'; };
  // Браузеры блокируют автоплей со звуком до жеста (Android — строго, iOS мягче).
  // Снимаем жест-слушатели ТОЛЬКО когда play() реально запустился; иначе пробуем
  // на КАЖДЫЙ следующий жест (а не сдаёмся после первого) — capture, чтобы поймать
  // событие раньше карты.
  const EVS = ['pointerdown','touchend','click','keydown'];
  const arm = on => EVS.forEach(e => on
    ? document.addEventListener(e, onGesture, {capture:true})
    : document.removeEventListener(e, onGesture, {capture:true}));
  function play(){
    if (muted) return;
    const p = bgm.play();
    if (p && p.then) p.then(() => arm(false)).catch(() => {});  // не вышло — ждём след. жест
  }
  function onGesture(){ play(); }
  paint(); play(); arm(true);                        // пробуем сразу (iOS) + ловим жест (Android)
  btn.addEventListener('click', (e) => { e.stopPropagation(); muted = !muted;
    try { localStorage.setItem('map_mute', muted ? '1' : '0'); } catch(_){}
    if (muted) bgm.pause(); else play();
    paint(); });
})();
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
  const critterLayer = new PIXI.Container(); app.stage.addChild(critterLayer);  // живность (под маркерами)
  const millRoute = new PIXI.Graphics(); app.stage.addChild(millRoute);  // дорога телеги к мельнице
  const farmLayer = new PIXI.Container(); app.stage.addChild(farmLayer);  // фермы-ориентиры
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

  // ---------- бродячая живность (амбиент): пасётся у поселений, тихо гуляет ----------
  // Размер ПРОПОРЦИОНАЛЕН зданиям (масштаб по markerK, своя база на вид), чтобы не
  // были ни огромными, ни мелкими. Спрайт-лист 6×8, ряд 2 = боковой шаг (вправо),
  // флип по направлению. Привязаны к таверне (на суше), бродят в малом радиусе.
  (async () => {
    const SPECIES = [{n:'horse',h:30},{n:'foal',h:24},{n:'goat',h:21},{n:'goatling',h:15},
                     {n:'goose',h:17},{n:'gosling',h:11},{n:'rabbit',h:15},{n:'rabbit_cub',h:10}];
    const avail = [];
    for (const s of SPECIES){
      try {
        const tex = await PIXI.Assets.load('/assets/animals/'+s.n+'.png');
        const fw = tex.width/6, fh = tex.height/8, fr = [];     // сетка 6×8, кадр квадратный
        for (let c=0;c<6;c++)
          fr.push(new PIXI.Texture({source:tex.source, frame:new PIXI.Rectangle(c*fw, 2*fh, fw, fh)}));
        s.frames = fr; s.fh = fh; avail.push(s);
      } catch(e){}
    }
    if (!avail.length || !taverns.length) return;
    const critters = [];
    const N = Math.min(90, Math.max(24, Math.round(taverns.length*1.8)));
    for (let i=0;i<N;i++){
      const home = taverns[(Math.random()*taverns.length)|0];
      const sp = avail[(Math.random()*avail.length)|0];
      const an = new PIXI.AnimatedSprite(sp.frames);
      an.anchor.set(0.5,0.9); an.animationSpeed = 0.12; an.play();
      critterLayer.addChild(an);
      const hx = home.wx + (Math.random()-0.5)*70, hy = home.wy + (Math.random()-0.5)*70;
      critters.push({an, sp, hx, hy, wx:hx, wy:hy, tx:hx, ty:hy, dir:1, idle:Math.random()*4, moving:false});
    }
    const newTarget = c => { const r = 24+Math.random()*46, a = Math.random()*6.283;
      c.tx = c.hx + Math.cos(a)*r; c.ty = c.hy + Math.sin(a)*r; };
    let last = performance.now();
    app.ticker.add(() => {
      const now = performance.now(), dt = Math.min(0.05,(now-last)/1000); last = now;
      const show = world.scale.x > LABEL_MIN, k = markerK();   // на сильном отдалении прячем
      for (const c of critters){
        c.an.visible = show; if (!show) continue;
        if (c.moving){
          const dx=c.tx-c.wx, dy=c.ty-c.wy, d=Math.hypot(dx,dy);
          if (d < 1.5){ c.moving=false; c.idle = 1+Math.random()*4; c.an.gotoAndStop(0); }
          else { const v=14*dt; c.wx += dx/d*v; c.wy += dy/d*v; c.dir = dx>=0?1:-1;
                 if (!c.an.playing) c.an.play(); }
        } else if ((c.idle -= dt) <= 0){ newTarget(c); c.moving = true; c.an.play(); }
        const s = screenOf(c.wx,c.wy); c.an.x=s.x; c.an.y=s.y;
        const sc = (c.sp.h/c.sp.fh)*k; c.an.scale.set(sc); c.an.scale.x = sc*c.dir;  // флип
      }
    });
  })();

  let gatherMillPos = null;            // {wx,wy} мельницы-вылазки (ставит ферма-блок ниже)
  // ---------- ферма-сценка (мельница + мельник + поле + забор) на пустой суше ----------
  // Точку ищем в центральной полосе (точно суша) с МАКС. зазором до ближайшей таверны
  // → в «пустоте», а не впритык к поселениям. Вся сценка — один контейнер в пиксельных
  // координатах мельницы (origin = низ мельницы), сортировка по Y для глубины.
  (async () => {
    const load = async n => { try { return await PIXI.Assets.load('/assets/farm/'+n+'.png'); }
                              catch(e){ return null; } };
    const strip = (t, n) => { const fw=t.width/n, fr=[]; for (let i=0;i<n;i++)
      fr.push(new PIXI.Texture({source:t.source, frame:new PIXI.Rectangle(i*fw,0,fw,t.height)})); return fr; };
    const millTex = await load('mill');
    if (!millTex) return;
    const FH = millTex.height;                          // опорная высота (мельница)
    const sowTex = await load('miller_sowing'), cartTex = await load('cart'), fenceTex = await load('fence1');
    const bedTex = [await load('bed1'), await load('bed2'), await load('bed3')].filter(Boolean);
    const cropTex = [];
    for (const c of [['rye1','rye2'],['cabbage1','cabbage2'],['pumpkin1','pumpkin2'],
                     ['tomato1','tomato2'],['carrot1','carrot2']]){
      const a = await load(c[0]), b = await load(c[1]); if (a&&b) cropTex.push([a,b]);
    }
    const spr = (t, x, y, z) => { const s=new PIXI.Sprite(t); s.anchor.set(0.5,1); s.position.set(x,y); s.zIndex=z; return s; };
    const anim = (fr, x, y, z, sp) => { const a=new PIXI.AnimatedSprite(fr); a.anchor.set(0.5,1);
      a.position.set(x,y); a.zIndex=z; a.animationSpeed=sp; a.play(); return a; };
    function buildFarm(){
      const c = new PIXI.Container(); c.sortableChildren = true;
      c.addChild(anim(strip(millTex,3), 0, 0, 0, 0.06));               // мельница (лопасти крутятся)
      if (cartTex) c.addChild(spr(cartTex, -120, 4, 4));              // телега слева
      let ci = 0;                                                      // поле грядок справа
      for (let row=0; row<2; row++) for (let col=0; col<3; col++){
        const bx = 120 + col*36, by = 18 - row*14;
        if (bedTex.length) c.addChild(spr(bedTex[(row*3+col)%bedTex.length], bx, by, by));
        if (cropTex.length){ c.addChild(anim(cropTex[ci%cropTex.length], bx, by, by+0.2, 0.03)); ci++; }
      }
      if (fenceTex) for (let x=108; x<=216; x+=30) c.addChild(spr(fenceTex, x, 28, 28));  // забор спереди
      if (sowTex) c.addChild(anim(strip(sowTex,6), 98, 24, 24, 0.14)); // мельник сеет у поля
      farmLayer.addChild(c);
      return c;
    }
    const cand = [];
    for (let gx=0.22; gx<=0.78; gx+=0.07)
      for (let gy=0.26; gy<=0.74; gy+=0.07) cand.push({x:gx, y:gy, gap:1e9});
    for (const cc of cand)
      for (const t of taverns){ const d=Math.hypot(cc.x-t.x, cc.y-t.y); if (d<cc.gap) cc.gap=d; }
    cand.sort((a,b)=>b.gap-a.gap);
    const spots = [], want = 2;
    for (const cc of cand){
      if (cc.gap < 0.11) break;
      if (spots.every(o=>Math.hypot(o.x-cc.x,o.y-cc.y) > 0.22)) spots.push(cc);
      if (spots.length>=want) break;
    }
    if (!spots.length) spots.push({x:0.5, y:0.5});
    const farms = spots.map(s => ({node: buildFarm(), wx:s.x*W, wy:s.y*H}));
    if (farms.length){                                  // первая мельница — кликабельная вылазка
      gatherMillPos = {wx: farms[0].wx, wy: farms[0].wy};
      farms[0].node.eventMode = 'static'; farms[0].node.cursor = 'pointer';
      farms[0].node.on('pointertap', e => { e.stopPropagation(); openMillPanel(); });
    }
    const BASE_H = 64;
    app.ticker.add(() => {
      const k = markerK();
      for (const f of farms){ const sc = screenOf(f.wx, f.wy);
        f.node.x=sc.x; f.node.y=sc.y; f.node.scale.set((BASE_H/FH)*k); }
    });
  })();

  // ---------- вылазка «телега за зерном»: панель + телега на карте ----------
  let millState = data.mill || null;          // состояние вылазки зрителя
  let millFetchT = performance.now()/1000;     // когда получили millState (для живого отсчёта)
  let millHold = 0;                            // не перерисовывать панель (показываем итог сбора)
  const millPanel = document.getElementById('millPanel');
  const millSub = document.getElementById('millSub'), millBtn = document.getElementById('millBtn');
  const mineTav = () => taverns.find(t => t.mine);
  const millLive = () => performance.now()/1000 - millFetchT;
  function setMill(st){ millState = st || null; millFetchT = performance.now()/1000; renderMillPanel(); }
  function fmtT(s){ s=Math.max(0,Math.round(s)); const h=Math.floor(s/3600), m=Math.floor((s%3600)/60);
    return h>0 ? (h+'ч '+String(m).padStart(2,'0')+'м') : (m+':'+String(s%60).padStart(2,'0')); }
  function renderMillPanel(){
    if (millPanel.style.display==='none' || performance.now()<millHold) return;
    const st = millState || {state:'idle'};
    if (st.state==='transit'){
      const back = (st.trip_secs||1800) - (st.elapsed_secs + millLive());
      millSub.textContent = '🛒 Телега в пути · вернётся через ' + fmtT(back);
      millBtn.style.display = 'none';
      if (back <= 0) pollMill();                         // доехала — обновим до «забрать»
    } else if (st.state==='ready'){
      millSub.textContent = '🌾 Телега вернулась — забирай зерно!';
      millBtn.style.display=''; millBtn.disabled=false;
      millBtn.textContent='🌾 Забрать зерно'; millBtn.dataset.act='collect';
    } else if (st.state==='cooldown'){
      millSub.textContent = '😴 Мельница отдыхает · телега снова через ' + fmtT((st.ready_in||0) - millLive());
      millBtn.style.display = 'none';
    } else {
      millSub.textContent = 'Снаряди телегу — привезёт зерно с мельницы (~30 мин в пути).';
      millBtn.style.display=''; millBtn.disabled=false;
      millBtn.textContent='🛒 Снарядить телегу'; millBtn.dataset.act='run';
    }
  }
  async function pollMill(){
    try { const d = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json();
      setMill(d.mill); } catch(_){}
  }
  function openMillPanel(){
    millPanel.style.display='block'; millHold=0;
    if (!mineTav()){ millSub.textContent='Сначала заведи кабак в боте (/start).';
      millBtn.style.display='none'; return; }
    renderMillPanel(); pollMill();
  }
  document.getElementById('millx').onclick = () => { millPanel.style.display='none'; };
  millBtn.onclick = async () => {
    const act = millBtn.dataset.act;
    millBtn.disabled=true; const was=millBtn.textContent; millBtn.textContent='…';
    try {
      const r = await fetch(act==='collect' ? '/api/mill/collect' : '/api/mill/run',
        {method:'POST', headers:{'Content-Type':'application/json'},
         body:JSON.stringify({initData:(tg&&tg.initData)||''})});
      const d = await r.json();
      if (d.ok){
        if (act==='collect'){
          const note = d.note==='rich' ? ' · богатый помол!' : (d.note==='mishap' ? ' · тряхнуло, часть просыпал' : '');
          millSub.textContent = '🌾 +' + d.grain + ' зерна' + note;
          millBtn.style.display='none'; millHold = performance.now()+3500;   // подержать итог
          try{ tg&&tg.HapticFeedback&&tg.HapticFeedback.notificationOccurred('success'); }catch(e){}
        } else {
          try{ tg&&tg.HapticFeedback&&tg.HapticFeedback.impactOccurred('medium'); }catch(e){}
        }
        setMill(d.mill);
      } else {
        millBtn.disabled=false; millBtn.textContent=was;
        millSub.textContent = ({auth:'Открой карту через бота', no_tavern:'Сначала заведи кабак (/start)',
          busy:'Телега ещё в деле / мельница отдыхает', nothing:'Забирать нечего'}[d.error]) || 'Не вышло, ещё раз';
        if (d.mill) setMill(d.mill);
      }
    } catch(e){ millBtn.disabled=false; millBtn.textContent=was; millSub.textContent='Сеть подвела — ещё раз'; }
  };
  // движущаяся ПОВОЗКА (конь тянет телегу) на карте: таверна → мельница → таверна.
  // Конь — боковой шаг (анимация), телега прицеплена сзади; вся повозка флипается
  // по направлению (вправо/влево), конь идёт мордой вперёд.
  let millRig = null;
  (async () => {
    let hTex, cTex;
    try { hTex = await PIXI.Assets.load('/assets/animals/horse.png'); } catch(e){}
    try { cTex = await PIXI.Assets.load('/assets/farm/cart.png'); } catch(e){}
    if (!hTex) return;
    const HFW = hTex.width/6, HFH = hTex.height/8, hf = [];     // 6×8, ряд 2 = боковой шаг
    for (let c=0;c<6;c++)
      hf.push(new PIXI.Texture({source:hTex.source, frame:new PIXI.Rectangle(c*HFW, 2*HFH, HFW, HFH)}));
    const node = new PIXI.Container(); node.visible = false;
    if (cTex){ const cart = new PIXI.Sprite(cTex); cart.anchor.set(0.5,1);   // телега СЗАДИ коня
      cart.position.set(-26, -4); node.addChild(cart); }                    // дышло под коня
    const horse = new PIXI.AnimatedSprite(hf); horse.anchor.set(0.5,0.72);   // якорь по НОГАМ коня
    horse.animationSpeed = 0.18; horse.play(); node.addChild(horse);
    farmLayer.addChild(node);
    millRig = {node, HFH};
  })();
  app.ticker.add(() => {
    if (millPanel.style.display!=='none') renderMillPanel();
    millRoute.clear();
    if (!millRig) return;
    const mt = mineTav();
    if (millState && millState.state==='transit' && gatherMillPos && mt){
      const p = Math.max(0, Math.min(1, (millState.elapsed_secs + millLive())/(millState.trip_secs||1800)));
      const q = p<0.5 ? p*2 : (1-p)*2;                  // 0→1→0 (туда и обратно)
      const a = screenOf(mt.wx, mt.wy), b = screenOf(gatherMillPos.wx, gatherMillPos.wy);
      const k = markerK();
      // ЯРКАЯ ДОРОГА таверна→мельница: тёмная окантовка + светлый пунктир поверх
      const dx=b.x-a.x, dy=b.y-a.y, len=Math.hypot(dx,dy)||1, ux=dx/len, uy=dy/len;
      millRoute.moveTo(a.x,a.y).lineTo(b.x,b.y)
        .stroke({color:0x3a2410, width:Math.max(5,8*k), alpha:0.5, cap:'round'});  // казёнка
      const dash=16*k, gap=10*k;
      for (let d=0; d<len; d+=dash+gap){ const e=Math.min(len,d+dash);
        millRoute.moveTo(a.x+ux*d, a.y+uy*d).lineTo(a.x+ux*e, a.y+uy*e); }
      millRoute.stroke({color:0xffd98a, width:Math.max(3,4.5*k), alpha:0.95, cap:'round'});  // пунктир
      // повозка
      const wx = mt.wx + (gatherMillPos.wx-mt.wx)*q, wy = mt.wy + (gatherMillPos.wy-mt.wy)*q;
      const s = screenOf(wx,wy);
      const sc = (46/millRig.HFH)*k;                    // размер повозки на экране
      const dir = (gatherMillPos.wx>=mt.wx ? 1 : -1) * (p<0.5 ? 1 : -1);
      millRig.node.visible=true; millRig.node.x=s.x; millRig.node.y=s.y;
      millRig.node.scale.set(sc); millRig.node.scale.x = sc*dir;
    } else millRig.node.visible=false;
  });

  // ---------- ивент-объекты (анимированные, самостоятельные) ----------
  const RL = {tank:['🛡','Авангард'], archer:['⚔️','Рубаки'],
              scout:['🔭','Разведка'], ratnik:['🗡','Ратники']};
  let liveInv = null, reportEv = null;      // живой ивент / сводка боя
  let invAddTroop = null;                    // добавить свою дружину на карту live
  let invSyncTroops = null;                  // пересобрать дружины под финальный состав
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
  if (liveInv || reportEv){            // во время ивента подсказка-жесты мешает банеру фазы (сверху)
    const h = document.querySelector('.hint'); if (h) h.style.display = 'none';
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
    // ── Сфера HP/ГОТОВНОСТИ ДРУЖИНЫ (HUD, экранная, правый-нижний угол) ─────────
    // Жидкость в стеклянной сфере (арт fant_UI). На сборе — наливается «готовность
    // к победе» (рубеж VL); в бою — живое HP дружины, тает с гибелью бойцов.
    // squadOn() — ПРОВЕРЯЕТСЯ КАЖДЫЙ КАДР: ev.army_hp_max доливается опросом, когда
    // кто-то записывается ПОСЛЕ открытия карты (иначе у раннего зрителя сфера мертва).
    const VL = 0.7;            // зеркалит invasion.VICTORY_LINE
    const squadOn = () => (ev.army_hp_max||0) > 0;
    const readyCol = f => f>=VL ? 0x3fa34d : (f>=VL*0.6 ? 0xe0a020 : 0xc0392b);
    const hpCol    = f => f>0.5 ? 0x3fa34d : (f>0.25 ? 0xe0a020 : 0xc0392b);
    let gTex=null; try{ gTex=await PIXI.Assets.load('/assets/hud/squad_globe.png'); }catch(e){}
    const GIW=226, GIH=219, GCX=112.5, GCY=100.5, GR=96;   // геометрия PNG: круг жидкости
    const hud = new PIXI.Container(); hud.visible=false; app.stage.addChild(hud);
    const gShadow = new PIXI.Graphics().ellipse(GCX, GCY+8, GR+8, GR+5).fill({color:0x000000, alpha:0.32});
    hud.addChild(gShadow);                                               // мягкая тень-подложка
    if (gTex){ const gSpr = new PIXI.Sprite(gTex); hud.addChild(gSpr); }  // стекло/оправа
    const liquid = new PIXI.Graphics(); hud.addChild(liquid);            // жидкость — поверх (полупрозрачная)
    const lmask = new PIXI.Graphics().circle(GCX, GCY, GR-2).fill(0xffffff);
    hud.addChild(lmask); liquid.mask = lmask;                            // не даём жидкости вылезти за круг
    const gLabel = new PIXI.Text({text:'', style:{fontFamily:'Georgia,serif', fontSize:20,
      fontWeight:'700', fill:0xffe9c2, stroke:{color:0x140d06, width:5}, align:'center'}});
    gLabel.anchor.set(0.5, 0.5); gLabel.position.set(GCX, GCY); hud.addChild(gLabel);   // число по центру орба
    function placeHud(){
      const disp = Math.min(138, app.screen.width*0.30), s = disp/GIW;
      hud.scale.set(s);
      hud.x = app.screen.width - GIW*s - 16;                            // правый-нижний угол
      hud.y = app.screen.height - GIH*s - 22;
    }
    placeHud(); window.addEventListener('resize', placeHud);
    function setGlobe(frac, color, label, notch){
      if (!squadOn()) return;
      hud.visible = true; frac = Math.max(0, Math.min(1, frac));
      const yTop = (GCY+GR) - frac*2*GR;
      liquid.clear();
      if (frac>0){ liquid.rect(0, yTop, GIW, (GCY+GR)-yTop).fill({color, alpha:0.6});   // тело
        liquid.rect(0, yTop, GIW, 5).fill({color:0xffffff, alpha:0.28}); }              // поверхность
      if (notch!=null){ const ny=(GCY+GR)-notch*2*GR;                                    // победный рубеж
        liquid.rect(0, ny-1, GIW, 2).fill({color:0xffe9a8, alpha:0.95}); }
      if (gLabel.text !== (label||'')) gLabel.text = label || '';   // не перерисовываем текст каждый кадр
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
    function rebuildUnits(troops){            // пересобрать под финальный состав (новые записи)
      for (const u of units) u.sp.destroy();
      units.length = 0;
      (troops||[]).forEach((t,i)=> units.push(makeUnit(t,i)));
    }
    invSyncTroops = (troops) => {             // вызывает опрос сбора при изменении числа
      if (troops && troops.length !== units.length) rebuildUnits(troops);
    };
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
    // G/M фиксированы; B (длина боя) может уточниться, когда опрос сбора подтянет
    // финальный состав → читаем её и TOTAL вживую, иначе ранний зритель крутил бы
    // бой по старому числу раундов.
    const G=ev.gather_secs, M=ev.march_secs, END=4;
    const B = () => (ev.battle_secs || 0), TOTAL = () => G+M+B()+END;
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
      if (t > TOTAL()){ if (ev.demo) { reset(); t = 0; } else t = TOTAL(); }
      const k = markerK();
      pathLayer.clear();
      const bs = screenOf(bx, by);
      evEl.style.display = 'block';                  // баннер фазы (внизу); на живом сборе скроем
      buffTxt.visible = false;                       // баффы орды — только в бою
      if (t < G){                                   // СБОР: войска СТОЯТ у таверн + пунктир к орде
        evEl.style.display = ev.demo ? 'block' : 'none';   // на сборе отсчёт показывает плашка регистрации
        evEl.textContent = '⚔ Сбор войск · выход через '+Math.ceil(G-t)+'с · таверн: '+units.length;
        setAnim('idle');
        if (squadOn()){                                 // 🪓 орда (бар) vs 🛡 сфера готовности
          hp.visible=true; drawHp(1);
          const rf = ev.ready!=null ? ev.ready : 0;
          const tag = rf>=VL ? 'ГОТОВЫ' : Math.min(99, Math.round(rf/VL*100))+'%';
          setGlobe(rf, readyCol(rf), '🛡 '+tag, VL);
        } else { hp.visible=false; }
        for (const u of units){ u.wx=u.ox; u.wy=u.oy; u.sp.visible=true;
          u.dir=(bx>=u.ox)?1:-1; uAnim(u,'idle');
          const us=screenOf(u.ox,u.oy); drawDotted(us.x,us.y, bs.x,bs.y, t/G); }
      } else if (t < G+M){                            // МАРШ: герои идут по пунктиру
        const p=(t-G)/M;
        evEl.textContent = '⚔ Войска идут к орде!'; setAnim('idle');
        if (squadOn()){ hp.visible=true; drawHp(1); setGlobe(1, hpCol(1), '🛡 100%'); }
        else { hp.visible=false; }
        for (const u of units){
          const lp = Math.max(0, Math.min(1, (p-u.delay)/(1-u.delay)));
          u.wx = u.ox + (bx-u.ox)*lp; u.wy = u.oy + (by-u.oy)*lp;
          u.sp.visible = lp>0; u.dir = (bx>=u.ox)?1:-1; uAnim(u,'walk');
          const us=screenOf(u.ox,u.oy); drawDotted(us.x,us.y, bs.x,bs.y, 1);
        }
      } else if (t < G+M+B()){                        // БОЙ
        const bp=(t-(G+M))/B();
        evEl.textContent = '⚔ Битва · '+fmt(B()*(1-bp));
        hp.visible=true;
        let warded=false, bf='';
        if (ev.timeline && ev.timeline.length && ev.orc_hp_max){    // РЕАЛЬНАЯ динамика
          const tl=ev.timeline, idx=Math.min(tl.length-1, Math.max(0, Math.floor(bp*tl.length)));
          const st=tl[idx]; warded=!!st.ward;
          drawHp(st.hp/ev.orc_hp_max, warded);
          if (squadOn()){ const af = st.army!=null ? st.army/ev.army_hp_max : 1;
            setGlobe(af, hpCol(af), '🛡 '+Math.round(af*100)+'%'); }   // HP дружины тает по-настоящему
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
          if (squadOn()){ const last=ev.timeline&&ev.timeline.length?ev.timeline[ev.timeline.length-1]:null;
            const af=last&&ev.army_hp_max?(last.army||0)/ev.army_hp_max:1;
            setGlobe(af, hpCol(af), '🛡 '+Math.round(af*100)+'%'); }   // выжившие вернулись
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
          let lf=0.35, af=0;
          if (ev.timeline && ev.timeline.length && ev.orc_hp_max){
            const last = ev.timeline[ev.timeline.length-1];
            lf = last.hp / ev.orc_hp_max;                              // реальный остаток HP орды
            if (squadOn()) af = (last.army||0) / ev.army_hp_max;        // дружина выбита
          }
          hp.visible=true; drawHp(lf); setAnim('idle'); anim.tint=0xffffff;
          if (squadOn()){ setGlobe(af, hpCol(af), '🛡 '+Math.round(af*100)+'%'); }   // дружина выбита
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
    bar.style.display = '';                 // вернуть счётчик после закрытия сводки
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
    // опрос на сборе: чужие записи тоже наливают полоску готовности дружины
    const poll = setInterval(async () => {
      try {
        const d = await (await fetch('/api/taverns?uid='+encodeURIComponent(myId))).json();
        const e = (d.events||[]).find(x => x.gather_secs != null && !x.demo);
        if (e && e.status === 'gathering'){
          if (e.ready != null) ev.ready = e.ready;
          if (e.n != null) ev.n = e.n;
          // синхронизируем БОЕВЫЕ данные с финальным составом — иначе у того, кто
          // открыл карту раньше остальных, анимация/сфера считались бы по старому
          // ростеру (и могли разойтись с реальным итогом боя).
          if (e.army_hp_max != null) ev.army_hp_max = e.army_hp_max;
          if (e.orc_hp_max != null) ev.orc_hp_max = e.orc_hp_max;
          if (e.timeline) ev.timeline = e.timeline;
          if (e.result) ev.result = e.result;
          if (e.battle_secs != null) ev.battle_secs = e.battle_secs;
          if (invSyncTroops && e.troops) invSyncTroops(e.troops);
        } else { clearInterval(poll); }
      } catch(_){}
    }, 4000);
    const start = performance.now()/1000 - (ev.elapsed || 0);
    app.ticker.add(() => {
      const left = Math.max(0, (ev.gather_secs || 0) - (performance.now()/1000 - start));
      if (left <= 0){ reg.style.display = 'none'; return; }   // сбор окончен — плашка уходит
      const rf = ev.ready!=null ? ev.ready : 0;
      const tag = rf>=0.7 ? '✅ состав победный' : (rf>=0.42 ? '⚠️ почти — зовите ещё' : '🔴 войска мало');
      sub.textContent = '⏳ Выход через ' + Math.floor(left/60) + ':'
        + String(Math.floor(left % 60)).padStart(2, '0') + ' · таверн: ' + (ev.n || 0)
        + ' · ' + tag;
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
          if (d.ready != null) ev.ready = d.ready;          // полоска готовности доливается сразу
          if (d.n != null) ev.n = d.n;
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
