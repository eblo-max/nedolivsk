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
@keyframes rb{0%,100%{box-shadow:0 4px 16px rgba(210,58,24,.45)}50%{box-shadow:0 4px 26px rgba(255,90,50,.8)}}
/* ── РЕЙД-БОСС на карте: живой маркер (крупный эмодзи + аура по фазе + HP-полоса) ── */
.raid-ev{position:relative;width:96px;height:92px;pointer-events:auto;cursor:pointer}
.raid-ev .rboss{position:absolute;left:50%;bottom:0;transform:translateX(-50%);font-size:58px;line-height:1;
  filter:drop-shadow(0 6px 10px rgba(0,0,0,.7));animation:rbossFloat 2.4s ease-in-out infinite}
@keyframes rbossFloat{0%,100%{transform:translateX(-50%) translateY(0) rotate(-2deg)}50%{transform:translateX(-50%) translateY(-5px) rotate(2deg)}}
.raid-ev .raura{position:absolute;left:50%;bottom:2px;width:120px;height:120px;transform:translate(-50%,0);z-index:-1;border-radius:50%;
  background:radial-gradient(circle,rgba(255,120,50,.5),rgba(200,40,20,0) 66%);animation:orcAura 1.6s ease-in-out infinite}
.raid-ev.ph2 .raura{background:radial-gradient(circle,rgba(255,70,40,.6),rgba(210,25,15,0) 64%);animation-duration:1.1s}
.raid-ev.ph3 .raura{background:radial-gradient(circle,rgba(255,40,60,.7),rgba(190,10,30,0) 62%);animation-duration:.7s}
.raid-ev.ph3 .rboss{animation:rbossRage .45s ease-in-out infinite}
@keyframes rbossRage{0%,100%{transform:translateX(-50%) translate(0,0)}25%{transform:translateX(-50%) translate(-3px,-2px)}75%{transform:translateX(-50%) translate(3px,-1px)}}
.raid-ev.dead .rboss{animation:orcFade 1.6s ease-out forwards}
.raid-ev .rhp{position:absolute;left:50%;top:-16px;transform:translateX(-50%);width:100px;height:9px;z-index:3;
  border-radius:5px;background:#2a0d0a;border:1px solid #6a2016;overflow:hidden;box-shadow:0 1px 5px rgba(0,0,0,.6)}
.raid-ev .rhp i{display:block;height:100%;width:100%;border-radius:4px;transition:width .4s ease;background:linear-gradient(180deg,#ff6a3c,#c11e12)}
.raid-ev.ph3 .rhp i{background:linear-gradient(180deg,#ff3a6a,#b0102e)}
.raid-ev .rlbl{position:absolute;left:50%;top:-34px;transform:translateX(-50%);white-space:nowrap;z-index:3;
  font:800 12px/1 var(--serif);color:#ffcf9a;text-shadow:0 1px 3px #000,0 0 8px rgba(255,90,50,.7)}
.raid-ev .rsub{position:absolute;left:50%;top:-46px;transform:translateX(-50%);white-space:nowrap;z-index:3;
  font:700 10.5px/1 var(--serif);color:#e9c98a;text-shadow:0 1px 3px #000}
/* телеграф заклинаний босса (иконки) — переиспользует telPop от Орды */
.raid-ev .rtel{position:absolute;left:50%;top:-60px;transform:translateX(-50%);white-space:nowrap;z-index:4;
  font-size:16px;line-height:1;letter-spacing:2px;filter:drop-shadow(0 1px 3px #000);opacity:0;transition:opacity .25s;pointer-events:none}
.raid-ev .rtel.on{opacity:1}
.raid-ev .rtel.pop{animation:telPop .5s cubic-bezier(.2,.8,.3,1)}
/* числа урона/лечения по боссу — переиспользуют dmgUp */
.raid-ev .rdmgc{position:absolute;left:50%;top:34%;transform:translateX(-50%);width:0;height:0;z-index:6;pointer-events:none}
.raid-ev .rdn{position:absolute;top:0;transform:translateX(-50%);white-space:nowrap;font:900 17px/1 var(--serif);
  color:#ffe08a;text-shadow:0 0 9px rgba(255,150,40,.6),0 2px 4px #000;animation:dmgUp 1.1s ease-out forwards}
.raid-ev .rdn.big{font-size:24px;color:#fff6c0;text-shadow:0 0 15px rgba(255,190,70,1),0 2px 5px #000}
.raid-ev .rdn.heal{color:#8fe05a;text-shadow:0 0 9px rgba(120,220,80,.65),0 2px 4px #000}
/* ударная волна добивания — переиспользует boom */
.raid-ev .rboom{position:absolute;left:50%;top:40%;width:44px;height:44px;transform:translate(-50%,-50%) scale(.2);
  border-radius:50%;border:4px solid rgba(255,224,150,.95);opacity:0;pointer-events:none;z-index:4;
  box-shadow:0 0 26px rgba(255,180,90,.9),inset 0 0 20px rgba(255,120,60,.7)}
.raid-ev.dead .rboom{animation:boom .7s cubic-bezier(.15,.7,.3,1) forwards}
/* нижний CTA-баннер рейда (ультрасовременный, как у Орды) */
#raidbar{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(env(safe-area-inset-bottom,0px) + 74px);z-index:1000;
  width:max-content;max-width:calc(100vw - 24px);display:none;align-items:center;gap:11px;padding:10px 12px 10px 16px;
  border-radius:18px;cursor:pointer;font-family:var(--serif);font-weight:700;font-size:14px;color:#ffe0cf;letter-spacing:.2px;
  background:linear-gradient(180deg,rgba(150,42,24,.96),rgba(84,20,12,.96));border:1px solid rgba(255,120,70,.5);
  box-shadow:0 12px 34px rgba(0,0,0,.55),0 0 22px rgba(230,70,30,.34);animation:rb 1.9s ease-in-out infinite}
#raidbar>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#raidbar .go{flex:none;padding:6px 13px;border-radius:999px;font-size:12.5px;font-weight:800;white-space:nowrap;
  background:linear-gradient(180deg,#ff9a5a,#e0562a);color:#2a0f04;box-shadow:0 2px 7px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.35)}
@media (prefers-reduced-motion:reduce){#raidbar{animation:none}.raid-ev .rboss,.raid-ev .raura{animation:none}}
/* баннер Орды: призыв «встать в строй» на сборе. СНИЗУ по центру, приподнят НАД
   зум-контролами (чтобы не налезал ни на шапку сверху, ни на зум справа-снизу).
   Ультрасовременная плавающая плашка: глубокий градиент, тёплое свечение, пилюля-CTA. */
#ordaBar{position:fixed;left:50%;transform:translateX(-50%);
  bottom:calc(env(safe-area-inset-bottom,0px) + 74px);z-index:1001;width:max-content;max-width:calc(100vw - 24px);
  display:none;align-items:center;gap:11px;padding:10px 12px 10px 16px;border-radius:18px;cursor:pointer;
  font-family:var(--serif);font-weight:700;font-size:14px;color:#fbe6d2;letter-spacing:.2px;
  background:linear-gradient(180deg,rgba(64,28,13,.96),rgba(36,15,7,.96));
  border:1px solid rgba(255,150,70,.42);
  box-shadow:0 12px 34px rgba(0,0,0,.55),0 0 22px rgba(210,90,30,.32),inset 0 1px 0 rgba(255,220,170,.14);
  animation:ordaGlow 2.2s ease-in-out infinite}
@keyframes ordaGlow{0%,100%{box-shadow:0 12px 34px rgba(0,0,0,.55),0 0 16px rgba(210,90,30,.28),inset 0 1px 0 rgba(255,220,170,.14)}
  50%{box-shadow:0 12px 34px rgba(0,0,0,.55),0 0 32px rgba(255,120,50,.6),inset 0 1px 0 rgba(255,220,170,.2)}}
#ordaBar>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#ordaBar .go{flex:none;padding:6px 13px;border-radius:999px;font-size:12.5px;font-weight:800;white-space:nowrap;
  background:linear-gradient(180deg,#ffd684,#e0972f);color:#3a1c05;box-shadow:0 2px 7px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.4)}
#ordaBar.reg{border-color:rgba(126,209,79,.5);color:#e2f0cc;animation:none;
  background:linear-gradient(180deg,rgba(34,64,22,.96),rgba(20,44,14,.96))}
#ordaBar.reg .go{background:linear-gradient(180deg,#c3ec9a,#6fae3f);color:#123008}
#ordaBar.info{cursor:default;animation:none;background:linear-gradient(180deg,rgba(56,26,14,.94),rgba(34,15,7,.94))}
#ordaBar.info .go{background:rgba(255,255,255,.12);color:#f0d8b0;box-shadow:none}
@media (prefers-reduced-motion:reduce){#ordaBar{animation:none}}
/* нижний HUD боя: ДВЕ подписанные полосы HP (орда/дружина), в бою вместо баннера-призыва */
#battleHud{position:fixed;left:10px;right:10px;bottom:calc(env(safe-area-inset-bottom,0px) + 88px);z-index:1001;
  display:none;max-width:520px;margin:0 auto;padding:10px 13px 11px;border-radius:16px;font-family:var(--serif);
  background:linear-gradient(180deg,rgba(30,19,11,.95),rgba(16,10,6,.96));border:1px solid rgba(122,80,42,.55);
  box-shadow:0 12px 34px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,220,170,.12)}
.bh-title{text-align:center;font-weight:800;font-size:12.5px;color:#ffcf9a;letter-spacing:.3px;margin-bottom:8px;
  text-shadow:0 1px 3px #000,0 0 8px rgba(255,90,50,.5)}
.bh-row{display:flex;align-items:center;gap:9px;margin:5px 0}
.bh-lbl{flex:none;width:108px;font-weight:700;font-size:12px;color:#e9dcc2;white-space:nowrap}
.bh-bar{flex:1;height:11px;border-radius:6px;overflow:hidden;border:1px solid rgba(0,0,0,.5);background:#241109}
.bh-bar.ally{background:#0c1608}
.bh-bar i{display:block;height:100%;transition:width .3s ease}
.bh-bar .orcf{background:linear-gradient(180deg,#ff5a3c,#c11e12)}
.bh-bar .allyf{background:linear-gradient(180deg,#8fe05a,#3f9a24)}
.bh-pct{flex:none;width:36px;text-align:right;font-weight:800;font-size:11.5px;color:#bfa775}
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
/* ударная волна на добивании (только победа) */
.orc-ev .boom{position:absolute;left:50%;top:48%;width:44px;height:44px;transform:translate(-50%,-50%) scale(.2);
  border-radius:50%;border:4px solid rgba(255,224,150,.95);opacity:0;pointer-events:none;z-index:4;
  box-shadow:0 0 26px rgba(255,180,90,.9),inset 0 0 20px rgba(255,120,60,.7)}
.orc-ev.dead .boom{animation:boom .7s cubic-bezier(.15,.7,.3,1) forwards}
@keyframes boom{0%{opacity:0;transform:translate(-50%,-50%) scale(.2)}14%{opacity:1}100%{opacity:0;transform:translate(-50%,-50%) scale(3.6)}}
/* лёгкая тряска карты на исходе боя (transform-only → композитор, дёшево) */
#map.shake{animation:mapShake .44s cubic-bezier(.36,.07,.19,.97)}
@keyframes mapShake{10%{transform:translate(-2px,1px)}25%{transform:translate(3px,-2px)}40%{transform:translate(-4px,2px)}
  55%{transform:translate(3px,-1px)}70%{transform:translate(-2px,2px)}85%{transform:translate(2px,-1px)}100%{transform:none}}
@media (prefers-reduced-motion:reduce){#map.shake{animation:none}.orc-ev.dead .boom{animation:none}}
.orc-ev .aura{position:absolute;left:50%;top:55%;width:132px;height:132px;transform:translate(-50%,-50%);z-index:-1;
  border-radius:50%;background:radial-gradient(circle,rgba(120,200,70,.3),rgba(80,160,40,0) 68%);animation:orcAura 2.3s ease-in-out infinite}
.orc-ev.battle .aura{background:radial-gradient(circle,rgba(255,70,50,.42),rgba(220,30,20,0) 66%);animation-duration:.9s}
@keyframes orcAura{0%,100%{opacity:.5;transform:translate(-50%,-50%) scale(.92)}50%{opacity:.95;transform:translate(-50%,-50%) scale(1.16)}}
/* ДВЕ полосы стопкой НАД орком (не на нём): орда (красная) сверху, дружина (зелёная)
   под ней — сразу видно, кто кого пересиливает */
.orc-ev .hp{position:absolute;left:50%;top:-30px;transform:translateX(-50%);width:104px;height:8px;z-index:3;
  border-radius:5px;background:#2a0d0a;border:1px solid #5a1e14;overflow:hidden;box-shadow:0 1px 5px rgba(0,0,0,.6);opacity:0;transition:opacity .3s}
.orc-ev.battle .hp,.orc-ev.dead .hp{opacity:1}
.orc-ev .hp i{display:block;height:100%;width:100%;border-radius:4px;transition:width .25s linear;background:linear-gradient(180deg,#ff5a3c,#c11e12)}
.orc-ev .ally{position:absolute;left:50%;top:-19px;transform:translateX(-50%);width:104px;height:8px;z-index:3;
  border-radius:5px;background:#0c1608;border:1px solid rgba(0,0,0,.55);overflow:hidden;opacity:0;transition:opacity .3s}
.orc-ev.battle .ally,.orc-ev.dead .ally{opacity:1}
.orc-ev .ally i{display:block;height:100%;width:100%;border-radius:4px;transition:width .25s linear;background:linear-gradient(180deg,#8fe05a,#3f9a24)}
/* телеграф способностей орка: иконки активных баффов + «pop» при активации */
.orc-ev .tel{position:absolute;left:50%;top:-60px;transform:translateX(-50%);white-space:nowrap;z-index:4;
  font-size:17px;line-height:1;letter-spacing:2px;filter:drop-shadow(0 1px 3px #000);opacity:0;transition:opacity .25s;pointer-events:none}
.orc-ev.battle .tel{opacity:1}
.orc-ev .tel.pop{animation:telPop .5s cubic-bezier(.2,.8,.3,1)}
@keyframes telPop{0%{transform:translateX(-50%) scale(.4);opacity:.2}42%{transform:translateX(-50%) scale(1.4);opacity:1}100%{transform:translateX(-50%) scale(1)}}
/* ── ЭПИЧНЫЕ баффы орка: слои-оверлеи (НЕ filter — его занимает orcHurt-анимация) ── */
.orc-ev .rage,.orc-ev .curse,.orc-ev .wolves,.orc-ev .shield{position:absolute;left:50%;top:46%;
  transform:translate(-50%,-50%);pointer-events:none;opacity:0;transition:opacity .3s;border-radius:50%}
.orc-ev .rage,.orc-ev .curse,.orc-ev .wolves{width:150px;height:150px;z-index:-1}
/* 🗣 ЯРОСТЬ — красный жар (пульс в такт удару) */
.orc-ev .rage{background:radial-gradient(circle,rgba(255,66,30,.55),rgba(200,20,10,0) 60%)}
.orc-ev.enr .rage{opacity:1;animation:auraP .5s ease-in-out infinite}
.orc-ev.enr .aura{background:radial-gradient(circle,rgba(255,60,40,.6),rgba(220,20,10,0) 62%)!important}
/* 💀 ПРОКЛЯТЬЕ — тёмно-фиолетовая дымка (медленное вращение) */
.orc-ev .curse{background:radial-gradient(circle,rgba(158,72,210,.5),rgba(90,20,140,0) 62%)}
.orc-ev.cursed .curse{opacity:1;animation:curseP 1.7s ease-in-out infinite}
/* 🐺 ЗОВ СТАИ — оранжевый рой миньонов */
.orc-ev .wolves{background:radial-gradient(circle,rgba(255,150,44,.5),rgba(200,90,10,0) 60%)}
.orc-ev.wolves-on .wolves{opacity:1;animation:auraP .8s ease-in-out infinite}
/* 🛡 СТЕНА ЩИТОВ — пульсирующее энергокольцо + синяя аура */
.orc-ev .shield{width:120px;height:120px;z-index:2;border:3px solid rgba(130,190,255,.9);
  box-shadow:0 0 22px rgba(90,150,255,.7),inset 0 0 22px rgba(120,180,255,.5)}
.orc-ev.warded .shield{opacity:1;animation:shieldP 1.2s ease-in-out infinite}
.orc-ev.warded .aura{background:radial-gradient(circle,rgba(120,180,255,.5),rgba(60,120,220,0) 66%)!important}
@keyframes auraP{0%,100%{transform:translate(-50%,-50%) scale(1);opacity:.5}50%{transform:translate(-50%,-50%) scale(1.18);opacity:.92}}
@keyframes curseP{0%,100%{transform:translate(-50%,-52%) scale(1) rotate(0);opacity:.38}50%{transform:translate(-50%,-48%) scale(1.12) rotate(8deg);opacity:.78}}
@keyframes shieldP{0%,100%{transform:translate(-50%,-50%) scale(.95);opacity:.75}50%{transform:translate(-50%,-50%) scale(1.07);opacity:1}}
@media (prefers-reduced-motion:reduce){.orc-ev .rage,.orc-ev .curse,.orc-ev .wolves,.orc-ev .shield{animation:none!important}}
/* всплывающие числа урона по ОРДЕ — чистые (без плашки), крупные, всплывают над орком */
.orc-ev .dmgc{position:absolute;left:50%;top:34%;transform:translateX(-50%);width:0;height:0;z-index:6;pointer-events:none}
.orc-ev .dn{position:absolute;top:0;transform:translateX(-50%);white-space:nowrap;
  font:900 18px/1 var(--serif);color:#ffe08a;text-shadow:0 0 9px rgba(255,150,40,.65),0 2px 4px #000;animation:dmgUp 1.1s ease-out forwards}
.orc-ev .dn.big{font-size:25px;color:#fff6c0;text-shadow:0 0 15px rgba(255,190,70,1),0 2px 5px #000}
@keyframes dmgUp{0%{opacity:0;transform:translateX(-50%) translateY(6px) scale(.6)}20%{opacity:1;transform:translateX(-50%) translateY(-2px) scale(1.15)}100%{opacity:0;transform:translateX(-50%) translateY(-44px) scale(1)}}
@media (prefers-reduced-motion:reduce){.orc-ev .dn{animation-duration:.5s}}
.orc-ev .lbl{position:absolute;left:50%;top:-46px;transform:translateX(-50%);white-space:nowrap;z-index:3;
  font:800 12px/1 var(--serif);color:#cdeba6;text-shadow:0 1px 3px #000,0 0 7px rgba(120,200,80,.6);letter-spacing:.3px}
.orc-ev.battle .lbl{color:#ffcf9a;text-shadow:0 1px 3px #000,0 0 8px rgba(255,90,50,.7)}
/* эффект удара по боссу (fire-стрип 7 кадров, только в бою; аддитивное свечение) */
.orc-ev .fx{display:none;position:absolute;left:50%;top:42%;width:78px;height:78px;transform:translate(-50%,-50%);
  z-index:2;pointer-events:none;background:url('/assets/fx/fire1.png') 0 0/546px 78px no-repeat;mix-blend-mode:screen}
.orc-ev.battle .fx{display:block;animation:fxHit .48s steps(7) infinite}
@keyframes fxHit{to{background-position-x:-546px}}
@keyframes orcHurt{0%,72%,100%{filter:drop-shadow(0 4px 7px rgba(0,0,0,.75))}80%{filter:drop-shadow(0 4px 7px rgba(0,0,0,.75)) brightness(2.4) sepia(1) hue-rotate(-35deg) saturate(4)}}
/* войска-соратники: марш к логову (близко — фигурки, далеко — нити) */
.orc-fig{width:44px;height:55px;pointer-events:none;transition:opacity .4s}
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
<div id="ordaBar"></div>
<div id="battleHud"></div>
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
  // рейд-босс теперь ЖИВОЙ маркер на карте + нижний CTA (см. pollRaid/renderRaid ниже),
  // а не статичный верхний баннер из taverns.json.
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
var troopMarks=[],troopMeta=[],troopInvId=null;
var invPh='',invResultKey='',invBmask=0,invFrameIdx=-1;   // фаза + дедуп модалки + маска баффов + индекс кадра боя (для чисел урона)
// Всплывающее число урона по орде: чистое (без плашки), крупный удар — ярче/больше.
// Чётко над орком, лёгкое чередование сторон (детерминированно, без «каши» из random).
var _dmgSide=0;
function floatDmg(el2,val){var c=el2&&el2.querySelector('.dmgc');if(!c||val<=0)return;
  var s=document.createElement('span');
  s.className='dn'+(val>=45?' big':'');s.textContent='−'+val;
  s.style.left=((_dmgSide++%2)?18:-18)+'px';   // чуть влево/вправо по очереди — не стопкой
  c.appendChild(s);setTimeout(function(){if(s.parentNode)s.parentNode.removeChild(s);},1100);}
// Итоги боя: просим родителя (React) открыть модалку с полной сводкой. Авто — один
// раз на нашествие (флаг в localStorage переживает перезаход карты); тап по орку —
// принудительно (manual), в обход дедупа.
function askResult(won,manual){
  try{parent.postMessage({t:'nedo-orda-result',won:!!won,manual:!!manual},location.origin);}catch(e){}
  if(parent===window){location.href='/app/?startapp=orda_result';}}
// Кульминация боя: тряска карты (ударная волна на орке — из CSS .dead .boom) + просьба
// родителю дать сильный гаптик. Один раз на нашествие (вызывается из once-гейта ниже).
function climax(won){
  var m=document.getElementById('map');
  if(m){m.classList.remove('shake');void m.offsetWidth;m.classList.add('shake');
    setTimeout(function(){m.classList.remove('shake');},480);}
  try{parent.postMessage({t:'nedo-orda-fx',won:!!won},location.origin);}catch(_){}}
function maybeAutoResult(e,ph){
  if(ph!=='won'&&ph!=='lost')return;
  var rk='orda-res-'+(e.id||0);
  if(invResultKey===rk)return;invResultKey=rk;         // уже поставили таймер в этой сессии
  var seen=false;try{seen=localStorage.getItem(rk)==='1';}catch(_){}
  if(seen)return;                                       // уже показывали (перезаход) — не спамим
  try{localStorage.setItem(rk,'1');}catch(_){}
  climax(ph==='won');                                   // удар/тряска/гаптик В МОМЕНТ исхода
  setTimeout(function(){askResult(ph==='won',false);},1800);}   // дать добить/пасть → всплывает сводка
function fmtT(s){s=Math.max(0,s|0);var m=(s/60)|0,ss=s%60;return m+':'+(ss<10?'0':'')+ss;}
function invElapsed(){return invBaseEl+(Date.now()-invAtMs)/1000;}
function invPhase(e,el){
  if(e.status==='won')return'won';    // защитники победили → орк ГИБНЕТ
  if(e.status==='lost')return'lost';  // орда прорвалась → воины ГИБНУТ
  var g=e.gather_secs,mr=e.march_secs,b=e.battle_secs;
  if(el<g)return'gather';if(el<g+mr)return'march';if(el<g+mr+b)return'battle';
  return (e.orc_hp_left<=0)?'won':'lost';}   // бой отыгран → ИСХОД сразу по HP (не ждём флип статуса нотифаера)
// Одна фигурка + её линия к логову. Орбита ВОКРУГ босса (кольцо с глубиной):
// угол по золотому сечению, радиус СНАРУЖИ туши (иначе прятались за 100px орком).
function addTroop(t,i,e){var lair=px(e.x*W,e.y*H);
  L.polyline([px(t.x*W,t.y*H),lair],{className:'orc-line'+(t.mine?' mine':''),interactive:false}).addTo(invTroops);
  var hv='h'+((i%6)+1);
  var m=L.marker(px(t.x*W,t.y*H),{icon:L.divIcon({className:'orc-fig '+hv+(t.mine?' mine':''),
    iconSize:[44,55],iconAnchor:[22,50],html:'<div class="hf"></div>'}),
    interactive:false,keyboard:false,zIndexOffset:2100}).addTo(invTroops);   // ВЫШЕ босса — не прячутся за тушей
  troopMarks.push(m);
  troopMeta.push({tx:t.x,ty:t.y,orbAng:i*2.399963,orbR:0.026+((i*37)%5)*0.003});}
// ИНКРЕМЕНТАЛЬНО: при входе нового бойца дорисовываем ТОЛЬКО его, а не пересобираем
// всех — иначе весь строй мигал (DOM пересоздавался, анимация ходьбы рестартовала).
// Полный пересбор — лишь на новое нашествие или если состав вдруг ужался.
function syncTroops(e){var list=e.troops||[];
  if(troopInvId!==e.id||list.length<troopMarks.length){
    invTroops.clearLayers();troopMarks=[];troopMeta=[];troopInvId=e.id;}
  for(var i=troopMarks.length;i<list.length;i++)addTroop(list[i],i,e);}
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
      g.style.opacity=home?'0':'';}}}   // дошли до таверн → плавно исчезли (fade из CSS .orc-fig)
// Верхний баннер-призыв: на сборе — заметное «встать в строй» (не искать орка на карте);
// в марше/бою — статус. Итог (won/lost) не дублируем — им занимается авто-модалка + чип в React.
function ordaBarUpdate(e,ph,el){
  var ob=document.getElementById('ordaBar');if(!ob)return;
  ob.classList.remove('reg','info');
  if(ph==='gather'){
    var t=fmtT(e.gather_secs-el),n=e.n||0;
    if(e.me){ob.classList.add('reg');
      ob.innerHTML='✅ <span>Ты в строю · '+t+' · дружина '+n+'</span><span class="go">Состав</span>';}
    else ob.innerHTML='🪓 <span>Орда идёт · '+t+' · '+n+' в строю</span><span class="go">В строй</span>';
    ob.onclick=function(){try{parent.postMessage({t:'nedo-orda'},location.origin);}catch(_){}
      if(parent===window)location.href='/app/?startapp=orda';};
    ob.style.display='flex';
  }else if(ph==='march'){
    ob.classList.add('info');ob.onclick=null;
    ob.innerHTML='🪓 <span>Орда наступает на Недоливск…</span><span class="go">Смотрим</span>';
    ob.style.display='flex';
  }else ob.style.display='none';   // бой/итог — призыв прячем, снизу работает HUD полосок HP
}
// Нижний HUD боя: две ПОДПИСАННЫЕ полосы HP (орда/дружина) вместо тесных полосок над орком.
function battleHudUpdate(ph,orcPct,allyPct){
  var bh=document.getElementById('battleHud');if(!bh)return;
  if(ph!=='battle'&&ph!=='won'&&ph!=='lost'){bh.style.display='none';return;}
  if(!bh.getAttribute('data-built')){bh.setAttribute('data-built','1');
    bh.innerHTML='<div class="bh-title">⚔️ Битва за Недоливск</div>'
      +'<div class="bh-row"><span class="bh-lbl">🪓 Орда орков</span><span class="bh-bar"><i class="orcf"></i></span><span class="bh-pct bh-op"></span></div>'
      +'<div class="bh-row"><span class="bh-lbl">🛡 Наша дружина</span><span class="bh-bar ally"><i class="allyf"></i></span><span class="bh-pct bh-ap"></span></div>';}
  bh.querySelector('.orcf').style.width=orcPct+'%';bh.querySelector('.allyf').style.width=allyPct+'%';
  bh.querySelector('.bh-op').textContent=Math.round(orcPct)+'%';bh.querySelector('.bh-ap').textContent=Math.round(allyPct)+'%';
  bh.style.display='block';
}
function renderInv(){
  if(!invData){invLayer.clearLayers();invTroops.clearLayers();invM=null;invKey='';troopInvId=null;troopMarks=[];troopMeta=[];
    var _ob=document.getElementById('ordaBar');if(_ob)_ob.style.display='none';
    var _bh=document.getElementById('battleHud');if(_bh)_bh.style.display='none';return;}
  var e=invData,el=invElapsed(),ph=invPhase(e,el),lair=px(e.x*W,e.y*H);
  invPh=ph;maybeAutoResult(e,ph);   // тап по орку знает фазу + авто-модалка итогов (раз на бой)
  syncTroops(e);                    // дорисовать новоприбывших без пересбора всех (без мигания)
  ordaBarUpdate(e,ph,el);           // баннер-призыв «встать в строй» / статус боя
  var key=e.name+'|'+(ph==='battle'?'b':(ph==='won'?'w':(ph==='lost'?'l':'p')));
  if(key!==invKey){invLayer.clearLayers();
    var icon=L.divIcon({className:'orc-ev'+(ph==='battle'?' battle':''),iconSize:[100,76],iconAnchor:[50,76],
      html:'<div class="aura"></div><div class="rage"></div><div class="curse"></div><div class="wolves"></div><div class="fx"></div><div class="boom"></div><div class="shield"></div><div class="dmgc"></div><div class="tel"></div><div class="lbl"></div><div class="orc"></div>'});
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
    // кадр боя по elapsed (как HP) → точные HP/баффы синхронно с симуляцией;
    // в терминале берём ПОСЛЕДНИЙ кадр (реальные выжившие/добитый орк, не заглушка).
    var tl=e.tl||[],fr=null,fi=-1,bp=Math.min(1,(el-e.gather_secs-e.march_secs)/Math.max(1,e.battle_secs));
    if(tl.length){
      if(ph==='battle'){fi=Math.min(tl.length-1,Math.floor(bp*tl.length));fr=tl[fi];}
      else if(ph==='won'||ph==='lost')fr=tl[tl.length-1];}
    // всплывающее число урона по ОРДЕ при смене кадра боя (дельта HP орды за раунд)
    if(ph==='battle'&&fi>=0&&fi!==invFrameIdx){
      floatDmg(el2,(fi>0?tl[fi-1].h:(e.orc_hp_max||0))-fr.h);
      invFrameIdx=fi;
    }else if(ph!=='battle')invFrameIdx=-1;
    // HP орды и дружины СЧИТАЕМ здесь, а РИСУЕМ в нижнем подписанном HUD (над орком было
    // тесно/нечитаемо). Дружина — общий запас HP всех записавшихся войск.
    var orcHp;
    if(ph==='won')orcHp=0;
    else if(ph==='lost')orcHp=e.orc_hp_max?Math.max(6,100*e.orc_hp_left/e.orc_hp_max):50;
    else if(fr)orcHp=100*fr.h/(e.orc_hp_max||1);
    else{var endp=e.orc_hp_max?100*e.orc_hp_left/e.orc_hp_max:0;orcHp=Math.max(endp,100-(100-endp)*bp);}
    var allyHp;
    if(ph==='lost')allyHp=8;
    else if(fr)allyHp=100*fr.a/(e.army_hp_max||1);
    else allyHp=(ph==='won')?50:Math.max(28,100-42*bp);
    battleHudUpdate(ph,Math.max(0,Math.min(100,orcHp)),Math.max(0,Math.min(100,allyHp)),e.n||0);
    // ТЕЛЕГРАФ способностей орка (только в бою): компактные иконки (без крупного баннера)
    // + эпичные слои-оверлеи (щит/ярость/проклятье/волки) с «pop» при смене набора.
    var b=(ph==='battle'&&fr)?fr:{},w=b.w?1:0,c=b.c?1:0,en=b.e?1:0,dd=b.d?1:0;
    var mask=w|(c<<1)|(en<<2)|(dd<<3),tel=el2.querySelector('.tel');
    if(mask!==invBmask){invBmask=mask;
      if(tel){tel.textContent=(w?'🛡':'')+(c?'💀':'')+(en?'🗣':'')+(dd?'🐺':'');
        if(mask){tel.classList.remove('pop');void tel.offsetWidth;tel.classList.add('pop');}}}
    el2.classList.toggle('warded',!!w);el2.classList.toggle('cursed',!!c);   // слои-оверлеи баффов
    el2.classList.toggle('enr',!!en);el2.classList.toggle('wolves-on',!!dd);
    var lb=el2.querySelector('.lbl');
    if(lb){if(ph==='gather')lb.textContent='🪓 СБОР · '+fmtT(e.gather_secs-el)+' ('+(e.n||0)+')';
      else if(ph==='march')lb.textContent='🪓 ОРДА ИДЁТ!';
      else if(ph==='battle')lb.textContent='⚔️ БИТВА ЗА НЕДОЛИВСК';   // без таймера — бой не по часам
      else if(ph==='won')lb.textContent='🏆 ОРДА ПОВЕРЖЕНА!';
      else if(ph==='lost')lb.textContent='💀 ОРДА ПРОРВАЛАСЬ…';
      else lb.textContent='…';}}}
  // позиции войск НЕ здесь — их плавно гонит rAF-петля animTroops (~45fps), иначе марш рвался
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
// Тяжёлое (пересбор маркеров, HP-полоса, подписи, авто-модалка) — раз в 250мс.
// Позиции войск — отдельной rAF-петлёй с моментальным transform: раньше марш гнался
// на ~8fps (setInterval 120мс), а инлайновый transition:opacity убил CSS-сглаживание
// transform → на зумах ход был рваным. Теперь ~45fps без transition (нет и рывка при
// зуме от Leaflet). Троттлинг 22мс щадит слабый Android.
var _moveAt=0;
function animTroops(ts){
  if(invData&&troopMarks.length&&ts-_moveAt>=22){_moveAt=ts;
    var e=invData,el=invElapsed(),ph=invPhase(e,el);moveTroops(e,ph,el);}
  requestAnimationFrame(animTroops);}
pollInv();setInterval(pollInv,5000);setInterval(renderInv,250);   // рефетч 5с + тяжёлый рендер 4fps
requestAnimationFrame(animTroops);                               // плавный марш/орбита/отход ~45fps

// ── РЕЙД-БОСС на карте: живой маркер (эмодзи+аура по фазе+HP) + нижний CTA. Тап →
// просим родителя открыть бой (RaidSheet) поверх карты, без релоада приложения. ──
var raidLayer=L.layerGroup().addTo(map),raidM=null,raidData=null,raidKey='';
var raidPrevHp=-1,raidTel='',raidFxKey='',_rdmgSide=0;   // дельта HP для чисел + телеграф + дедуп FX
function openRaid(){try{parent.postMessage({t:'nedo-raid'},location.origin);}catch(e){}
  if(parent===window)location.href='/app/?startapp=raid';}
// всплывающее число по боссу: урон (жёлт) или лечение/реген (зелёный «+»)
function floatRaid(el,val,heal){var c=el&&el.querySelector('.rdmgc');if(!c||val<=0)return;
  var s=document.createElement('span');s.className='rdn'+(heal?' heal':'')+(!heal&&val>=200?' big':'');
  s.textContent=(heal?'+':'−')+val;s.style.left=((_rdmgSide++%2)?18:-18)+'px';
  c.appendChild(s);setTimeout(function(){if(s.parentNode)s.parentNode.removeChild(s);},1100);}
function renderRaid(){
  var r=raidData,rb=document.getElementById('raidbar');
  if(!r){raidLayer.clearLayers();raidM=null;raidKey='';raidPrevHp=-1;if(rb)rb.style.display='none';return;}
  var ph=r.phase||1,gath=r.status==='gathering',dead=r.status==='dead';
  var key=r.key+'|'+(dead?'d':(gath?'g':'p'+ph));
  if(key!==raidKey){raidLayer.clearLayers();
    var icon=L.divIcon({className:'raid-ev'+(dead?' dead':' ph'+ph),iconSize:[96,92],iconAnchor:[48,92],
      html:'<div class="raura"></div><div class="rboom"></div><div class="rdmgc"></div><div class="rtel"></div><div class="rsub"></div><div class="rlbl"></div><div class="rhp"><i></i></div><div class="rboss">'+r.emoji+'</div>'});
    raidM=L.marker(px(r.x*W,r.y*H),{icon:icon,zIndexOffset:1900}).addTo(raidLayer);
    raidM.on('click',openRaid);raidKey=key;}
  var el=raidM.getElement();
  if(el){var fill=el.querySelector('.rhp i'),hpEl=el.querySelector('.rhp'),lbl=el.querySelector('.rlbl'),sub=el.querySelector('.rsub');
    var hpPct=dead?0:(gath?100:(r.max_hp?Math.max(0,Math.min(100,100*r.hp/r.max_hp)):100));
    if(fill)fill.style.width=hpPct+'%';
    if(hpEl)hpEl.style.opacity=(gath||dead)?'0':'1';
    if(lbl)lbl.textContent=r.emoji+' '+r.name;
    if(sub)sub.textContent=dead?'🏆 ПОВЕРЖЕН!':(gath?'🔥 сбор рейда · '+(r.n||0)+' в деле':'⚔️ '+(r.n||0)+' рубятся · Фаза '+ph);
    // числа урона/лечения по боссу (дельта HP за интервал поллинга)
    if(!gath&&!dead&&raidPrevHp>=0){var dh=raidPrevHp-r.hp;
      if(dh>0)floatRaid(el,dh,false); else if(dh<0)floatRaid(el,-dh,true);}
    raidPrevHp=(gath||dead)?-1:r.hp;
    // ТЕЛЕГРАФ заклинаний босса: 🛡 щит · 💀 проклятье · 👹 выводок · 🗣 рык
    var rtel=el.querySelector('.rtel');
    if(rtel){var bs=(r.ward?'🛡':'')+(r.curse?'💀':'')+(r.adds?'👹':'')+(r.roar?'🗣':'');
      rtel.classList.toggle('on',!!bs);
      if(bs!==raidTel){raidTel=bs;rtel.textContent=bs;
        if(bs){rtel.classList.remove('pop');void rtel.offsetWidth;rtel.classList.add('pop');}}}
    // FX добивания (раз на босса): ударная волна (CSS) + тряска карты + гаптик
    if(dead&&raidFxKey!==r.key){raidFxKey=r.key;
      var m=document.getElementById('map');
      if(m){m.classList.remove('shake');void m.offsetWidth;m.classList.add('shake');setTimeout(function(){m.classList.remove('shake');},480);}
      try{parent.postMessage({t:'nedo-raid-fx'},location.origin);}catch(_){}}}
  if(rb){
    rb.innerHTML='⚔️ <span>'+r.name+(dead?' повержен!':(gath?' — сбор рейда':' · рубят!'))+'</span><span class="go">'+(dead?'Итог':'В БОЙ')+'</span>';
    rb.onclick=openRaid;
    var ob=document.getElementById('ordaBar'),ordaShown=ob&&ob.style.display==='flex';   // не наложиться на баннер Орды
    rb.style.bottom='calc(env(safe-area-inset-bottom,0px) + '+(ordaShown?134:74)+'px)';
    rb.style.display='flex';}
}
function pollRaid(){fetch('/world/raid.json').then(function(r){return r.json();})
  .then(function(d){raidData=d.raid;renderRaid();}).catch(function(){});}
pollRaid();setInterval(pollRaid,5000);
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
    # Пока идёт обкатка (invmod.MAP_PUBLIC=False) орда на карте видна ТОЛЬКО админу.
    # Гейт по ?uid — мягкий (скрыть сырое, не безопасность). Запуск = MAP_PUBLIC=True.
    from bot.config import settings
    from bot.game import invasion as invmod
    if not invmod.MAP_PUBLIC and uid != settings.admin_id:
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
            # компактный таймлайн для ЧИТАЕМОСТИ боя на карте: HP орды(h)/дружины(a) +
            # активные способности по раундам — щит(w)/проклятье(c)/ярость(e)/волки(d).
            # Клиент по elapsed выбирает кадр (как HP) → телеграф синхронен симуляции.
            ctl = [{"h": int(f.get("hp", 0)), "a": int(f.get("army", 0)),
                    "w": 1 if f.get("ward") else 0, "c": 1 if f.get("curse") else 0,
                    "e": 1 if f.get("enraged") else 0, "d": 1 if (f.get("adds", 0) or 0) > 0 else 0}
                   for f in tl if isinstance(f, dict)]
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
                "army_hp_max": int(e.get("army_hp_max", 1) or 1), "tl": ctl,
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


RAID_LAIR = (0.40, 0.85)   # логово рейд-босса на карте (юг, вдали от Орды на севере)


async def _world_raid(request: web.Request) -> web.Response:
    """Лёгкий поллинг рейд-босса для карты: логово, emoji/имя, HP/фаза/бойцы, статус.
    Read-only, открыт ВСЕМ (рейд — публичная механика). Свежий труп показываем ~14с
    (окно «повержен» под FX добивания)."""
    from datetime import datetime, timezone

    from bot.game import raid as rd
    ev = None
    async with session_factory() as s:
        boss = await repo.get_active_raid(s)
        if boss is None:
            boss = await repo.latest_raid(s)          # мог только что пасть
        show = False
        if boss is not None:
            if boss.status in ("gathering", "active"):
                show = True
            elif boss.status == "dead" and boss.ends_at:
                ea = boss.ends_at if boss.ends_at.tzinfo else boss.ends_at.replace(tzinfo=timezone.utc)
                show = (datetime.now(timezone.utc) - ea).total_seconds() < 14
        if show:
            spec = rd.BOSSES.get(boss.boss_key)
            if spec is not None:
                mh = int(boss.max_hp or 0) or 1
                active = boss.status == "active"
                ev = {
                    "key": boss.boss_key, "emoji": spec.emoji, "name": spec.name,
                    "status": boss.status, "hp": max(0, int(boss.hp or 0)), "max_hp": mh,
                    "phase": rd.phase(boss), "n": rd.registered_count(boss),
                    "x": RAID_LAIR[0], "y": RAID_LAIR[1],
                    # телеграф активных заклинаний босса (для иконок на карте)
                    "ward": bool(active and rd.ward_left(boss) > 0),
                    "curse": bool(active and rd.curse_left(boss) > 0),
                    "adds": bool(active and rd.adds_hp(boss) > 0),
                    "roar": bool(active and rd.stun_left(boss) > 0),
                }
    return web.json_response({"raid": ev}, headers={"Cache-Control": "no-store"})


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
