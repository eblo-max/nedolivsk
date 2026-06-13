"""Живой город: показ события панелью и резолв выбора (в личке и в чате)."""

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import autoclean, panels
from bot.db import repo
from bot.db.models import Player
from bot.game import story_engine, story_state
from bot.keyboards import inline as kb

router = Router()


async def deliver_pending(message: Message, player: Player, owner_id: int) -> None:
    """Показать ожидающее событие новой панелью (в чате — за владельцем)."""
    s = story_engine.pending_storylet(player)
    if s is None:
        return
    text, markup = story_engine.present(s, player)
    msg = await message.answer(text, reply_markup=markup)
    panels.claim(msg, owner_id)  # в группе кнопки жмёт только владелец; в личке no-op


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("ev:"))
async def cb_event(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id, for_update=True)
    if player is None:
        await callback.answer()
        return

    s = story_engine.pending_storylet(player)
    arg = callback.data.split(":", 1)[1]

    if arg == "skip":
        story_state.clear_pending(player)
        await _edit(callback, "Ну, как-нибудь в другой раз.", kb.back_kb())
        await callback.answer()
        return

    if s is None:
        await callback.answer("Событие уже отыграло.", show_alert=True)
        return
    if not arg.isdigit() or int(arg) >= len(s.choices):
        await callback.answer()
        return

    now = datetime.now(timezone.utc)
    city = None
    if player.chat_id is not None:
        city = await repo.get_or_create_city(session, player.chat_id)
    shielded = story_state.is_shielded(player, now)

    outcome, ctx = story_engine.resolve(
        player, city, s, int(arg), now, shielded=shielded
    )
    if outcome is None:
        await callback.answer("Этот выбор сейчас недоступен.", show_alert=True)
        return

    # Летопись и эхо в общий чат — только если у игрока есть домашний чат.
    if player.chat_id is not None:
        for line in ctx.chronicle:
            await repo.add_chronicle(session, player.chat_id, line)
        for line in ctx.chat_echo:
            try:
                m = await callback.bot.send_message(player.chat_id, line)
                autoclean.schedule_message(m)
            except Exception:  # noqa: BLE001 — бота нет в чате и т.п.
                pass

    await _edit(callback, f"<b>{s.title}</b>\n\n{outcome.text}", kb.back_kb())
    await callback.answer()
