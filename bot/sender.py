"""Устойчивая доставка сообщений: уважение к флуд-контролю Telegram + пейсинг.

Telegram режет частые отправки (~30 сообщений/сек глобально, 1/сек на чат) и на
превышение отвечает 429 с `retry_after`. Раньше циклы рассылки (анонсы мира,
утренний пуш, напоминания, очередь уведомлений) шли вплотную и ловили 429 общим
`except` — то есть молча ТЕРЯЛИ сообщение. При росте числа чатов/игроков это
оборачивалось дырами в рассылке.

`deliver` решает обе беды:
  • при TelegramRetryAfter — спит `retry_after` и повторяет один раз;
  • прочие ошибки (заблокировал бота / чат удалён) — лог и пропуск;
  • лёгкий пейсинг между отправками держит темп ниже лимита.

Принимает ФАБРИКУ корутины (а не саму корутину) — чтобы повтор был возможен.
Возвращает результат отправки (Message и т.п.) или None при неудаче.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.exceptions import TelegramRetryAfter

logger = logging.getLogger(__name__)

# ~22 отправки/сек — с запасом под лимит Telegram (~30/с). На фоне (после коммита,
# без удержания локов) это не мешает обработке кликов игроков.
SEND_PACE_SECONDS = 0.045


async def deliver(
    make_send: Callable[[], Awaitable[Any]], *, what: str = "сообщение"
) -> Any | None:
    """Отправить с уважением к флуд-контролю. Возвращает результат или None."""
    res = None
    try:
        res = await make_send()
    except TelegramRetryAfter as e:
        wait = e.retry_after + 0.5
        logger.warning("Флуд-контроль (%s): жду %.1fс и повторяю", what, wait)
        await asyncio.sleep(wait)
        try:
            res = await make_send()
        except Exception:  # noqa: BLE001 — повтор не удался
            logger.warning("Не доставлено после ожидания (%s)", what)
    except Exception:  # noqa: BLE001 — заблокировал бота / чат удалён и т.п.
        logger.warning("Не доставлено (%s)", what)
    await asyncio.sleep(SEND_PACE_SECONDS)
    return res
