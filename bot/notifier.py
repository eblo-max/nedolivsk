"""Фоновые уведомления: работники вернулись с вылазки."""

import asyncio
import html
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import func, select

from bot import announce, effects, panels, texts
from bot.db import repo
from bot.db.base import session_factory
from bot.sender import deliver
from bot.db.models import Player, Tavern
from bot.game import auction as auctionmod
from bot.game import balance
from bot.game import city as citymod
from bot.game import loot
from bot.game import market as marketmod
from bot.game import npc
from bot.game import season, story_engine, story_state
from bot.game import world as wld
from bot.keyboards.inline import (
    bonus_push_kb, buildings_notify_kb, claim_kb, craft_claim_kb, hunt_cta_kb,
    idle_nudge_kb, loot_kb,
)

CHECK_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


async def _notify(bot: Bot, player: Player, text: str, markup) -> None:
    """Уведомление игроку. Если известен «домашний» чат (заходил через «гг») —
    постим туда с упоминанием и регистрируем сообщение как панель игрока, чтобы
    к кнопке пускало только владельца (PanelGuard). Иначе или при сбое — в личку."""
    if player.chat_id is not None:
        name = html.escape(player.first_name or "Хозяин")
        body = f'<a href="tg://user?id={player.id}">{name}</a>!\n{text}'
        msg = await deliver(
            lambda: bot.send_message(player.chat_id, body, reply_markup=markup),
            what=f"увед→чат{player.chat_id}")
        if msg is not None:
            panels.claim(msg, player.id)  # кнопку жмёт только владелец
            return
        # в чат не ушло (бота нет/чат удалён) — пробуем личку
    await deliver(lambda: bot.send_message(player.id, text, reply_markup=markup),
                  what=f"увед→личка{player.id}")


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

        # Утренний пуш «бонус готов»: раз в день после рубежа 10:00 МСК.
        # Шлём недавно активным (за 3 дня) — давно ушедших ведёт «возвращалка».
        from bot.game import buff as buffmod
        bonus_push_targets: list[int] = []
        day_key = buffmod.reset_day_key(now)
        if world.bonus_push_on != day_key:
            world.bonus_push_on = day_key
            res = await session.execute(
                select(Player.id)
                .join(Tavern, Tavern.player_id == Player.id)
                .where(Player.last_seen_at.is_not(None),
                       Player.last_seen_at >= now - timedelta(days=3))
            )
            bonus_push_targets = [r[0] for r in res.all()]

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

        # Охота: пингуем, когда раненый охотник восстановил HP до боевого порога.
        result = await session.execute(
            select(Player).where(
                Player.hunt_ready_at.is_not(None),
                Player.hunt_ready_at <= now,
            ).with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            player.hunt_ready_at = None
            outbox.append((player, texts.hunter_recovered_notification(), hunt_cta_kb()))

        # Возвращалка: напоминаем забывчивым (простой 1/3/7 дней, тон нарастает).
        # nudge_tier сбрасывается в 0 при любой активности (middleware), так что
        # одно напоминание на ступень за период простоя.
        idle_nudges: list[tuple[int, int]] = []  # (player_id, ступень)
        result = await session.execute(
            select(Player).where(
                Player.last_seen_at.is_not(None),
                Player.last_seen_at < now - timedelta(days=1),
                Player.nudge_tier < 3,
            ).with_for_update(skip_locked=True)
        )
        for player in result.scalars().all():
            seen = player.last_seen_at
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            days = (now - seen).total_seconds() / 86400
            tier = 3 if days >= 7 else 2 if days >= 3 else 1
            if tier > player.nudge_tier:
                player.nudge_tier = tier
                idle_nudges.append((player.id, tier))

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
            # Рецептурные пристройки (пекарня/коптильня/сыроварня) — обобщённо
            for bname in prod.RECIPES:
                rbatch = (tavern.production or {}).get(bname)
                if (rbatch and not rbatch.get("notified")
                        and prod.state(tavern, bname)[0] == "ready"):
                    outbox.append((
                        player,
                        texts.recipe_ready_notification(rbatch.get("recipe")),
                        buildings_notify_kb(),
                    ))
                    new = dict(tavern.production)
                    new[bname] = {**rbatch, "notified": True}
                    tavern.production = new
        # Живой город: блокируем города ПЕРВЫМИ (FOR UPDATE), чтобы тик фракций
        # не словил гонку с правкой faction_power из хендлеров.
        cities = await repo.all_cities(session, lock=True)

        # Аукцион: горожане перебивают ставки по активным лотам; закрытие — продажа.
        result = await session.execute(
            select(Player)
            .join(Tavern, Tavern.player_id == Player.id)
            .where(Tavern.auction != {})
            .with_for_update(of=Player, skip_locked=True)
        )
        for player in result.scalars().all():
            tavern = player.tavern
            if auctionmod.is_due(tavern, now):
                res = auctionmod.settle(player, tavern, world)  # сбыт на ЕДИНЫЙ рынок
                if res is not None:
                    if res.get("sold"):
                        from bot.game import production as prodmod
                        gn = (prodmod.GOODS[res["good"]].name
                              if res["good"] in prodmod.GOODS else res["good"])
                        repo.add_log(session, "player", player.id,
                                     f"🔨 аукцион: продал {res['qty']}×{gn} "
                                     f"за {res['gold']} 🪙")
                    outbox.append((
                        player, texts.auction_settled(res),
                        buildings_notify_kb()))
                continue
            chance = balance.AUCTION_BID_CHANCE * (
                balance.AUCTION_FAIR_BID_MULT if wld.is_fair() else 1.0)
            if random.random() < chance:
                had_bid = bool((tavern.auction or {}).get("top_bid"))
                bres = auctionmod.try_bid(tavern, world)
                if bres and not had_bid:  # первая ставка — пингуем продавца
                    from bot.game import production as prodmod
                    lot = tavern.auction or {}
                    gn = (prodmod.GOODS[lot.get("good")].name
                          if lot.get("good") in prodmod.GOODS else lot.get("good"))
                    repo.queue_notify(
                        session, player.id,
                        f"🔨 Твой лот {lot.get('qty')}×{gn} заметили на торгах — "
                        f"ставка {bres['unit']} 🪙!")

        # Авто-истечение биржевых лотов: старше TTL — вернуть товар/залог владельцу.
        from bot.game import production as prodmod2
        stale_cut = now - timedelta(days=balance.BOURSE_ORDER_TTL_DAYS)
        for o in await repo.stale_orders(session, stale_cut, 30):
            owner = await repo.get_player(session, o.seller_id, for_update=True)
            gname = (prodmod2.GOODS[o.good].name
                     if o.good in prodmod2.GOODS else o.good)
            if owner is not None and o.side == "sell" and owner.tavern is not None:
                pr = dict(owner.tavern.products or {})
                pr[o.good] = pr.get(o.good, 0) + o.qty
                owner.tavern.products = pr
                repo.queue_notify(session, owner.id,
                                  f"⌛ Лот на бирже истёк — {o.qty}×{gname} в погребе")
            elif owner is not None and o.side == "buy":
                owner.gold += o.qty * o.unit_price  # возврат залога
                repo.queue_notify(session, owner.id,
                                  f"⌛ Заявка «куплю» истекла — залог "
                                  f"{o.qty * o.unit_price} 🪙 вернулся")
            await repo.delete_order(session, o.id)

        city_events: list[tuple[int, str]] = []  # (chat_id, текст анонса)

        # ЕДИНЫЙ рынок: масштаб (число активных чатов) для адаптивных порогов цены,
        # затем впитывание перекоса + редкий пульс — двигает цену всего мира сразу.
        # Молва о скачке цен идёт во ВСЕ чаты (это мировая новость).
        world.market_scale = max(1, await repo.count_known_chats(session))
        marketmod.decay(world, now)
        if random.random() < balance.MARKET_PULSE_CHANCE:
            cit = npc.random_pulser()
            good, delta, _verb = cit.pulse
            marketmod.nudge(world, good, delta)
            for cid in await repo.all_chat_ids(session):
                city_events.append((cid, texts.market_pulse_announce(cit)))
                await repo.add_chronicle(session, cid, texts.market_pulse_chron(cit))

        # Симуляция фракций — по чатам (фракции/ситуации остаются ЛОКАЛЬНЫМИ).
        for city in cities:
            for kind, sit in citymod.advance(city, now):
                text = sit.activate_text if kind == "activate" else sit.expire_text
                city_events.append((city.chat_id, text))
                if kind == "activate":
                    await repo.add_chronicle(session, city.chat_id, sit.chron)

        # Подкидыш: в каждом чате независимо ~раз в час «что-то теряется».
        # Не множим, пока висит неподобранный (анти-навал).
        await repo.cleanup_loot(session)
        await repo.cleanup_logs(session)  # держим журнал в разумном размере
        loot_to_post: list[tuple[int, int]] = []
        for chat_id in await repo.all_chat_ids(session):
            if random.random() >= balance.LOOT_DROP_CHANCE:
                continue
            if await repo.has_active_loot(session, chat_id):
                continue
            drop = await repo.create_loot(session, chat_id)
            loot_to_post.append((chat_id, drop.id))

        await session.commit()
        wld.refresh_cache(world)  # синхронизируем кэш ярмарки для экранов/дохода
        for city in cities:
            citymod.refresh_cache(city, now)  # кэш ситуаций для экранов

        # Персональные уведомления — после коммита (локи уже отпущены).
        for player, text, markup in outbox:
            await _notify(bot, player, text, markup)

        # Возвращалка — строго в личку (nudge_tier уже зафиксирован: при сбое
        # доставки не долбим каждый тик, ждём следующей ступени/возврата).
        for pid, tier in idle_nudges:
            await deliver(
                lambda p=pid, t=tier: bot.send_message(
                    p, texts.idle_nudge(t), reply_markup=idle_nudge_kb()),
                what=f"простой→{pid}")

        # Утренний пуш «бонус готов» — в личку (маркер дня уже зафиксирован).
        for pid in bonus_push_targets:
            await deliver(
                lambda p=pid: bot.send_message(
                    p, texts.bonus_ready_push(), reply_markup=bonus_push_kb()),
                what=f"пуш-бонус→{pid}")

        # Outbox: отложенная личка (биржа: «твой лот купили» и т.п.).
        notes = await repo.pop_notifications(session, 50)
        if notes:
            for n in notes:
                await deliver(lambda nn=n: bot.send_message(nn.user_id, nn.text),
                              what=f"outbox→{n.user_id}")
            await repo.delete_notifications(session, [n.id for n in notes])
            await session.commit()

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
                    msg = await deliver(
                        lambda cid=chat_id, t=text: bot.send_message(cid, t),
                        what=f"сезон→{chat_id}")
                    await effects.react_msg(msg, "🎉")  # праздничный бейдж
        # Анонсы городских ситуаций (после коммита).
        for chat_id, text in city_events:
            msg = await deliver(
                lambda cid=chat_id, t=text: bot.send_message(cid, t),
                what=f"ситуация→{chat_id}")
            await effects.react_msg(msg, "🔥")  # «жизнь» городу
        # Подкидыш — постим после коммита (строка уже сохранена, id известен).
        orphaned: list[int] = []
        for chat_id, drop_id in loot_to_post:
            drop_text = texts.loot_drop(loot.flavor())
            msg = await deliver(
                lambda cid=chat_id, did=drop_id, t=drop_text: bot.send_message(
                    cid, t, reply_markup=loot_kb(did)),
                what=f"подкидыш→{chat_id}")
            if msg is None:
                orphaned.append(drop_id)  # не блокируем чат осиротевшей строкой
            else:
                await effects.react_msg(msg, "👀")  # «ой, что-то упало»
        if orphaned:
            for drop_id in orphaned:
                await repo.delete_loot(session, drop_id)
            await session.commit()
