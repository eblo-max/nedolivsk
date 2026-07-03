"""Ночная ходка — соло push-your-luck вылазка по тракту (личный режим).

Состояние забега живёт на player.night_run (JSONB); пишем ВСЕГДА присвоением
свежего объекта (p.night_run = run) — иначе SQLAlchemy без MutableDict не увидит
правок. Игрока лочим FOR UPDATE на каждый ход. «Лихо» бросает живой кубик
(answer_dice) и резолвит по выпавшему значению — бот результат не подкручивает.
"""

import asyncio
import logging
import random
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputPollOption, PollAnswer
from sqlalchemy.ext.asyncio import AsyncSession

from bot import effects, texts
from bot.config import settings
from bot.db import repo
from bot.game import balance, city as citymod, nightrun
from bot.keyboards import inline as kb

router = Router()
logger = logging.getLogger(__name__)
UTC = timezone.utc


async def _blocked(cb: CallbackQuery) -> bool:
    """Доступ: открыт всем при NIGHTRUN_ENABLED, иначе — ТОЛЬКО админу (тест).
    Остальным — мягкий алерт «в разработке»."""
    if balance.NIGHTRUN_ENABLED or cb.from_user.id == settings.admin_id:
        return False
    await cb.answer("🌙 Ночная ходка ещё в разработке — скоро открою!", show_alert=True)
    return True


async def _edit_panel(bot: Bot, chat_id: int, msg_id: int, text: str, markup) -> None:
    """Правка панели из не-callback контекста (poll_answer): подпись, потом текст."""
    try:
        await bot.edit_message_caption(chat_id=chat_id, message_id=msg_id,
                                       caption=text, reply_markup=markup)
    except TelegramBadRequest:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id,
                                        reply_markup=markup)
        except TelegramBadRequest:
            pass


async def _player(cb: CallbackQuery, session: AsyncSession, *, lock: bool = False):
    p = await repo.get_player(session, cb.from_user.id, for_update=lock)
    if not p or not p.tavern:
        await cb.answer("Сначала заведи кабак: /start", show_alert=True)
        return None
    return p


def _cooldown(p) -> int:
    """Секунд до следующей ходки — одна ходка в NIGHTRUN_COOLDOWN_H часов (для
    всех, включая админа: иначе «прошёл и сразу снова» — абуз)."""
    return nightrun.cooldown_left(p)


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    """Правка текущей панели (подпись, если медиа; иначе текст). Косметика —
    не должна ронять хендлер (данные уже в БД). TelegramBadRequest (не изменено /
    старое сообщение) — ожидаемо, тихо; прочее — логируем, чтобы было видно."""
    msg = cb.message
    try:
        if msg.photo or msg.video:
            await msg.edit_caption(caption=text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("nightrun: сбой правки панели (uid=%s)", cb.from_user.id)


async def _render_state(cb: CallbackQuery, p, run: dict,
                        session: AsyncSession | None = None) -> None:
    """Перерисовать экран под текущее состояние забега. Любой сбой сборки текста/
    клавиатуры — НЕ молча: логируем (stdout + БД), затем безопасный экран, чтобы
    кнопка не «висела». Видимость поломки — чтобы такие баги не прятались."""
    try:
        if run.get("state") == "fork":
            await _edit(cb, texts.nightrun_fork(p, run), kb.nightrun_fork_kb(run))
        elif run.get("state") == "meet":
            await _edit(cb, texts.nightrun_meet(p, run), kb.nightrun_meet_kb(run))
        elif run.get("state") == "quiz":
            await _edit(cb, texts.nightrun_quiz_wait(p, run), kb.nightrun_wait_kb())
        elif run.get("state") == "crossroad":
            await _edit(cb, texts.nightrun_crossroad(p, run), kb.nightrun_cross_kb(run))
        else:
            cd = _cooldown(p)
            await _edit(cb, texts.nightrun_intro(p, cd), kb.nightrun_intro_kb(p, cd))
    except Exception as e:  # noqa: BLE001
        logger.exception("nightrun: сбой отрисовки (state=%s, uid=%s)",
                         run.get("state"), cb.from_user.id)
        if session is not None:
            repo.add_log(session, "error", cb.from_user.id,
                         f"ночная ходка: сбой отрисовки [{run.get('state')}] {type(e).__name__}: {e}")
        await _edit(cb, "🌙 Ходка сбилась. Открой «Ночная ходка» заново.",
                    kb.nightrun_after_kb())


async def _apply_factions(session: AsyncSession, p, factions) -> None:
    """Применить сдвиг силы фракций к ЕДИНОМУ мировому городу. Город лочим
    FOR UPDATE — как в событиях, безопасно при параллели."""
    if not factions:
        return
    city = await repo.get_world_city(session, lock=True)
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
        await _render_state(cb, p, run, session)
    else:
        cd = _cooldown(p)
        await _edit(cb, texts.nightrun_intro(p, cd), kb.nightrun_intro_kb(p, cd))
    await cb.answer()


@router.callback_query(F.data == "nr:go")
async def cb_go(cb: CallbackQuery, session: AsyncSession) -> None:
    if await _blocked(cb):
        return
    p = await _player(cb, session, lock=True)
    if p is None:
        return
    if nightrun.is_active(p.night_run or {}):                # уже в пути
        await _render_state(cb, p, p.night_run, session)
        await cb.answer()
        return
    if _cooldown(p) > 0:
        await cb.answer("Ноги ещё гудят — отдышись.", show_alert=True)
        return
    city = await repo.get_world_city(session)           # активная ситуация мира красит ночь
    sit = citymod.current(city)
    situation = sit.id if sit else None
    p.night_run_at = datetime.now(UTC)
    p.night_run = nightrun.start(p, p.region or "", situation=situation)
    repo.add_log(session, "player", p.id, "🌙 ушёл в ночную ходку")
    await session.commit()
    await _render_state(cb, p, p.night_run, session)
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
    if kind == "quiz":                                  # загадка — нативная викторина
        rd = nightrun.current_riddle(run)
        try:
            sent = await cb.message.answer_poll(
                question=rd["q"],
                options=[InputPollOption(text=o) for o in rd["options"]],
                type="quiz", correct_option_id=rd["correct"], is_anonymous=False)
            run["quiz"] = {"poll_id": sent.poll.id,
                           "panel": [cb.message.chat.id, cb.message.message_id]}
        except Exception:  # noqa: BLE001 — опрос не ушёл: считаем «мимо», забег не виснет
            logger.exception("nightrun: не отправилась викторина (uid=%s)", cb.from_user.id)
            await _apply(cb, session, p, run, nightrun.quiz_resolve(run, p, False))
            return
        p.night_run = run
        await session.commit()
        await _edit(cb, texts.nightrun_quiz_wait(p, run), kb.nightrun_wait_kb())
        await cb.answer("🔮 Ведьма загадала загадку…")
        return
    await _apply(cb, session, p, run, out)


@router.poll_answer()
async def cb_poll(poll_answer: PollAnswer, session: AsyncSession, bot: Bot) -> None:
    """Ответ на викторину Ведьмы: резолвим загадку и правим панель забега."""
    if not poll_answer.option_ids or poll_answer.user is None:   # отозвал голос / нет юзера
        return
    p = await repo.get_player(session, poll_answer.user.id, for_update=True)
    if p is None:
        return
    run = dict(p.night_run or {})
    q = run.get("quiz") or {}
    if run.get("state") != "quiz" or q.get("poll_id") != poll_answer.poll_id:
        return                                          # стейл/чужой опрос — игнор
    correct = poll_answer.option_ids[0] == nightrun.current_riddle(run)["correct"]
    out = nightrun.quiz_resolve(run, p, correct)
    p.night_run = run
    repo.add_log(session, "player", p.id, f"❓ загадка: {'верно' if correct else 'мимо'}")
    await session.commit()
    chat_id, msg_id = (q.get("panel") or [None, None])
    if chat_id:
        await _edit_panel(bot, chat_id, msg_id,
                          texts.nightrun_result(p, run, out), kb.nightrun_cross_kb(run))


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
    except Exception:  # noqa: BLE001 — кубик не ушёл: режемся по случайному значению
        logger.exception("nightrun: не отправился кубик (uid=%s)", cb.from_user.id)
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
    await _render_state(cb, p, run, session)
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
