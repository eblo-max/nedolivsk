"""Фоновые уведомления: работники вернулись с вылазки."""

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select

from bot import texts
from bot.db.base import session_factory
from bot.db.models import Player, Tavern
from bot.keyboards.inline import buildings_notify_kb, claim_kb, craft_claim_kb

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
    from bot.game.items import CATALOG, parse_entry

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
            item_id, tier = parse_entry(player.craft_item)
            item = CATALOG.get(item_id)
            if item is not None:
                try:
                    await bot.send_message(
                        player.id,
                        texts.craft_ready_notification(item, tier),
                        reply_markup=craft_claim_kb(),
                    )
                except Exception:
                    logger.warning("Не доставлен крафт игроку %s", player.id)
            player.craft_notified = True

        from bot.game import buildings as bld

        result = await session.execute(
            select(Player)
            .where(Player.build_item.is_not(None), Player.build_ends_at <= now)
            .with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            building = bld.finalize_build(player, player.tavern)  # завершаем стройку
            if building is None:
                continue
            try:
                await bot.send_message(
                    player.id,
                    texts.build_ready_notification(building),
                    reply_markup=buildings_notify_kb(),
                )
            except Exception:
                logger.warning("Не доставлено о стройке игроку %s", player.id)

        from bot.game import production as prod

        result = await session.execute(
            select(Player)
            .join(Tavern, Tavern.player_id == Player.id)
            .where(Tavern.production != {})
            .with_for_update(of=Player, skip_locked=True)
        )
        for player in result.scalars().all():
            tavern = player.tavern
            # Пивоварня (с фазами/выдержкой)
            bbatch = (tavern.production or {}).get("brewery")
            if bbatch:
                phase, _ = prod.brew_phase(tavern)
                stage = bbatch.get("stage", "ferment")
                if phase in ("ready", "ripe") and bbatch.get("notified") != stage:
                    tier = int(bbatch["tier"])
                    msg = (
                        texts.brew_ready_notification(tier) if phase == "ready"
                        else texts.brew_aged_notification(tier)
                    )
                    try:
                        await bot.send_message(
                            player.id, msg, reply_markup=buildings_notify_kb()
                        )
                    except Exception:
                        logger.warning("Не доставлено о варке игроку %s", player.id)
                    new = dict(tavern.production)
                    new["brewery"] = {**bbatch, "notified": stage}
                    tavern.production = new
            # Медоварня (простая готовность)
            mbatch = (tavern.production or {}).get("meadery")
            if (mbatch and not mbatch.get("notified")
                    and prod.state(tavern, "meadery")[0] == "ready"):
                recipe = mbatch.get("recipe", "mead")
                try:
                    await bot.send_message(
                        player.id, texts.meadery_ready_notification(recipe),
                        reply_markup=buildings_notify_kb(),
                    )
                except Exception:
                    logger.warning("Не доставлено о медовухе игроку %s", player.id)
                new = dict(tavern.production)
                new["meadery"] = {**mbatch, "notified": True}
                tavern.production = new
        await session.commit()
