"""Авто-подчистка сообщений в общих чатах через 2 минуты.

Чистим и триггеры игроков («гг …»), и ответы бота (панели, карта, рейтинг),
чтобы не засорять чат. Для панелей таймер сбрасывается на каждое действие
владельца (см. PanelGuardMiddleware) — пока играют, панель живёт; 2 минуты
без кликов — удаляется.

Удалять СВОИ сообщения бот может всегда (в пределах 48 ч). Чтобы удалять
ЧУЖИЕ триггер-сообщения, боту нужны права админа с «удалять сообщения» —
иначе попытка тихо игнорируется.
"""

import asyncio

from aiogram import Bot
from aiogram.types import Message

from bot import panels

DELETE_AFTER_SECONDS = 120

_tasks: dict[tuple[int, int], asyncio.Task] = {}


def schedule(bot: Bot, chat_id: int, message_id: int) -> None:
    """Запланировать удаление сообщения; повторный вызов сбрасывает отсчёт."""
    key = (chat_id, message_id)
    old = _tasks.get(key)
    if old is not None and not old.done():
        old.cancel()
    _tasks[key] = asyncio.create_task(_delete_later(bot, chat_id, message_id))


def schedule_message(message: Message | None) -> None:
    """То же, но из объекта сообщения и только для общих чатов."""
    if message is not None and panels.is_group(message):
        schedule(message.bot, message.chat.id, message.message_id)


async def _delete_later(bot: Bot, chat_id: int, message_id: int) -> None:
    key = (chat_id, message_id)
    try:
        await asyncio.sleep(DELETE_AFTER_SECONDS)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:  # noqa: BLE001 — уже удалено / нет прав / бота кикнули
            pass
        panels.forget(chat_id, message_id)
    except asyncio.CancelledError:
        return  # таймер сброшен новым действием
    finally:
        if _tasks.get(key) is asyncio.current_task():
            _tasks.pop(key, None)
