"""Инфо-хаб: разделы о игре (как играть, живой город, в чат, команды).

Доступен с приветствия (новичок) и с экрана таверны (кнопка «ℹ️ О игре»).
Работает и в личке, и в общем чате — в группе сообщение закрепляется за
владельцем (PanelGuard), навигация правит текст на месте.
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from bot import panels, texts
from bot.keyboards import inline as kb

router = Router()


async def _show(callback: CallbackQuery, text: str, markup) -> None:
    """Из фото (welcome/таверна) — новым сообщением; из текста — правкой на месте."""
    msg = callback.message
    if msg.photo:
        sent = await msg.answer(text, reply_markup=markup)
        panels.claim(sent, callback.from_user.id)  # в группе жмёт только владелец
    else:
        try:
            await msg.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery) -> None:
    await _show(
        callback,
        "ℹ️ <b>О Недоливске</b>\nКуда лезем, кабатчик?",
        kb.info_nav_kb(),
    )


@router.callback_query(F.data == "how_play")
async def cb_how_play(callback: CallbackQuery) -> None:
    await _show(callback, texts.RULES, kb.info_nav_kb())


@router.callback_query(F.data == "living_city")
async def cb_living_city(callback: CallbackQuery) -> None:
    await _show(callback, texts.LIVING_CITY, kb.info_nav_kb())


@router.callback_query(F.data == "commands")
async def cb_commands(callback: CallbackQuery) -> None:
    await _show(callback, texts.COMMANDS_SCREEN, kb.info_nav_kb())


@router.callback_query(F.data == "add_chat")
async def cb_add_chat(callback: CallbackQuery) -> None:
    me = await callback.bot.me()
    await _show(callback, texts.ADD_TO_CHAT, kb.add_chat_kb(me.username))
