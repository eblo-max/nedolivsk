"""Ночная ходка — соло push-your-luck вылазка по тракту (личный режим).

Состояние забега живёт на player.night_run (JSONB); пишем ВСЕГДА присвоением
свежего объекта (p.night_run = run) — иначе SQLAlchemy без MutableDict не увидит
правок. Игрока лочим FOR UPDATE на каждый ход. «Лихо» бросает живой кубик
(answer_dice) и резолвит по выпавшему значению — бот результат не подкручивает.
"""

import asyncio
import random
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import effects, texts
from bot.db import repo
from bot.game import balance, city as citymod, nightrun
from bot.keyboards import inline as kb

router = Router()
UTC = timezone.utc


async def _blocked(cb: CallbackQuery) -> bool:
    """Режим выключен для всех (в разработке) — мягко отбиваем любой клик."""
    if balance.NIGHTRUN_ENABLED:
        return False
    await cb.answer("🌙 Ночная ходка ещё в разработке — скоро открою!", show_alert=True)
    return True


async def _player(cb: CallbackQuery, session: AsyncSession, *, lock: bool = False):
    p = await repo.get_player(session, cb.from_user.id, for_update=lock)
    if not p or not p.tavern:
        await cb.answer("Сначала заведи кабак: /start", show_alert=True)
        return None
    return p


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    """Правка текущей панели (подпись, если медиа; иначе текст)."""
    msg = cb.message
    try:
        if msg.photo or msg.video:
            await msg.edit_caption(caption=text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


async def _render_state(cb: CallbackQuery, p, run: dict) -> None:
    """Перерисовать экран под текущее состояние забега."""
    if run.get("state") == "fork":
        await _edit(cb, texts.nightrun_fork(p, run), kb.nightrun_fork_kb(run))
    elif run.get("state") == "meet":
        await _edit(cb, texts.nightrun_meet(p, run), kb.nightrun_meet_kb(run))
    elif run.get("state") == "crossroad":
        await _edit(cb, texts.nightrun_crossroad(p, run), kb.nightrun_cross_kb(run))
    else:
        await _edit(cb, texts.nightrun_intro(p), kb.nightrun_intro_kb(p))


async def _apply_factions(session: AsyncSession, p, factions) -> None:
    """Применить сдвиг силы фракций к ОБЩЕМУ городу игрока (если есть домашний
    чат). Город лочим FOR UPDATE — как в событиях, безопасно при параллели."""
    if not factions or p.chat_id is None:
        return
    city = await repo.get_or_create_city(session, p.chat_id, lock=True)
    fp = dict(city.faction_power or {})
    for fac, delta in factions:
        fp[fac] = max(balance.FACTION_MIN, min(balance.FACTION_MAX, fp.get(fac, 0) + delta))
    city.faction_power = fp


async def _finish(cb: CallbackQuery, text: str, *, win: bool) -> None:
    """Финальный экран (банк/бюст). В личке — свежее сообщение с анимэффектом."""
    msg = cb.message
    fx = effects.for_private(msg.chat, effects.FX_PARTY if win else effects.FX_POOP)
    markup = kb.nightrun_after_kb()
    if fx is None:
        await _edit(cb, text, markup)
        return
    try:                                          # снять кнопки со старой панели — без залипаний
        await msg.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    try:
        await msg.answer(text, reply_markup=markup, message_effect_id=fx)
    except TelegramBadRequest:
        await _edit(cb, text, markup)


@router.callback_query(F.data == "nr:open")
async def cb_open(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session)
    if p is None:
        return
    run = p.night_run or {}
    if nightrun.is_active(run):
        await _render_state(cb, p, run)
    else:
        await _edit(cb, texts.nightrun_intro(p), kb.nightrun_intro_kb(p))
    await cb.answer()


@router.callback_query(F.data == "nr:go")
async def cb_go(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session, lock=True)
    if p is None:
        return
    if nightrun.is_active(p.night_run or {}):                # уже в пути
        await _render_state(cb, p, p.night_run)
        await cb.answer()
        return
    if nightrun.cooldown_left(p) > 0:
        await cb.answer("Ноги ещё гудят — отдышись.", show_alert=True)
        return
    situation = None                                    # активная ситуация города красит ночь
    if p.chat_id is not None:
        city = await repo.get_or_create_city(session, p.chat_id)
        sit = citymod.current(city)
        situation = sit.id if sit else None
    p.night_run_at = datetime.now(UTC)
    p.night_run = nightrun.start(p, p.region or "", situation=situation)
    repo.add_log(session, "player", p.id, "🌙 ушёл в ночную ходку")
    await session.commit()
    await _render_state(cb, p, p.night_run)
    await cb.answer("🌙 В добрый путь…")


@router.callback_query(F.data.startswith("nr:pick:"))
async def cb_pick(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session, lock=True)
    if p is None:
        return
    run = dict(p.night_run or {})
    if not nightrun.is_active(run) or run.get("state") != "fork":
        await cb.answer("Развилка уже позади.", show_alert=True)
        return
    kind = cb.data.split(":", 2)[2]
    if kind not in nightrun.fork(run):
        await cb.answer("Эта тропа уже не та.", show_alert=True)
        return
    if kind == "gamble":
        await _gamble(cb, session, p, run)
        return
    out = nightrun.attempt(run, p, kind)
    if kind == "meet":                                  # встреча — под-экран выбора
        p.night_run = run
        await session.commit()
        await _edit(cb, texts.nightrun_meet(p, run), kb.nightrun_meet_kb(run))
        await cb.answer()
        return
    await _apply(cb, session, p, run, out)


@router.callback_query(F.data.startswith("nr:meet:"))
async def cb_meet(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session, lock=True)
    if p is None:
        return
    run = dict(p.night_run or {})
    if run.get("state") != "meet":
        await cb.answer("Встреча уже позади.", show_alert=True)
        return
    opt = cb.data.split(":", 2)[2]
    out = nightrun.meet_resolve(run, p, opt)
    await _apply_factions(session, p, out.get("factions"))   # сдвиг фракций в общий город
    p.night_run = run
    repo.add_log(session, "player", p.id, f"🗣 встреча на тракте ({out.get('opt')})")
    await session.commit()
    await _edit(cb, texts.nightrun_result(p, run, out), kb.nightrun_cross_kb(run))
    await cb.answer()


async def _gamble(cb: CallbackQuery, session: AsyncSession, p, run: dict) -> None:
    """Нода «Лихо»: живой бросок кубика, резолв по выпавшему значению."""
    await cb.answer("🎲 Картавый бросает кости…")
    val = random.randint(1, 6)
    try:
        dice = await cb.message.answer_dice(emoji="🎲")
        val = dice.dice.value
    except TelegramBadRequest:
        pass
    await asyncio.sleep(3.6)                                 # дать анимации доиграть
    out = nightrun.attempt(run, p, "gamble", roll=val)
    await _apply(cb, session, p, run, out, answered=True)


async def _apply(cb: CallbackQuery, session: AsyncSession, p, run: dict,
                 out: dict, *, answered: bool = False) -> None:
    """Записать исход испытания и показать перекрёсток либо финал (бюст)."""
    if out["busted"]:
        p.night_run = {}                                    # забег окончен
        repo.add_log(session, "player", p.id, "🌑 ходка сорвалась")
        await session.commit()
        await _finish(cb, texts.nightrun_bust(run, out), win=False)
    else:
        p.night_run = run
        await session.commit()
        await _edit(cb, texts.nightrun_result(p, run, out), kb.nightrun_cross_kb(run))
    if not answered:
        await cb.answer()


@router.callback_query(F.data == "nr:push")
async def cb_push(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session, lock=True)
    if p is None:
        return
    run = dict(p.night_run or {})
    if run.get("state") != "crossroad":
        await cb.answer("Сейчас не распутье.", show_alert=True)
        return
    nightrun.push(run)
    p.night_run = run
    await session.commit()
    await _render_state(cb, p, run)
    await cb.answer()


@router.callback_query(F.data == "nr:bank")
async def cb_bank(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session, lock=True)
    if p is None:
        return
    run = dict(p.night_run or {})
    if not nightrun.is_active(run):
        await cb.answer("Нечего сворачивать.", show_alert=True)
        return
    banked = nightrun.bank(run, p)
    p.night_run = {}
    repo.add_log(session, "player", p.id,
                 f"🏠 вернулся с ходки (+{nightrun.satchel_value(banked)}🪙-экв)")
    await session.commit()
    await _finish(cb, texts.nightrun_bank(banked), win=bool(banked))
    await cb.answer()
