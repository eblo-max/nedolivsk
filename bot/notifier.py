"""Фоновые уведомления: работники вернулись с вылазки."""

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select

from bot import texts
from bot.db.base import session_factory
from bot.db.models import Player
from bot.keyboards.inline import claim_kb, craft_claim_kb

CHECK_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


async def notifier_loop(bot: Bot) -> None:
    """Раз в минуту проверяет завершённые вылазки и шлёт уведомления."""
    while True:
        try:
            await _notify_returned(bot)
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            logger.exception("Сбой в цикле уведомлений")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _notify_returned(bot: Bot) -> None:
    from bot.game.items import CATALOG

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        result = await session.execute(
            select(Player)
            .where(
                Player.expedition_resource.is_not(None),
                Player.expedition_ends_at <= now,
                Player.expedition_notified.is_(False),
            )
            .with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            try:
                await bot.send_message(
                    player.id,
                    texts.expedition_returned(player.expedition_resource),
                    reply_markup=claim_kb(),
                )
            except Exception:  # заблокировал бота и т.п. — не повторяем
                logger.warning("Не доставлено уведомление игроку %s", player.id)
            player.expedition_notified = True

        result = await session.execute(
            select(Player)
            .where(
                Player.craft_item.is_not(None),
                Player.craft_ends_at <= now,
                Player.craft_notified.is_(False),
            )
            .with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            item = CATALOG.get(player.craft_item)
            if item is not None:
                try:
                    await bot.send_message(
                        player.id,
                        texts.craft_ready_notification(item),
                        reply_markup=craft_claim_kb(),
                    )
                except Exception:
                    logger.warning("Не доставлен крафт игроку %s", player.id)
            player.craft_notified = True
        await session.commit()
