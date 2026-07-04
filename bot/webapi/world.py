"""Тайловый мир-атлас (/world) — интерактивная карта мира: таверны, континенты,
короны лидеров, Орда орков. Единственная карта проекта (старая PNG/PixiJS-карта
удалена; карта живёт только здесь и встраивается в мини-апп)."""

import pathlib

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import worldmap
from bot.webapi.rating import _rating_entries, _rating_leaders

# Пирамида тайлов мира (генерится в Docker из assets/world25.jpg тайлером worldgen/tiler.py).
WORLD_TILES = pathlib.Path(__file__).resolve().parent.parent.parent / "world_tiles"

_PARTY_MAX = 60   # потолок точек войск орды на карте (перф)


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
/* ── Орда орков на карте: анимированный орк (spritesheet 10 кадров) + войска ── */
.orc-ev{position:relative;width:100px;height:76px;pointer-events:auto;cursor:pointer}
.orc-ev .orc{width:100px;height:76px;background:url('/assets/boss/ork1_idle.png') 0 0/1000px 76px no-repeat;
  animation:orcIdle 1.1s steps(10) infinite;filter:drop-shadow(0 4px 7px rgba(0,0,0,.75));transform-origin:50% 100%}
@keyframes orcIdle{to{background-position:-1000px 0}}
.orc-ev.battle .orc{animation:orcIdle 1.1s steps(10) infinite,orcSh .5s ease-in-out infinite,orcHurt .48s ease-in-out infinite}
@keyframes orcSh{0%,100%{transform:translateX(0) rotate(0)}25%{transform:translateX(-3px) rotate(-2deg)}75%{transform:translateX(3px) rotate(2deg)}}
/* DEATH орка (защитники победили): лист _die 10 кадров one-shot → растворяется */
.orc-ev.dead .orc{background-image:url('/assets/boss/ork1_die.png');animation:orcIdle 1.1s steps(10) 1 forwards}
.orc-ev.dead .fx{display:none}
.orc-ev.dead .aura{opacity:.15}
.orc-ev.dead{animation:orcFade 1.8s ease-out 1.1s forwards}
@keyframes orcFade{to{opacity:0;transform:translateY(6px) scale(.9)}}
.orc-ev .aura{position:absolute;left:50%;top:55%;width:132px;height:132px;transform:translate(-50%,-50%);z-index:-1;
  border-radius:50%;background:radial-gradient(circle,rgba(120,200,70,.3),rgba(80,160,40,0) 68%);animation:orcAura 2.3s ease-in-out infinite}
.orc-ev.battle .aura{background:radial-gradient(circle,rgba(255,70,50,.42),rgba(220,30,20,0) 66%);animation-duration:.9s}
@keyframes orcAura{0%,100%{opacity:.5;transform:translate(-50%,-50%) scale(.92)}50%{opacity:.95;transform:translate(-50%,-50%) scale(1.16)}}
.orc-ev .hp{position:absolute;left:50%;top:-15px;transform:translateX(-50%);width:104px;height:10px;z-index:3;
  border-radius:6px;background:#2a0d0a;border:1px solid #5a1e14;overflow:hidden;box-shadow:0 1px 5px rgba(0,0,0,.6);opacity:0;transition:opacity .3s}
.orc-ev.battle .hp{opacity:1}
.orc-ev .hp i{display:block;height:100%;width:100%;border-radius:5px;transition:width .25s linear;background:linear-gradient(180deg,#ff5a3c,#c11e12)}
.orc-ev .lbl{position:absolute;left:50%;top:-34px;transform:translateX(-50%);white-space:nowrap;z-index:3;
  font:800 12px/1 var(--serif);color:#cdeba6;text-shadow:0 1px 3px #000,0 0 7px rgba(120,200,80,.6);letter-spacing:.3px}
.orc-ev.battle .lbl{color:#ffcf9a;text-shadow:0 1px 3px #000,0 0 8px rgba(255,90,50,.7)}
/* эффект удара по боссу (fire-стрип 7 кадров, только в бою; аддитивное свечение) */
.orc-ev .fx{display:none;position:absolute;left:50%;top:42%;width:78px;height:78px;transform:translate(-50%,-50%);
  z-index:2;pointer-events:none;background:url('/assets/fx/fire1.png') 0 0/546px 78px no-repeat;mix-blend-mode:screen}
.orc-ev.battle .fx{display:block;animation:fxHit .48s steps(7) infinite}
@keyframes fxHit{to{background-position-x:-546px}}
@keyframes orcHurt{0%,72%,100%{filter:drop-shadow(0 4px 7px rgba(0,0,0,.75))}80%{filter:drop-shadow(0 4px 7px rgba(0,0,0,.75)) brightness(2.4) sepia(1) hue-rotate(-35deg) saturate(4)}}
/* войска-соратники: марш к логову (близко — фигурки, далеко — нити) */
.orc-fig{width:44px;height:55px;pointer-events:none;transition:opacity .3s,transform .16s linear}
/* воин: spritesheet WALK 10 кадров (у всех 6 листов; масштаб листа → 440px даёт 44px/кадр) */
.orc-fig .hf{width:44px;height:55px;background-size:440px 55px;background-repeat:no-repeat;background-position:0 0;
  animation:heroWalk .9s steps(10) infinite;filter:drop-shadow(0 3px 3px rgba(0,0,0,.65))}
.orc-fig.h1 .hf{background-image:url('/assets/heroes/hero1_walk.png')}
.orc-fig.h2 .hf{background-image:url('/assets/heroes/hero2_walk.png')}
.orc-fig.h3 .hf{background-image:url('/assets/heroes/hero3_walk.png')}
.orc-fig.h4 .hf{background-image:url('/assets/heroes/hero4_walk.png')}
.orc-fig.h5 .hf{background-image:url('/assets/heroes/hero5_walk.png')}
.orc-fig.h6 .hf{background-image:url('/assets/heroes/hero6_walk.png')}
@keyframes heroWalk{to{background-position-x:-440px}}
/* ATTACK: настоящий взмах (лист _attack, 10 кадров, тот же steps/размер) */
.orc-fig.atk.h1 .hf{background-image:url('/assets/heroes/hero1_attack.png')}
.orc-fig.atk.h2 .hf{background-image:url('/assets/heroes/hero2_attack.png')}
.orc-fig.atk.h3 .hf{background-image:url('/assets/heroes/hero3_attack.png')}
.orc-fig.atk.h4 .hf{background-image:url('/assets/heroes/hero4_attack.png')}
.orc-fig.atk.h5 .hf{background-image:url('/assets/heroes/hero5_attack.png')}
.orc-fig.atk.h6 .hf{background-image:url('/assets/heroes/hero6_attack.png')}
.orc-fig.atk .hf{animation:heroWalk .6s steps(10) infinite}
/* DEATH: падение (лист _die, one-shot, замереть на последнем кадре) */
.orc-fig.dead.h1 .hf{background-image:url('/assets/heroes/hero1_die.png')}
.orc-fig.dead.h2 .hf{background-image:url('/assets/heroes/hero2_die.png')}
.orc-fig.dead.h3 .hf{background-image:url('/assets/heroes/hero3_die.png')}
.orc-fig.dead.h4 .hf{background-image:url('/assets/heroes/hero4_die.png')}
.orc-fig.dead.h5 .hf{background-image:url('/assets/heroes/hero5_die.png')}
.orc-fig.dead.h6 .hf{background-image:url('/assets/heroes/hero6_die.png')}
.orc-fig.dead .hf{animation:heroWalk .9s steps(10) 1 forwards}
.orc-fig.mine .hf{filter:drop-shadow(0 0 6px #ffd27a) drop-shadow(0 2px 2px #000)}
.orc-line{stroke:#9ad35a;stroke-width:1.6;fill:none;opacity:.45;stroke-dasharray:5 9;animation:march 1.1s linear infinite}
/* СВОЯ нить «таверна → босс» — яркая, толстая, со свечением, видна на ЛЮБОМ зуме */
.orc-line.mine{stroke:#ffe08a;stroke-width:3.4;opacity:1;stroke-dasharray:9 6;stroke-linecap:round;
  filter:drop-shadow(0 0 4px rgba(255,205,90,.95)) drop-shadow(0 0 8px rgba(255,180,50,.5));animation:march .9s linear infinite}
@keyframes march{to{stroke-dashoffset:-15}}
/* воины видны на ЛЮБОМ зуме; ЧУЖИЕ нити — только на обзоре (иначе каша), СВОЯ — всегда */
body:not(.far) .orc-line:not(.mine){opacity:0}
/* фокус рейда: не-участники таверн скрыты */
.tav-pin.raid-hidden{opacity:0;transition:opacity .4s;pointer-events:none}
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
  // старт НЕ на самом дальнем: +2 ступени, но не меньше порога подписей (видны
  // таверны и их названия); зум-аут до обзора (cz) остаётся доступен.
  if(!map._c){var iz=Math.min(MAXZ,Math.max(cz+2,3.8));map.setView(px(W/2,H/2),iz,{animate:false});map._c=true;}
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
    if(o.raidHidden){el.style.opacity=0;return;}      // фокус рейда: чужая таверна скрыта
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
    tavMarkers.push({m:m,mine:!!t.mine,prio:t.mine?1e9:(crowned?5e8:0)+(t.level*1000+(t.rep||0)),
      key:(t.x||0).toFixed(4)+','+(t.y||0).toFixed(4)});   // ключ позиции — для фокуса рейда
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
  if(typeof applyRaidFocus==='function')applyRaidFocus();   // таверны загрузились — сразу спрятать чужих, если орда идёт
  document.getElementById('loader').classList.add('hide');
}).catch(function(){document.getElementById('loader').textContent='Карта не загрузилась — обнови';});

// ── Орда орков на карте: анимированный орк + ПЛАВНЫЙ марш войск + автобой ──
var invLayer=L.layerGroup().addTo(map),invTroops=L.layerGroup().addTo(map);
var invM=null,invKey='',invData=null,invBaseEl=0,invAtMs=0;
var troopMarks=[],troopMeta=[],troopKey='';
var invPh='',invResultKey='';   // текущая фаза (для тапа по орку) + дедуп авто-модалки итогов
// Итоги боя: просим родителя (React) открыть модалку с полной сводкой. Авто — один
// раз на нашествие (флаг в localStorage переживает перезаход карты); тап по орку —
// принудительно (manual), в обход дедупа.
function askResult(won,manual){
  try{parent.postMessage({t:'nedo-orda-result',won:!!won,manual:!!manual},location.origin);}catch(e){}
  if(parent===window){location.href='/app/?startapp=orda_result';}}
function maybeAutoResult(e,ph){
  if(ph!=='won'&&ph!=='lost')return;
  var rk='orda-res-'+(e.id||0);
  if(invResultKey===rk)return;invResultKey=rk;         // уже поставили таймер в этой сессии
  var seen=false;try{seen=localStorage.getItem(rk)==='1';}catch(_){}
  if(seen)return;                                       // уже показывали (перезаход) — не спамим
  try{localStorage.setItem(rk,'1');}catch(_){}
  setTimeout(function(){askResult(ph==='won',false);},1800);}   // дать добить/пасть → всплывает сводка
function fmtT(s){s=Math.max(0,s|0);var m=(s/60)|0,ss=s%60;return m+':'+(ss<10?'0':'')+ss;}
function invElapsed(){return invBaseEl+(Date.now()-invAtMs)/1000;}
function invPhase(e,el){
  if(e.status==='won')return'won';    // защитники победили → орк ГИБНЕТ
  if(e.status==='lost')return'lost';  // орда прорвалась → воины ГИБНУТ
  var g=e.gather_secs,mr=e.march_secs,b=e.battle_secs;
  if(el<g)return'gather';if(el<g+mr)return'march';if(el<g+mr+b)return'battle';
  return (e.orc_hp_left<=0)?'won':'lost';}   // бой отыгран → ИСХОД сразу по HP (не ждём флип статуса нотифаера)
// Пересоздаём фигурки ТОЛЬКО при смене состава (иначе марш дёргался — каждый тик
// маркеры уничтожались/создавались заново). Дальше их плавно ДВИГАЕМ (setLatLng + CSS-transition).
function rebuildTroops(e){invTroops.clearLayers();troopMarks=[];troopMeta=[];var lair=px(e.x*W,e.y*H);
  (e.troops||[]).forEach(function(t,i){
    L.polyline([px(t.x*W,t.y*H),lair],{className:'orc-line'+(t.mine?' mine':''),interactive:false}).addTo(invTroops);
    var hv='h'+((i%6)+1);
    var m=L.marker(px(t.x*W,t.y*H),{icon:L.divIcon({className:'orc-fig '+hv+(t.mine?' mine':''),
      iconSize:[44,55],iconAnchor:[22,50],html:'<div class="hf"></div>'}),
      interactive:false,keyboard:false,zIndexOffset:2100}).addTo(invTroops);   // ВЫШЕ босса — не прячутся за тушей
    troopMarks.push(m);
    // орбита ВОКРУГ босса (кольцо с глубиной): угол по золотому сечению + радиус
    // СНАРУЖИ туши (иначе прятались за 100px орком)
    troopMeta.push({tx:t.x,ty:t.y,orbAng:i*2.399963,orbR:0.026+((i*37)%5)*0.003});});}
function moveTroops(e,ph,el){
  var bx=e.x,by=e.y,tt=Date.now()/1000,bEnd=e.gather_secs+e.march_secs+e.battle_secs;
  var march=ph==='gather'?0:(ph==='march'?Math.min(1,(el-e.gather_secs)/Math.max(1,e.march_secs)):1);
  // отступление по СЕРВЕРНОМУ времени (el), а не клиентскому таймеру — иначе при
  // перезаходе в карту путь домой проигрывался заново. Дошли (retreat>=1) → исчезают.
  var retreat=ph==='won'?Math.min(1,Math.max(0,el-bEnd)/6):0;
  var home=ph==='won'&&retreat>=1;
  for(var i=0;i<troopMarks.length;i++){var mt=troopMeta[i],fx,fy,atk=false,dead=false;
    var rx=bx+Math.cos(mt.orbAng)*mt.orbR,ry=by+Math.sin(mt.orbAng)*mt.orbR;   // точка на кольце
    if(ph==='gather'||ph==='march'){fx=mt.tx+(rx-mt.tx)*march;fy=mt.ty+(ry-mt.ty)*march;}   // марш к кольцу
    else if(ph==='battle'){var a=mt.orbAng+tt*1.3;                              // ХОДЯТ вокруг (быстрее) + бьют
      fx=bx+Math.cos(a)*mt.orbR;fy=by+Math.sin(a)*mt.orbR;atk=true;}
    else if(ph==='won'){fx=rx+(mt.tx-rx)*retreat;fy=ry+(mt.ty-ry)*retreat;}     // ПОБЕДА → домой (walk)
    else{fx=rx;fy=ry;dead=true;}                                                // ПРОРЫВ → падают у босса
    troopMarks[i].setLatLng(px(fx*W,fy*H));
    var g=troopMarks[i].getElement();
    if(g){g.classList.toggle('atk',atk);g.classList.toggle('dead',dead);
      g.style.transition='opacity .5s';g.style.opacity=home?'0':'';}}}   // дошли до таверн → исчезли (и при перезаходе сразу 0)
function renderInv(){
  if(!invData){invLayer.clearLayers();invTroops.clearLayers();invM=null;invKey='';troopKey='';troopMarks=[];return;}
  var e=invData,el=invElapsed(),ph=invPhase(e,el),lair=px(e.x*W,e.y*H);
  invPh=ph;maybeAutoResult(e,ph);   // тап по орку знает фазу + авто-модалка итогов (раз на бой)
  var tk=e.name+'|'+((e.troops||[]).length);
  if(tk!==troopKey){rebuildTroops(e);troopKey=tk;}
  var key=e.name+'|'+(ph==='battle'?'b':(ph==='won'?'w':(ph==='lost'?'l':'p')));
  if(key!==invKey){invLayer.clearLayers();
    var icon=L.divIcon({className:'orc-ev'+(ph==='battle'?' battle':''),iconSize:[100,76],iconAnchor:[50,76],
      html:'<div class="aura"></div><div class="fx"></div><div class="lbl"></div><div class="hp"><i></i></div><div class="orc"></div>'});
    invM=L.marker(lair,{icon:icon,zIndexOffset:2000}).addTo(invLayer);
    invM.on('click',function(){   // не релоадим приложение — просим родителя открыть панель поверх карты
      if(invPh==='won'||invPh==='lost'){askResult(invPh==='won',true);return;}   // бой кончился → сводка итогов
      try{parent.postMessage({t:'nedo-orda'},location.origin);}catch(e){}
      if(parent===window){location.href='/app/?startapp=orda';}});
    invKey=key;}
  var el2=invM.getElement();
  if(el2){el2.classList.toggle('battle',ph==='battle');
    el2.classList.toggle('dead',ph==='won');   // орк гибнет при победе защитников
    // смерть отыграна давно (перезаход) → орк уже исчез, не переигрываем анимацию
    var bEnd=e.gather_secs+e.march_secs+e.battle_secs;
    el2.style.opacity=(ph==='won'&&el-bEnd>3)?'0':'';
    var fill=el2.querySelector('.hp i');
    if(fill){var hp=100;
      if(ph==='battle'){var bp=Math.min(1,(el-e.gather_secs-e.march_secs)/Math.max(1,e.battle_secs));
        var endp=e.orc_hp_max?100*e.orc_hp_left/e.orc_hp_max:0;hp=Math.max(endp,100-(100-endp)*bp);}
      else if(ph==='won')hp=0;
      else if(ph==='lost')hp=e.orc_hp_max?Math.max(6,100*e.orc_hp_left/e.orc_hp_max):50;
      fill.style.width=hp+'%';}
    var lb=el2.querySelector('.lbl');
    if(lb){if(ph==='gather')lb.textContent='🪓 СБОР · '+fmtT(e.gather_secs-el)+' ('+(e.n||0)+')';
      else if(ph==='march')lb.textContent='🪓 ОРДА ИДЁТ!';
      else if(ph==='battle')lb.textContent='⚔️ БИТВА · '+fmtT(e.gather_secs+e.march_secs+e.battle_secs-el);
      else if(ph==='won')lb.textContent='🏆 ОРДА ПОВЕРЖЕНА!';
      else if(ph==='lost')lb.textContent='💀 ОРДА ПРОРВАЛАСЬ…';
      else lb.textContent='…';}}
  moveTroops(e,ph,el);}
// Фокус рейда: на время орды показываем ТОЛЬКО таверны участников (+ свою), чужие
// прячем (по совпадению позиции войска с маркером таверны). Нет орды — все видны.
function applyRaidFocus(){
  var focus=invData&&(invData.troops||[]).length>0,set={};
  if(focus)(invData.troops||[]).forEach(function(t){set[(t.x||0).toFixed(4)+','+(t.y||0).toFixed(4)]=1;});
  tavMarkers.forEach(function(o){var hidden=focus&&!o.mine&&!set[o.key];o.raidHidden=hidden;
    var ic=o.m.getElement&&o.m.getElement();if(ic)ic.classList.toggle('raid-hidden',hidden);});
  queueRelayout();}
function pollInv(){fetch('/world/invasion.json?uid='+uid).then(function(r){return r.json();})
  .then(function(d){invData=d.inv;invBaseEl=invData?(invData.elapsed||0):0;invAtMs=Date.now();renderInv();applyRaidFocus();}).catch(function(){});}
pollInv();setInterval(pollInv,5000);setInterval(renderInv,120);   // рефетч 5с + плавный марш ~8fps (CSS-transition сглаживает)
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


async def _world_invasion(request: web.Request) -> web.Response:
    """Лёгкий поллинг Орды орков для карты: позиция логова, фаза/тайминги (elapsed),
    войска (позиции таверн записавшихся), HP. Read-only, переиспользует _invasion_event
    (та же детерминированная симуляция → анимация синхронна серверу)."""
    try:
        uid = int(request.query.get("uid", "0"))
    except ValueError:
        uid = 0
    # ВРЕМЕННО: орда на карте открыта ТОЛЬКО админу (обкатка фичи). Гейт по ?uid —
    # мягкий (для скрытия сырого, не безопасность): обычный игрок орка не увидит.
    from bot.config import settings
    if uid != settings.admin_id:
        return web.json_response({"inv": None}, headers={"Cache-Control": "no-store"})
    from bot.webapi.invasion import _invasion_event
    conts = _world_continents()
    nc = len(conts)
    ev = None
    async with session_factory() as s:
        inv = await repo.get_active_invasion(s)
        if inv is None:
            inv = await repo.latest_invasion(s)      # мог только что зарезолвиться
        show = False
        if inv is not None:
            if inv.status in ("gathering", "battle"):
                show = True
            elif inv.status in ("won", "lost") and inv.resolve_at:   # окно смерти ~14с
                from datetime import datetime, timezone
                _ra = inv.resolve_at if inv.resolve_at.tzinfo else inv.resolve_at.replace(tzinfo=timezone.utc)
                show = (datetime.now(timezone.utc) - _ra).total_seconds() < 14
        if show:
            e = _invasion_event(inv, uid)
            tl = e.get("timeline") or []
            ohl = int(tl[-1].get("hp", 0)) if tl and isinstance(tl[-1], dict) else 0
            # Позиции войск — по ТОЙ ЖЕ формуле, что таверны-маркеры (_atlas_pos),
            # из id записавшихся → воин встаёт РОВНО у своей таверны (иначе марш шёл
            # мимо, и не совпасть с маркером для «скрыть чужие»). Болванки (отриц. id,
            # не в таблице) — их стоящая позиция из записи.
            reg = list((inv.registered or {}).items())[:_PARTY_MAX]
            real_ids = [int(p) for p, _ in reg if int(p) > 0]
            pos = {}
            if real_ids:
                from sqlalchemy import select as _sel
                from bot.db.models import Player as _P
                for pid, region in (await s.execute(
                        _sel(_P.id, _P.region).where(_P.id.in_(real_ids)))).all():
                    x, y = _atlas_pos(pid, region, conts, nc)
                    pos[pid] = (round(x, 4), round(y, 4))
            troops = []
            for pid_s, rec in reg:
                pid = int(pid_s)
                tx, ty = pos.get(pid) or (round(float(rec.get("tx", 0.5)), 4),
                                          round(float(rec.get("ty", 0.5)), 4))
                troops.append({"x": tx, "y": ty, "mine": bool(uid) and pid == uid})
            ev = {   # только нужное карте (без тяжёлого timeline целиком)
                "id": inv.id,   # ключ дедупа авто-модалки итогов (одна на нашествие)
                "x": e["x"], "y": e["y"], "sprite": e.get("sprite", 1),
                "name": e["name"], "status": e["status"], "n": e.get("n", 0),
                "me": bool(uid) and str(uid) in (inv.registered or {}),
                "gather_secs": e.get("gather_secs", 0), "march_secs": e.get("march_secs", 0),
                "battle_secs": e.get("battle_secs", 0), "elapsed": e.get("elapsed", 0),
                "orc_hp_max": e.get("orc_hp_max", 1), "orc_hp_left": ohl, "troops": troops,
            }
    return web.json_response({"inv": ev}, headers={"Cache-Control": "no-store"})


def _atlas_pos(pl_id: int, region: str, conts: list, nc: int) -> tuple[float, float]:
    """Позиция таверны на атласе (норм. x/y) — ТА ЖЕ формула, что в _world_taverns
    (хеш-спираль вокруг центра континента). Единый источник, чтобы войска рейда
    вставали ровно у своих таверн-маркеров."""
    import math
    c = worldmap.continent_for(region, pl_id) or conts[pl_id % nc]
    h1 = (pl_id * 2654435761) & 0xFFFFFFFF
    h2 = (pl_id * 40503 + 0x9E3779B1) & 0xFFFFFFFF
    a = (h1 / 4294967296.0) * 6.2831853
    rr = 0.095 * math.sqrt(h2 / 4294967296.0)
    return (min(0.997, max(0.003, c["x"] + rr * math.cos(a))),
            min(0.997, max(0.003, c["y"] + rr * math.sin(a))))


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
