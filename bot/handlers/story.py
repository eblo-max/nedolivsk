"""Живой город: показ события панелью и резолв выбора (в личке и в чате)."""

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import autoclean, images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import story_engine, story_state
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


@router.callback_query(F.data == "citizens")
async def cb_citizens(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if player is None:
        await callback.answer()
        return
    await common.caption_edit(
        callback.message, texts.citizens_screen(player), kb.citizens_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "city")
async def cb_city(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if player is None:
        await callback.answer()
        return
    city = await repo.get_world_city(session)   # единый мир — город у всех общий
    await common.caption_edit(callback.message, texts.city_screen(city), kb.city_kb())
    await callback.answer()


@router.callback_query(F.data == "market")
async def cb_market(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if player is None:
        await callback.answer()
        return
    city = await repo.get_world_city(session)   # единый мир
    await common.show_image_panel(
        callback.message, images.named_image("rinok"),
        texts.market_screen(city), kb.market_kb(), callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "chronicle")
async def cb_chronicle(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if player is None:
        await callback.answer()
        return
    entries = await repo.recent_chronicle(session, repo.GLOBAL_CITY_ID, 10)  # единый мир
    await common.caption_edit(
        callback.message, texts.chronicle_screen(entries), kb.chronicle_kb()
    )
    await callback.answer()


async def deliver_pending(message: Message, player: Player, owner_id: int) -> None:
    """Показать ожидающее событие новой панелью (в чате — за владельцем)."""
    s = story_engine.pending_storylet(player)
    if s is None:
        return
    text, markup = story_engine.present(s, player)
    text = common.tag_in_group(message, player, text)  # в чате — тег-пинг владельцу
    msg = await message.answer(text, reply_markup=markup)
    panels.claim(msg, owner_id)  # в группе кнопки жмёт только владелец; в личке no-op


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "event_open")
async def cb_event_open(callback: CallbackQuery, session: AsyncSession) -> None:
    """Вернуться к незакрытому событию (кнопка «Тебя ждёт гость»)."""
    player = await repo.get_player(session, callback.from_user.id, for_update=True)
    if player is None:
        await callback.answer()
        return
    if story_engine.pending_storylet(player) is None:
        if story_state.get_pending(player):  # висит несуществующий сторилет — снять
            story_state.clear_pending(player)
        await callback.answer("Гость уже ушёл.", show_alert=True)
        return
    await deliver_pending(callback.message, player, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("ev:"))
async def cb_event(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id, for_update=True)
    if player is None:
        await callback.answer()
        return

    s = story_engine.pending_storylet(player)
    arg = callback.data.split(":", 1)[1]

    if s is None:
        # Нет события или висит исчезнувший между деплоями сторилет — снять.
        if story_state.get_pending(player):
            story_state.clear_pending(player)
        await callback.answer("Событие уже отыграло.", show_alert=True)
        return

    if arg == "skip":
        # Откладываем, не теряем: гость ждёт, вернуться можно кнопкой «🔔».
        await _edit(
            callback,
            "Гость обождёт у стойки. Надумаешь — жми «🔔 Тебя ждёт гость».",
            kb.back_kb(),
        )
        await callback.answer()
        return

    if not arg.isdigit() or int(arg) >= len(s.choices):
        await callback.answer()
        return

    now = datetime.now(timezone.utc)
    city = await repo.get_world_city(session, lock=True)   # единый мир — фракции общие
    shielded = story_state.is_shielded(player, now)

    outcome, ctx = story_engine.resolve(
        player, city, s, int(arg), now, shielded=shielded
    )
    if outcome is None:
        await callback.answer("Этот выбор сейчас недоступен.", show_alert=True)
        return

    # Летопись — в общую мировую (видят все). Эхо — в домашний чат игрока, если есть.
    for line in ctx.chronicle:
        await repo.add_chronicle(session, repo.GLOBAL_CITY_ID, line)
    if player.chat_id is not None:
        for line in ctx.chat_echo:
            try:
                m = await callback.bot.send_message(player.chat_id, line)
                autoclean.schedule_message(m)
            except Exception:  # noqa: BLE001 — бота нет в чате и т.п.
                pass

    await _edit(callback, f"<b>{s.title}</b>\n\n{outcome.text}", kb.back_kb())
    await callback.answer()
