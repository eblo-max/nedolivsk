"""Фоновые уведомления: работники вернулись с вылазки."""

import asyncio
import html
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import func, select

from bot import announce, autoclean, effects, panels, texts
from bot.db import repo
from bot.db.base import session_factory
from bot.handlers import common
from bot.sender import deliver
from bot.db.models import Player, Tavern
from bot.game import auction as auctionmod
from bot.game import balance
from bot.game import economy
from bot.game import city as citymod
from bot.game import loot
from bot.game import market as marketmod
from bot.game import npc
from bot.game import raid as raidmod
from bot.game import invasion as invmod
from bot.game import inventory
from bot.game import season, story_engine, story_state
from bot.game import world as wld
from bot.keyboards.inline import (
    bonus_push_kb, buildings_notify_kb, claim_kb, craft_claim_kb, hunt_cta_kb,
    idle_nudge_kb, invasion_announce_kb, loot_kb, onboard_nudge_kb,
    raid_gather_kb, raid_kb, story_push_kb,
)

CHECK_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


def _apply_trophy(player, drop: dict) -> str:
    """Применить редкий трофей победителю и вернуть человекочитаемую строку."""
    if drop.get("kind") == "gold":
        player.gold += int(drop["qty"])
        economy.record(player, "invasion", int(drop["qty"]))
        return f"{drop['qty']} 🪙"
    if drop.get("kind") == "res":
        inventory.add(player, drop["res"], int(drop["qty"]))
        return f"{invmod.res_label(drop['res'])} ×{drop['qty']}"
    return "загадочный трофей"


async def _apply_invasion(session, inv, plan: dict) -> None:
    """Применить исход ивента «Орда орков»: награды/штраф участникам + личные сводки.
    Капы: золото не уходит в минус, репутация не ниже 0. Идемпотентность — снаружи
    (резолв только при status=='battle' под локом строки ивента)."""
    won = plan["won"]
    trophy = plan.get("trophy")
    for pid, dgold in plan["gold"].items():
        player = await session.get(Player, int(pid), with_for_update=True)
        if player is None:
            continue
        # репутацию (молву) ведём И на игроке, И на таверне (видимая — с таверны, как в охоте)
        tav = (await session.execute(
            select(Tavern).where(Tavern.player_id == int(pid)).with_for_update())
        ).scalar_one_or_none()
        drep = int(plan["rep"].get(pid, 0))
        if won:
            player.gold += int(dgold)
            economy.record(player, "invasion", int(dgold))
            player.reputation = (player.reputation or 0) + drep
            if tav is not None:
                tav.reputation = (tav.reputation or 0) + drep
            haul = plan["res"].get(pid) or {}
            for res, qty in haul.items():
                inventory.add(player, res, int(qty))
            tline = None
            if trophy and int(trophy["pid"]) == int(pid):
                tline = _apply_trophy(player, trophy["drop"])
            repo.queue_notify(session, int(pid),
                              texts.invasion_reward_dm(True, int(dgold), drep, haul, tline))
        else:
            _before = player.gold
            player.gold = max(0, player.gold + int(dgold))     # не в минус
            economy.record(player, "invasion", player.gold - _before)
            player.reputation = max(0, (player.reputation or 0) + drep)
            if tav is not None:
                tav.reputation = max(0, (tav.reputation or 0) + drep)
            repo.queue_notify(session, int(pid),
                              texts.invasion_reward_dm(False, int(dgold), drep))


def _has_webapp(markup) -> bool:
    """Есть ли в клавиатуре web_app-кнопка (она работает ТОЛЬКО в личке, не в группе)."""
    for row in getattr(markup, "inline_keyboard", []) or []:
        for b in row:
            if getattr(b, "web_app", None):
                return True
    return False


async def _notify(bot: Bot, player: Player, text: str, markup) -> None:
    """Уведомление игроку. Если известен «домашний» чат (заходил через «гг») —
    постим туда с упоминанием и регистрируем сообщение как панель игрока, чтобы
    к кнопке пускало только владельца (PanelGuard). Иначе или при сбое — в личку.
    Если в клавиатуре есть web_app-кнопка (мини-апп) — сразу в личку (в группе нельзя)."""
    if player.chat_id is not None and not _has_webapp(markup):
        name = html.escape(player.first_name or "Хозяин")
        body = f'<a href="tg://user?id={player.id}">{name}</a>!\n{text}'
        msg = await deliver(
            lambda: bot.send_message(player.chat_id, body, reply_markup=markup),
            what=f"увед→чат{player.chat_id}")
        if msg is not None:
            panels.claim(msg, player.id)  # кнопку жмёт только владелец
            # Личное уведомление в общий чат гасим через 5 мин (анти-флуд): клик
            # владельца продлит его как обычную панель (PanelGuard).
            autoclean.schedule_message(msg, after=300)
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
            who = npc.label(s.npc) if s.npc else "Гость"
            outbox.append((player, f"🚪 {who} ждёт тебя у стойки — загляни в таверну.", story_push_kb()))

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

        # Онбординг-дожим: завёл аккаунт, но кабак так и не открыл — подтолкнуть
        # ОДИН раз (флаг onboard_nudged). Только тех, кто ещё в досягаемости лички.
        onboard_nudges: list[tuple[int, bool]] = []
        res_ob = await session.execute(
            select(Player).where(
                Player.onboard_nudged.is_(False),
                Player.created_at < now - timedelta(minutes=balance.ONBOARD_NUDGE_AFTER_MIN),
                Player.last_seen_at.is_not(None),
                Player.last_seen_at >= now - timedelta(days=2),
                Player.id.not_in(select(Tavern.player_id)),
            ).with_for_update(skip_locked=True)
        )
        for player in res_ob.scalars().all():
            player.onboard_nudged = True
            onboard_nudges.append((player.id, player.referred_by is not None))

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

        # Рейд-босс: жизненный цикл. Сбор → битва (HP под явку + пинг) → уход.
        # Правки сообщений в чатах копим и шлём ПОСЛЕ коммита (не под локами).
        # (messages, text, markup|None, is_video) — видео правим подписью, текст текстом
        raid_edits: list[tuple[dict, str, object, bool]] = []
        from bot import images as imgmod
        live_raids = await repo.live_raids(session)
        for boss in live_raids:
            spec = raidmod.BOSSES.get(boss.boss_key)
            if spec is None:
                continue
            is_vid = bool(spec.video and imgmod.named_video(spec.video))
            if boss.status == "gathering":
                if now >= (boss.gather_until or now):       # сбор окончен
                    fighters = raidmod.registered_count(boss)
                    if fighters == 0:                        # никто не пришёл
                        boss.status = "expired"
                        raid_edits.append((dict(boss.messages or {}),
                                           texts.raid_no_show(boss), None, is_vid))
                    else:                                    # старт битвы
                        boss.max_hp = boss.hp = raidmod.boss_start_hp(boss)
                        boss.status = "active"
                        boss.ends_at = raidmod.fight_until(now)
                        raid_edits.append((dict(boss.messages or {}),
                                           texts.raid_screen(boss), raid_kb(boss.id),
                                           is_vid))
                        for pid in list((boss.contributions or {}).keys()):
                            repo.queue_notify(session, int(pid), texts.raid_fight_ping())
                else:                                        # идёт сбор — отсчёт
                    raid_edits.append((dict(boss.messages or {}),
                                       texts.raid_gather_screen(boss),
                                       raid_gather_kb(boss.id), is_vid))
            elif boss.status == "active":
                if now >= (boss.ends_at or now):
                    boss.status = "expired"                  # не добили — ушёл
                    raid_edits.append((dict(boss.messages or {}),
                                       texts.raid_expired(boss), None, is_vid))
                else:                                        # идёт бой: ход босса
                    events = raidmod.cast_tick(boss, now)      # фазы/щит/проклятье/призыв/рык/реген
                    if events:   # есть новость — перерисуем экран боя
                        raid_edits.append((dict(boss.messages or {}),
                                           texts.raid_screen(boss), raid_kb(boss.id),
                                           is_vid))
                        push = texts.raid_cast_push(boss, events)   # «громкие» касты — в личку бойцам
                        if push:
                            for pid in list((boss.contributions or {}).keys()):
                                repo.queue_notify(session, int(pid), push)
        # Кэш для кнопки «Рейд-босс» в меню: какой босс ещё жив (или None).
        raidmod.set_active(next(
            (b.id for b in live_raids if b.status in ("gathering", "active")), None))

        # Ивент «Орда орков»: сбор → битва → резолв (раздача/штраф). Правки анонсов
        # копим (messages, text, markup|None) и шлём ПОСЛЕ коммита, как у рейда.
        inv_edits: list[tuple[dict, str, object]] = []
        invs = await repo.live_invasions(session)
        for inv in invs:
            if inv.status == "gathering":
                if now >= (inv.gather_until or now):
                    if invmod.registered_count(inv) == 0:        # никто не пришёл
                        inv.status = "lost"
                        inv.result = {"won": False, "n": 0, "rounds": 0,
                                      "orc_hp_left": 0, "orc_hp_max": 0, "top": []}
                        world.invasion_next_at = invmod.cooldown_until(now)
                        inv_edits.append((dict(inv.messages or {}),
                                          texts.invasion_result_chat(inv), None))
                    else:                                        # войска выступили
                        inv.status = "battle"
                        # длина боя = реальное число раундов → resolve_at точно к финалу
                        parts = [dict(r, pid=int(pid))
                                 for pid, r in (inv.registered or {}).items()]
                        bsec = invmod.battle_secs_for(invmod.simulate(
                            parts, seed=inv.id, escal=invmod.escal_of(inv))["rounds"])
                        gu = inv.gather_until
                        if gu.tzinfo is None:
                            gu = gu.replace(tzinfo=timezone.utc)
                        inv.resolve_at = gu + timedelta(seconds=invmod.MARCH_SECONDS + bsec)
                        inv_edits.append((dict(inv.messages or {}),
                                          texts.invasion_battle_screen(inv), None))
                # пока идёт сбор — анонс НЕ правим (отсчёт/состав живут на карте);
                # сообщение в чате остаётся статичным призывом до старта битвы.
            elif inv.status == "battle":
                if now >= (inv.resolve_at or now):               # время исхода — СИМУЛЯЦИЯ
                    parts = [dict(r, pid=int(pid))
                             for pid, r in (inv.registered or {}).items()]
                    sim = invmod.simulate(parts, seed=inv.id, escal=invmod.escal_of(inv))
                    plan = invmod.settle(inv, sim)
                    await _apply_invasion(session, inv, plan)
                    if sim["won"]:        # победа мира → следующая орда сильнее
                        world.orc_wins = int(getattr(world, "orc_wins", 0) or 0) + 1
                    inv.result = {"won": sim["won"], "n": sim["n"], "rounds": sim["rounds"],
                                  "orc_hp_left": sim["orc_hp_left"],
                                  "orc_hp_max": sim["orc_hp_max"],
                                  "top": [[nm, role, dmg] for _p, nm, role, dmg
                                          in invmod.top_contributors(inv, sim)],
                                  "report": invmod.build_report(inv, sim, plan)}
                    inv.status = "won" if sim["won"] else "lost"
                    world.invasion_next_at = invmod.cooldown_until(now)
                    inv_edits.append((dict(inv.messages or {}),
                                      texts.invasion_result_chat(inv), None))
        # Кэш «идёт сбор» для кнопки «в строй» в меню таверны (или None — сбор кончился).
        invmod.set_gathering(next((iv.id for iv in invs if iv.status == "gathering"), None))

        # Телега за зерном вернулась — пуш в личку (один раз на вылазку, флаг mill_notified).
        from bot.game import mill as millmod
        mill_back = (await session.execute(
            select(Player).where(
                Player.mill_grain > 0,
                Player.mill_notified.is_(False),
                Player.mill_run_at.is_not(None),
                Player.mill_run_at <= now - timedelta(seconds=millmod.TRIP_SECONDS),
            ))).scalars().all()
        for pl in mill_back:
            repo.queue_notify(session, pl.id, texts.mill_back_dm(int(pl.mill_grain or 0)))
            pl.mill_notified = True

        city_events: list[tuple[int, str]] = []  # (chat_id, текст анонса)
        world_news: list[str] = []  # глобальные вести для DM-дайджеста одиночкам

        # ЕДИНЫЙ рынок: масштаб (число активных чатов) для адаптивных порогов цены,
        # затем впитывание перекоса + редкий пульс — двигает цену всего мира сразу.
        # Молва о скачке цен идёт во ВСЕ чаты (это мировая новость).
        world.market_scale = max(1, await repo.count_known_chats(session))
        marketmod.decay(world, now)
        if random.random() < balance.MARKET_PULSE_CHANCE:
            cit = npc.random_pulser()
            good, delta, _verb = cit.pulse
            marketmod.nudge(world, good, delta)
            world_news.append(texts.market_pulse_announce(cit))
            for cid in await repo.all_chat_ids(session):
                city_events.append((cid, texts.market_pulse_announce(cit)))
                await repo.add_chronicle(session, cid, texts.market_pulse_chron(cit))
        # Глобальные события — и в DM-дайджест одиночкам (сезон/праздник/ярмарка).
        if season_changed:
            world_news.append(texts.season_announce(season.SEASONS[cur_season]))
        if holiday_new:
            world_news.append(texts.holiday_announce(hol))
        if fair_event == "open":
            world_news.append("🎪 <b>Ярмарка открылась!</b> Спрос на товары взлетел — "
                              "сбывай, пока берут.")

        # Мировое событие (погода/экономика): одно за раз, ~1/сутки. Чистая логика
        # цикла — в worldevent.advance (мутирует world); старт → анонс в чаты+личку.
        from bot.game import worldevent
        started = worldevent.advance(world, now)
        # анонс события шлём ПОСЛЕ коммита через announce.world_event (чаты + ВСЕ
        # активные одиночки, не только подписчики дайджеста).
        we_text = (texts.worldevent_announce(started, world.event_good)
                   if started is not None else None)

        # Биржевая сводка: раз в N минут — свежие лоты во все чаты (биржа глобальна).
        # Берём ордера с прошлой сводки, ещё живые на стакане; мгновенно сведённые
        # уже удалены и не попадут. Текст копим — шлём ПОСЛЕ коммита.
        bourse_news_text = None
        bdelta = timedelta(minutes=balance.BOURSE_DIGEST_MINUTES)
        blast = world.bourse_announced_at
        if blast is not None and blast.tzinfo is None:
            blast = blast.replace(tzinfo=timezone.utc)
        if blast is None or now - blast >= bdelta:
            orders = await repo.bourse_orders_since(session, blast or (now - bdelta))
            world.bourse_announced_at = now
            agg: dict[str, dict[str, list]] = {"sell": {}, "buy": {}}
            for o in orders:
                side = o.side if o.side in ("sell", "buy") else "sell"
                cur = agg[side].get(o.good)
                if cur is None:
                    agg[side][o.good] = [o.qty, o.unit_price]
                else:
                    cur[0] += o.qty
                    cur[1] = (min(cur[1], o.unit_price) if side == "sell"
                              else max(cur[1], o.unit_price))
            sells = [(g, v[0], v[1]) for g, v in list(agg["sell"].items())[:6]]
            buys = [(g, v[0], v[1]) for g, v in list(agg["buy"].items())[:6]]
            if sells or buys:
                bourse_news_text = texts.bourse_news(sells, buys)
                # Личечным игрокам (без домашнего чата), кто СЕЙЧАС за ботом, —
                # сводку в личку. Окно ≈ интервал дайджеста: пока играешь —
                # видишь, ушёл — не заваливаем (пинги не копятся в простое).
                online = now - timedelta(minutes=balance.BOURSE_DIGEST_MINUTES + 5)
                dm_ids = [r[0] for r in (await session.execute(
                    select(Player.id).where(Player.chat_id.is_(None),
                                            Player.last_seen_at >= online))).all()]
                for uid in dm_ids:
                    repo.queue_notify(session, uid, bourse_news_text)

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
        # Подкидыш одиночкам (без группы, активным за сутки) — персонально в ЛС.
        dm_loot_to_post: list[tuple[int, int]] = []
        solo_cut = now - timedelta(days=1)
        solo_ids = [r[0] for r in (await session.execute(
            select(Player.id).where(Player.chat_id.is_(None),
                                    Player.last_seen_at >= solo_cut))).all()]
        for uid in solo_ids:
            if random.random() >= balance.LOOT_DROP_CHANCE:
                continue
            if await repo.has_active_loot(session, uid):
                continue
            drop = await repo.create_loot(session, uid)
            dm_loot_to_post.append((uid, drop.id))

        # Сброс новых file_id медиа в БД (переживут деплой → без повторной загрузки).
        pending = common.pending_file_ids()
        if pending is not None:
            world.media_ids = pending
            common.mark_file_ids_saved()

        await session.commit()
        wld.refresh_cache(world)  # синхронизируем кэш ярмарки для экранов/дохода
        worldevent.set_active(world.event_kind, world.event_until,
                              world.event_good)  # кэш мир-события
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

        # Онбординг-дожим — строго в личку, один раз (флаг уже зафиксирован).
        for pid, referred in onboard_nudges:
            await deliver(
                lambda p=pid, r=referred: bot.send_message(
                    p, texts.onboard_nudge(r), reply_markup=onboard_nudge_kb()),
                what=f"онбординг→{pid}")

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
                if n.photo:        # рассылка с картинкой: фото + подпись
                    await deliver(
                        lambda nn=n: bot.send_photo(
                            nn.user_id, nn.photo, caption=nn.text or None),
                        what=f"outbox-photo→{n.user_id}")
                else:
                    await deliver(lambda nn=n: bot.send_message(nn.user_id, nn.text),
                                  what=f"outbox→{n.user_id}")
            await repo.delete_notifications(session, [n.id for n in notes])
            await session.commit()

        # Мировое событие (погода/экономика) — анонс в чаты + ЛС всем одиночкам.
        if we_text:
            await announce.world_event(bot, session, we_text, now)

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
        # Рейд-босс: правка анонса в чатах (отсчёт сбора / старт битвы / уход).
        # Видео-анонс правим подписью, текстовый — текстом (edit_raid_announce).
        from bot.handlers.raid import edit_raid_announce
        for messages, rtext, rmarkup, is_vid in raid_edits:
            for cid_s, mid in messages.items():
                await deliver(
                    lambda c=int(cid_s), m=mid, t=rtext, mk=rmarkup, v=is_vid:
                    edit_raid_announce(bot, c, m, v, t, mk),
                    what=f"raid-edit→{cid_s}")
        # Ивент «Орда орков»: правка анонса (отсчёт сбора → битва → итог).
        from bot.handlers.invasion import edit_invasion_announce
        for messages, itext, imarkup in inv_edits:
            for cid_s, mid in messages.items():
                await deliver(
                    lambda c=int(cid_s), m=mid, t=itext, mk=imarkup:
                    edit_invasion_announce(bot, c, m, t, mk),
                    what=f"inv-edit→{cid_s}")

        # Анонсы городских ситуаций (после коммита).
        for chat_id, text in city_events:
            msg = await deliver(
                lambda cid=chat_id, t=text: bot.send_message(cid, t),
                what=f"ситуация→{chat_id}")
            await effects.react_msg(msg, "🔥")  # «жизнь» городу
        # Биржевая сводка (после коммита): свежие лоты — во все чаты.
        # Гасим через 10 мин (анти-флуд): следующая сводка всё равно свежее.
        if bourse_news_text:
            for chat_id in await repo.all_chat_ids(session):
                msg = await deliver(
                    lambda cid=chat_id, t=bourse_news_text: bot.send_message(cid, t),
                    what=f"биржа→{chat_id}")
                autoclean.schedule_message(msg, after=600)
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
                # Не подобрали за срок жизни — гасим (мёртвая кнопка не висит).
                autoclean.schedule_message(
                    msg, after=balance.LOOT_EXPIRE_MINUTES * 60)
        # Подкидыш одиночкам — в их ЛС (на пикапе удаляется, иначе гаснет по сроку).
        for uid, drop_id in dm_loot_to_post:
            drop_text = texts.loot_drop(loot.flavor())
            msg = await deliver(
                lambda u=uid, did=drop_id, t=drop_text: bot.send_message(
                    u, t, reply_markup=loot_kb(did)),
                what=f"подкидыш-лс→{uid}")
            if msg is None:
                orphaned.append(drop_id)
            else:
                autoclean.schedule(bot, uid, msg.message_id,
                                   after=balance.LOOT_EXPIRE_MINUTES * 60)
        # Вести мира — в ЛС одиночкам, кто включил (активным за неделю), одним письмом.
        if world_news:
            news_cut = now - timedelta(days=7)
            news_ids = [r[0] for r in (await session.execute(
                select(Player.id).where(
                    Player.chat_id.is_(None), Player.dm_news.is_(True),
                    Player.last_seen_at >= news_cut))).all()]
            digest = "🌍 <b>ВЕСТИ ИЗ НЕДОЛИВСКА</b>\n\n" + "\n\n".join(world_news)
            for uid in news_ids:
                await deliver(lambda u=uid, t=digest: bot.send_message(u, t),
                              what=f"вести-лс→{uid}")
        if orphaned:
            for drop_id in orphaned:
                await repo.delete_loot(session, drop_id)
            await session.commit()
