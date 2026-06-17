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
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.exceptions import TelegramRetryAfter

logger = logging.getLogger(__name__)

# ~22 отправки/сек — с запасом под лимит Telegram (~30/с). На фоне (после коммита,
# без удержания локов) это не мешает обработке кликов игроков.
SEND_PACE_SECONDS = 0.045

# Анти-флуд КОСМЕТИЧЕСКИХ правок одного сообщения (живой HP-бар рейда и т.п.).
# Telegram режет частые правки одного сообщения (бурст → 429). Лидирующий троттл
# схлопывает серию быстрых ударов в одну правку за интервал.
EDIT_MIN_INTERVAL_SECONDS = 3.0
_last_edit: dict[tuple[int, int], float] = {}


def claim_edit(
    chat_id: int, message_id: int, *, min_interval: float = EDIT_MIN_INTERVAL_SECONDS
) -> bool:
    """True — сообщение можно перерисовать (прошёл интервал), False — слишком часто,
    пропускаем (правку догонит следующий клик или тик нотифаера). Бережёт от 429
    на горячем рейде, где толпа лупит «Бить» по одному сообщению.

    Применять ТОЛЬКО к косметике (живой HP-бар). Важные правки — старт боя, рык,
    «ПОВЕРЖЕН» — идут мимо троттла (через deliver), чтобы финал точно долетел."""
    if len(_last_edit) > 4000:        # рейды редки — старые ключи мертвы, чистим оптом
        _last_edit.clear()
    key = (chat_id, message_id)
    now = time.monotonic()
    if now - _last_edit.get(key, 0.0) < min_interval:
        return False
    _last_edit[key] = now
    return True


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
