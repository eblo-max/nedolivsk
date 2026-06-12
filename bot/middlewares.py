from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.db.base import session_factory


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД на каждое событие и коммитит после хендлера."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with session_factory() as session:
            data["session"] = session
            result = await handler(event, data)
            await session.commit()
            return result
