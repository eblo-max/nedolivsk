"""Фоновые уведомления: работники вернулись с вылазки."""

import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import func, select

from bot import announce, panels, texts
from bot.db import repo
from bot.db.base import session_factory
from bot.db.models import Player, Tavern
from bot.game import city as citymod
from bot.game import market as marketmod
from bot.game import season, story_engine, story_state
from bot.game import world as wld
from bot.keyboards.inline import buildings_notify_kb, claim_kb, craft_claim_kb

CHECK_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


async def _notify(bot: Bot, player: Player, text: str, markup) -> None:
    """Уведомление игроку. Если известен «домашний» чат (заходил через «гг») —
    постим туда с упоминанием и регистрируем сообщение как панель игрока, чтобы
    к кнопке пускало только владельца (PanelGuard). Иначе или при сбое — в личку."""
    if player.chat_id is not None:
        name = html.escape(player.first_name or "Хозяин")
        body = f'<a href="tg://user?id={player.id}">{name}</a>!\n{text}'
        try:
            msg = await bot.send_message(player.chat_id, body, reply_markup=markup)
            panels.claim(msg, player.id)  # кнопку жмёт только владелец
            return
        except Exception:  # noqa: BLE001 — бота нет в чате/чат удалён
            logger.warning(
                "Увед. в чат %s игроку %s не ушло, шлю в личку",
                player.chat_id, player.id,
            )
    try:
        await bot.send_message(player.id, text, reply_markup=markup)
    except Exception:  # noqa: BLE001 — заблокировал бота и т.п.
        logger.warning("Уведомление игроку %s не доставлено", player.id)


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
        # Планировщик мира: открыть/закрыть ярмарку по расписанию.
        world = await repo.get_or_create_world(session)
        fair_event = wld.advance(world)  # 'pre'|'open'|'close'|None — анонс в чаты

        # Сезоны/праздники: детект смены для анонса (глобально, по дате).
        cur_season = season.season_index(now)
        season_changed = world.season != cur_season
        world.season = cur_season
        hol = season.holiday(now)
        hol_token = f"{hol.id}:{now.date().isoformat()}" if hol else None
        holiday_new = hol is not None and world.holiday != hol_token
        if hol is not None:
            world.holiday = hol_token

        # Рассылку копим и шлём ПОСЛЕ коммита, чтобы не держать локи строк
        # через сетевые вызовы Telegram (иначе клики игроков ждут весь тик).
        outbox: list[tuple] = []  # (player, text, markup)

        # Живой город: доставка созревших отложенных событий (цепочки-истории).
        result = await session.execute(
            select(Player)
            .where(func.coalesce(
                func.jsonb_array_length(Player.story["queue"]), 0) > 0)
            .with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            if story_state.get_pending(player):
                continue
            due = story_state.queue_pop_due(player, now)
            if not due:
                continue
            for extra in due[1:]:
                story_state.queue_push(player, extra, 0.02)  # вернём в очередь
            s = story_engine.get(due[0])
            if s is None:
                continue
            story_state.set_pending(player, s.id, s.npc)
            text, markup = story_engine.present(s, player)
            outbox.append((player, text, markup))

        result = await session.execute(
            select(Player)
            .where(Player.expeditions != [])
            .with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            newly: list[str] = []
            new_exps = []
            for e in (player.expeditions or []):
                ready = datetime.fromisoformat(e["ends_at"]) <= now
                if ready and not e.get("notified"):
                    newly.append(e["resource"])
                    new_exps.append({**e, "notified": True})
                else:
                    new_exps.append(e)
            if not newly:
                continue
            outbox.append((player, texts.expedition_returned(newly), claim_kb()))
            player.expeditions = new_exps

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
                outbox.append((
                    player,
                    texts.craft_ready_notification(item, tier), craft_claim_kb(),
                ))
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
            outbox.append((
                player,
                texts.build_ready_notification(building), buildings_notify_kb(),
            ))

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
                    outbox.append((player, msg, buildings_notify_kb()))
                    new = dict(tavern.production)
                    new["brewery"] = {**bbatch, "notified": stage}
                    tavern.production = new
            # Медоварня (простая готовность)
            mbatch = (tavern.production or {}).get("meadery")
            if (mbatch and not mbatch.get("notified")
                    and prod.state(tavern, "meadery")[0] == "ready"):
                recipe = mbatch.get("recipe", "mead")
                outbox.append((
                    player,
                    texts.meadery_ready_notification(recipe), buildings_notify_kb(),
                ))
                new = dict(tavern.production)
                new["meadery"] = {**mbatch, "notified": True}
                tavern.production = new
            # Кухня (простая готовность)
            kbatch = (tavern.production or {}).get("kitchen")
            if (kbatch and not kbatch.get("notified")
                    and prod.state(tavern, "kitchen")[0] == "ready"):
                outbox.append((
                    player,
                    texts.kitchen_ready_notification(), buildings_notify_kb(),
                ))
                new = dict(tavern.production)
                new["kitchen"] = {**kbatch, "notified": True}
                tavern.production = new
            # Винокурня (простая готовность)
            wbatch = (tavern.production or {}).get("winery")
            if (wbatch and not wbatch.get("notified")
                    and prod.state(tavern, "winery")[0] == "ready"):
                outbox.append((
                    player,
                    texts.winery_ready_notification(), buildings_notify_kb(),
                ))
                new = dict(tavern.production)
                new["winery"] = {**wbatch, "notified": True}
                tavern.production = new
        # Живой город: симуляция фракций — дрейф силы, старт/конец ситуаций.
        cities = await repo.all_cities(session, lock=True)
        city_events: list[tuple[int, str]] = []  # (chat_id, текст анонса)
        for city in cities:
            marketmod.decay(city, now)  # рынок впитывает излишки сбыта
            for kind, sit in citymod.advance(city, now):
                text = sit.activate_text if kind == "activate" else sit.expire_text
                city_events.append((city.chat_id, text))
                if kind == "activate":
                    await repo.add_chronicle(session, city.chat_id, sit.chron)

        await session.commit()
        wld.refresh_cache(world)  # синхронизируем кэш ярмарки для экранов/дохода
        for city in cities:
            citymod.refresh_cache(city, now)  # кэш ситуаций для экранов

        # Персональные уведомления — после коммита (локи уже отпущены).
        for player, text, markup in outbox:
            await _notify(bot, player, text, markup)

        # Анонсы мировых событий в общие чаты (после коммита состояния).
        if fair_event or season_changed or holiday_new:
            chat_ids = await repo.all_chat_ids(session)
            if fair_event:
                await announce.broadcast_fair(bot, fair_event, chat_ids, world)
            season_msgs = []
            if season_changed:
                season_msgs.append(texts.season_announce(season.SEASONS[cur_season]))
            if holiday_new:
                season_msgs.append(texts.holiday_announce(hol))
            for chat_id in chat_ids:
                for text in season_msgs:
                    try:
                        await bot.send_message(chat_id, text)
                    except Exception:  # noqa: BLE001
                        logger.warning("Анонс сезона не доставлен в чат %s", chat_id)
        # Анонсы городских ситуаций (после коммита).
        for chat_id, text in city_events:
            try:
                await bot.send_message(chat_id, text)
            except Exception:  # noqa: BLE001 — бота нет в чате и т.п.
                logger.warning("Анонс ситуации не доставлен в чат %s", chat_id)
