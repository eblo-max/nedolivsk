from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject
from sqlalchemy import func, update

from bot import autoclean, panels
from bot.db.base import session_factory
from bot.db.models import Player


def _actor_id(event: TelegramObject) -> int | None:
    """Telegram-id инициатора апдейта (для отметки активности)."""
    inner = getattr(event, "event", None)  # Update -> вложенное событие
    user = getattr(inner, "from_user", None)
    if user is None or user.is_bot:
        return None
    return user.id


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД на каждое событие и коммитит после хендлера.
    Заодно отмечает активность игрока (last_seen) и сбрасывает напоминания."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                uid = _actor_id(event)
                if uid is not None:  # любое действие игрока — он «в строю»
                    await session.execute(
                        update(Player).where(Player.id == uid)
                        .values(last_seen_at=func.now(), nudge_tier=0)
                    )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class PanelGuardMiddleware(BaseMiddleware):
    """В общих чатах к кнопкам панели пускает только её владельца."""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        # Подкидыш — публичная кнопка: жмёт любой, не только владелец панели.
        if event.data and event.data.startswith("loot:"):
            return await handler(event, data)
        msg = event.message
        if panels.is_group(msg):
            owner = panels.owner_of(msg.chat.id, msg.message_id)
            if owner is None:
                await event.answer(
                    "Панель устарела. Открой заново: «гг таверна».", show_alert=True
                )
                return None
            if owner != event.from_user.id:
                await event.answer(
                    "Не лапай чужой кабак! Открой свой: «гг таверна».", show_alert=True
                )
                return None
            # владелец что-то нажал — продлеваем жизнь панели ещё на 2 минуты
            autoclean.schedule(msg.bot, msg.chat.id, msg.message_id)
        return await handler(event, data)
