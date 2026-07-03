import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    Chronicle, CityState, Invasion, KnownChat, LogEntry, LootDrop, MarketOrder,
    Notification, NotifFeed, Player, RaidBoss, RankSnap, Tavern, WorldState,
)
from bot.game import balance, economy


async def get_or_create_world(session: AsyncSession) -> WorldState:
    """Единственная строка состояния мира (id=1)."""
    world = await session.get(WorldState, 1)
    if world is None:
        world = WorldState(id=1)
        session.add(world)
        await session.flush()
    return world


async def remember_chat(
    session: AsyncSession, chat_id: int, title: str | None
) -> None:
    """Запомнить общий чат как адресата анонсов мировых событий."""
    chat = await session.get(KnownChat, chat_id)
    if chat is None:
        session.add(KnownChat(chat_id=chat_id, title=title))
    elif title and chat.title != title:
        chat.title = title


async def forget_chat(session: AsyncSession, chat_id: int) -> None:
    """Забыть чат (бота выгнали/вышел) — чтобы не слать в пустоту."""
    chat = await session.get(KnownChat, chat_id)
    if chat is not None:
        await session.delete(chat)


async def all_chat_ids(session: AsyncSession) -> list[int]:
    """Все известные общие чаты — куда слать анонсы."""
    result = await session.execute(select(KnownChat.chat_id))
    return [row[0] for row in result.all()]


async def count_known_chats(session: AsyncSession) -> int:
    """Число известных общих чатов — масштаб единого рынка (адаптивные пороги)."""
    return await session.scalar(select(func.count(KnownChat.chat_id))) or 0


async def bourse_orders_since(session: AsyncSession, since, limit: int = 200):
    """Ордера биржи, созданные позже `since` и ещё живые на стакане (для сводки
    в чаты). Мгновенно заматчившиеся уже удалены — в выборку не попадут."""
    return list((await session.execute(
        select(MarketOrder).where(MarketOrder.created_at > since)
        .order_by(MarketOrder.created_at).limit(limit)
    )).scalars().all())


async def lock_players(session: AsyncSession, ids: list[int]) -> None:
    """Захватить строки игроков в ЕДИНОМ порядке (по возрастанию id) — анти-дедлок
    при сведении биржи (золотое правило: локи в консистентном порядке по ключу)."""
    if not ids:
        return
    await session.execute(
        select(Player.id).where(Player.id.in_(sorted(set(ids))))
        .order_by(Player.id).with_for_update()
    )


# ── Рейд-босс (глобальный, один активный) ───────────────────────────────────
async def get_active_raid(
    session: AsyncSession, *, lock: bool = False
) -> RaidBoss | None:
    """Живой босс (фаза сбора ИЛИ битвы). Один на весь мир."""
    stmt = (select(RaidBoss)
            .where(RaidBoss.status.in_(("gathering", "active")))
            .order_by(RaidBoss.id.desc()).limit(1))   # детерминизм: всегда самый свежий
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def live_raids(session: AsyncSession) -> list[RaidBoss]:
    """Все живые боссы (для тика жизненного цикла в нотифаере)."""
    return list((await session.execute(
        select(RaidBoss).where(RaidBoss.status.in_(("gathering", "active")))
        .with_for_update(skip_locked=True))).scalars().all())


async def get_raid(
    session: AsyncSession, raid_id: int, *, lock: bool = False
) -> RaidBoss | None:
    return await session.get(RaidBoss, raid_id, with_for_update=lock)


async def latest_raid(session: AsyncSession) -> RaidBoss | None:
    """Самый свежий босс (любой статус) — для пост-боевой сводки на экране рейда
    (победа/уход) тем, кто не добил сам. Аналог latest_invasion."""
    return (await session.execute(
        select(RaidBoss).order_by(RaidBoss.id.desc()).limit(1))).scalar_one_or_none()


async def add_raid_panel(
    session: AsyncSession, boss_id: int, key: str, message_id: int
) -> None:
    """Атомарно вписать личную панель игрока в messages босса — ТОЛЬКО поле messages,
    через jsonb-слияние. НЕ читаем-перезаписываем босса целиком: иначе устаревший
    снимок contributions из этой сессии затёр бы вклады бойцов (потеря урона)."""
    await session.execute(
        text("UPDATE raid_boss SET messages = COALESCE(messages, '{}'::jsonb) "
             "|| jsonb_build_object(:k, to_jsonb(CAST(:m AS integer))) "
             "WHERE id = :id AND status IN ('gathering', 'active')"),
        {"k": str(key), "m": int(message_id), "id": int(boss_id)},
    )


def create_raid(session: AsyncSession, boss_key: str, gather_until) -> RaidBoss:
    """Создать босса в фазе СБОРА. HP/ends_at ставятся при старте битвы."""
    raid = RaidBoss(boss_key=boss_key, status="gathering", gather_until=gather_until)
    session.add(raid)
    return raid


# ── Ивент «Орда орков» (invasion) ──────────────────────────────────────────
async def get_active_invasion(
    session: AsyncSession, *, lock: bool = False
) -> Invasion | None:
    """Живой ивент (сбор ИЛИ бой). Один на весь мир."""
    stmt = (select(Invasion)
            .where(Invasion.status.in_(("gathering", "battle")))
            .order_by(Invasion.id.desc()).limit(1))
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def live_invasions(session: AsyncSession) -> list[Invasion]:
    """Все живые ивенты — для тика жизненного цикла (обычно ≤1)."""
    return list((await session.execute(
        select(Invasion).where(Invasion.status.in_(("gathering", "battle")))
        .with_for_update(skip_locked=True))).scalars().all())


async def latest_invasion(session: AsyncSession) -> Invasion | None:
    """Самый свежий ивент (любой статус) — для показа сводки боя на карте."""
    return (await session.execute(
        select(Invasion).order_by(Invasion.id.desc()).limit(1))).scalar_one_or_none()


def create_invasion(session: AsyncSession, *, sprite: int, threshold: int,
                    gather_until, resolve_at) -> Invasion:
    """Создать ивент в фазе СБОРА (порог орды — снимок при спавне)."""
    inv = Invasion(sprite=sprite, threshold=threshold, status="gathering",
                   gather_until=gather_until, resolve_at=resolve_at)
    session.add(inv)
    return inv


async def invasion_register(
    session: AsyncSession, inv_id: int, player_id: int, record: dict
) -> bool:
    """Атомарно вписать бойца в реестр ивента — ТОЛЬКО поле registered, jsonb-слиянием
    (как add_raid_panel: не читаем-перезаписываем строку целиком, иначе устаревший
    снимок затёр бы чужие записи). Пишем лишь в фазе СБОРА и если ещё не записан.
    Возвращает True, если запись прошла (иначе уже записан/сбор окончен)."""
    res = await session.execute(
        text("UPDATE invasion SET registered = COALESCE(registered, '{}'::jsonb) "
             "|| jsonb_build_object(:pid, CAST(:rec AS jsonb)) "
             "WHERE id = :id AND status = 'gathering' "
             "AND NOT jsonb_exists(COALESCE(registered, '{}'::jsonb), :pid)"),
        {"pid": str(player_id), "rec": json.dumps(record), "id": int(inv_id)},
    )
    return (res.rowcount or 0) > 0


async def world_might_sum(session: AsyncSession) -> int:
    """Суммарная военная мощь всех таверн мира (для порога орды при спавне).
    Считаем в SQL по той же формуле, что invasion.tavern_might."""
    from bot.game import invasion as inv
    stmt = select(func.coalesce(func.sum(
        inv.MIGHT_BASE
        + func.greatest(Tavern.level, 1) * inv.MIGHT_PER_LEVEL
        + func.coalesce(func.jsonb_array_length(Tavern.buildings), 0) * inv.MIGHT_PER_BUILDING
    ), 0))
    return int((await session.execute(stmt)).scalar_one() or 0)


# ЕДИНЫЙ МИР: вся община (город, фракции, настроение, ситуации, летопись) —
# одна на всех, в городе-0. chat_id игрока/чата больше НЕ определяет общину (он
# остался только маршрутом уведомлений и признаком «окна» — куда транслировать
# мировые вести). У реальных чатов Telegram id отрицательный, 0 не бывает.
GLOBAL_CITY_ID = 0


def player_city_id(player) -> int:      # noqa: ARG001 — единый мир: община у всех общая
    """Город игрока — всегда единый мировой (община глобальна)."""
    return GLOBAL_CITY_ID


async def get_or_create_city(
    session: AsyncSession, chat_id: int | None, *, lock: bool = False
) -> CityState:
    """Состояние живого города (ленивое создание). chat_id=None/0 → мировой город.
    lock=True блокирует строку до конца транзакции — для безопасной правки силы
    фракций при одновременных событиях."""
    chat_id = chat_id or GLOBAL_CITY_ID          # None/0 → мировой город
    city = await session.get(CityState, chat_id, with_for_update=lock)
    if city is None:
        city = CityState(chat_id=chat_id)
        session.add(city)
        await session.flush()
    return city


async def get_world_city(session: AsyncSession, *, lock: bool = False) -> CityState:
    """ЕДИНЫЙ мировой город — одна община на всех (личка и чаты вместе)."""
    return await get_or_create_city(session, GLOBAL_CITY_ID, lock=lock)


async def all_cities(session: AsyncSession, *, lock: bool = False):
    """Все города (по чатам) — для тика симуляции фракций."""
    stmt = select(CityState)
    if lock:
        stmt = stmt.with_for_update(skip_locked=True)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_chronicle(
    session: AsyncSession, chat_id: int, text: str, keep: int = 60
) -> None:
    """Запись в летопись города (держим последние `keep` записей на чат)."""
    session.add(Chronicle(chat_id=chat_id, text=text[:256]))
    await session.flush()
    threshold = (await session.execute(
        select(Chronicle.id)
        .where(Chronicle.chat_id == chat_id)
        .order_by(Chronicle.id.desc())
        .limit(1).offset(keep)
    )).scalar()
    if threshold is not None:  # есть что подрезать
        await session.execute(
            delete(Chronicle).where(
                Chronicle.chat_id == chat_id, Chronicle.id <= threshold
            )
        )


async def create_loot(session: AsyncSession, chat_id: int) -> LootDrop:
    """Создать подкидыш в чате (id нужен для callback кнопки «Поднять»)."""
    drop = LootDrop(chat_id=chat_id)
    session.add(drop)
    await session.flush()
    return drop


async def claim_loot(session: AsyncSession, drop_id: int, user_id: int) -> bool:
    """Атомарно застолбить подкидыш за первым нажавшим. True — этот игрок успел."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=balance.LOOT_EXPIRE_MINUTES)
    result = await session.execute(
        update(LootDrop)
        .where(LootDrop.id == drop_id,
               LootDrop.claimed_by.is_(None),
               LootDrop.created_at >= cutoff)
        .values(claimed_by=user_id)
    )
    return result.rowcount == 1


async def has_active_loot(session: AsyncSession, chat_id: int) -> bool:
    """Есть ли в чате неподобранный, ещё не сгнивший подкидыш (анти-навал)."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=balance.LOOT_EXPIRE_MINUTES)
    result = await session.execute(
        select(LootDrop.id).where(
            LootDrop.chat_id == chat_id,
            LootDrop.claimed_by.is_(None),
            LootDrop.created_at >= cutoff,
        ).limit(1)
    )
    return result.first() is not None


async def delete_loot(session: AsyncSession, drop_id: int) -> None:
    """Убрать подкидыш (например, если сообщение не доставилось — не блокируем чат)."""
    await session.execute(delete(LootDrop).where(LootDrop.id == drop_id))


async def cleanup_loot(session: AsyncSession) -> None:
    """Подчистить старые подкидыши (день и старше), чтобы таблица не пухла."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    await session.execute(delete(LootDrop).where(LootDrop.created_at < cutoff))


def add_log(session: AsyncSession, kind: str, actor_id: int, text: str) -> None:
    """Записать событие в журнал (player|admin). Коммит — снаружи (middleware).
    Не флашим: попадёт в общий коммит хендлера; при откате — пропадёт вместе с ним."""
    session.add(LogEntry(kind=kind, actor_id=actor_id, text=text[:512]))


async def recent_logs(
    session: AsyncSession, *, kind: str | None = None, actor_id: int | None = None,
    limit: int = 10, offset: int = 0,
) -> list[LogEntry]:
    """Свежие записи журнала (новые сверху), с фильтром по виду/актору."""
    stmt = select(LogEntry)
    if kind:
        stmt = stmt.where(LogEntry.kind == kind)
    if actor_id is not None:
        stmt = stmt.where(LogEntry.actor_id == actor_id)
    stmt = stmt.order_by(LogEntry.id.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_logs(
    session: AsyncSession, *, kind: str | None = None, actor_id: int | None = None,
) -> int:
    stmt = select(func.count(LogEntry.id))
    if kind:
        stmt = stmt.where(LogEntry.kind == kind)
    if actor_id is not None:
        stmt = stmt.where(LogEntry.actor_id == actor_id)
    return await session.scalar(stmt) or 0


async def cleanup_logs(session: AsyncSession, keep: int = 3000) -> None:
    """Держим последние `keep` записей журнала, чтобы таблица не пухла."""
    threshold = (await session.execute(
        select(LogEntry.id).order_by(LogEntry.id.desc()).limit(1).offset(keep)
    )).scalar()
    if threshold is not None:
        await session.execute(delete(LogEntry).where(LogEntry.id <= threshold))


# ── Отложенные уведомления (outbox) ──────────────────────────────────────
def queue_notify(session: AsyncSession, user_id: int, text: str,
                 photo: str | None = None, kind: str = "") -> None:
    """Положить личку игроку в очередь (атомарно со сделкой; шлёт нотифаер).
    photo — file_id картинки: тогда уйдёт фото с подписью (text).
    Зеркалим в персистентную ленту мини-аппа; kind — тип вести (иконка/переход)."""
    session.add(Notification(user_id=user_id, text=text[:1024], photo=photo,
                             kind=kind[:32]))
    feed_push(session, user_id, text, kind=kind)


# ── Снимки рангов для тренда доски почёта (переживают деплой) ─────────────
async def rank_snaps_load(session: AsyncSession, since_ts: float,
                          limit: int = 40) -> list[tuple[float, dict]]:
    """Свежие снимки рангов (старые→новые) для гидрации тренда после рестарта."""
    rows = (await session.execute(
        select(RankSnap.ts, RankSnap.data)
        .where(RankSnap.ts >= since_ts)
        .order_by(RankSnap.ts.desc()).limit(limit))).all()
    return [(ts, data) for ts, data in reversed(rows)]


async def rank_snap_add(session: AsyncSession, ts: float, data: dict,
                        prune_before: float) -> None:
    """Записать снимок рангов и подчистить устаревшие (старше окна тренда)."""
    session.add(RankSnap(ts=ts, data=data))
    await session.execute(delete(RankSnap).where(RankSnap.ts < prune_before))


# ── Лента уведомлений мини-аппа (зеркало ВСЕХ DM) ─────────────────────────
def feed_push(session: AsyncSession, user_id: int, text: str,
              kind: str = "") -> None:
    """Добавить уведомление в персистентную ленту игрока (раздел «Уведомления»)."""
    if not text or user_id < 0:      # id<0 = группа (эхо в чат) — не в личную ленту
        return
    session.add(NotifFeed(user_id=user_id, text=text[:1024], kind=kind[:32]))


async def feed_list(session: AsyncSession, user_id: int,
                    limit: int = 60) -> list[NotifFeed]:
    return list((await session.execute(
        select(NotifFeed).where(NotifFeed.user_id == user_id)
        .order_by(NotifFeed.id.desc()).limit(limit))).scalars().all())


async def feed_unread(session: AsyncSession, user_id: int) -> int:
    return await session.scalar(
        select(func.count(NotifFeed.id)).where(
            NotifFeed.user_id == user_id, NotifFeed.read.is_(False))) or 0


async def feed_mark_read(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(NotifFeed).where(
            NotifFeed.user_id == user_id, NotifFeed.read.is_(False)
        ).values(read=True))
    # игрок заглянул в ленту → разрешаем следующий тизер по будущей пачке
    await session.execute(
        update(Player).where(Player.id == user_id).values(notif_pinged=False))


async def feed_ping_targets(session: AsyncSession, limit: int = 300) -> list[int]:
    """Кому слать тизер «весть в таверну»: есть непрочитанные И ещё не пинговали.
    Сразу ставим флаг notif_pinged (один тизер на пачку — анти-спам)."""
    # Окно активности ДОЛЖНО покрывать троттл touch_seen (core._SEEN_EVERY=5 мин):
    # иначе активный игрок с last_seen, обновляемым раз в 5 мин, попадёт в окно
    # 3–5 мин как «неактивный» и получит тизер, сидя в игре. 6 мин = 5 + буфер.
    active_cut = datetime.now(timezone.utc) - timedelta(minutes=6)
    rows = await session.execute(
        select(Player.id).where(
            Player.notif_pinged.is_(False),
            # кто в игре ПРЯМО СЕЙЧАС — не пингуем (видит бейдж сам); флаг не
            # ставим → пинганём после выхода, если так и не прочитает
            (Player.last_seen_at.is_(None)) | (Player.last_seen_at < active_cut),
            Player.id.in_(
                select(NotifFeed.user_id).where(NotifFeed.read.is_(False)))
        ).limit(limit))
    ids = [r[0] for r in rows.all()]
    if ids:
        await session.execute(
            update(Player).where(Player.id.in_(ids)).values(notif_pinged=True))
    return ids


async def feed_mark_read_kind(session: AsyncSession, user_id: int,
                              kinds: list[str]) -> None:
    """Погасить вести типов kinds действием в механике: забрал постройку —
    весть «достроена» больше не «непрочитанная» (и бейдж честный)."""
    if not kinds:
        return
    await session.execute(
        update(NotifFeed)
        .where(NotifFeed.user_id == user_id,
               NotifFeed.read.is_(False),
               NotifFeed.kind.in_(kinds))
        .values(read=True))


async def feed_prune(session: AsyncSession, days: int = 45) -> None:
    """Чистим старые записи ленты (по возрасту) — таблица не растёт бесконечно."""
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    await session.execute(delete(NotifFeed).where(NotifFeed.created_at < cut))


async def pop_notifications(
    session: AsyncSession, limit: int = 50
) -> list[Notification]:
    return list((await session.execute(
        select(Notification).order_by(Notification.id).limit(limit)
    )).scalars().all())


async def delete_notifications(session: AsyncSession, ids: list[int]) -> None:
    if ids:
        await session.execute(
            delete(Notification).where(Notification.id.in_(ids)))


# ── Городская биржа (P2P): двусторонний ордербук ──────────────────────────
def create_order(
    session: AsyncSession, chat_id: int, seller_id: int,
    good: str, qty: int, unit_price: int, side: str = "sell",
) -> MarketOrder:
    order = MarketOrder(chat_id=chat_id, seller_id=seller_id, side=side,
                        good=good, qty=qty, unit_price=unit_price)
    session.add(order)
    return order


async def has_sell_orders(session: AsyncSession, good: str, exclude: int = 0) -> bool:
    """Есть ли чужие sell-ордера по товару (поиск дефицита для NPC-завоза)."""
    n = await session.scalar(
        select(func.count(MarketOrder.id)).where(
            MarketOrder.good == good, MarketOrder.side == "sell",
            MarketOrder.qty > 0, MarketOrder.seller_id != exclude)) or 0
    return n > 0


def _orders_q(exclude_seller: int, side: str, goods: list[str] | None):
    # ЕДИНЫЙ рынок: стакан глобальный (без фильтра по чату), скрываем лишь свои.
    stmt = select(MarketOrder).where(
        MarketOrder.seller_id != exclude_seller,
        MarketOrder.qty > 0,
        MarketOrder.side == side,
    )
    if goods is not None:
        stmt = stmt.where(MarketOrder.good.in_(goods))
    return stmt


async def open_orders(
    session: AsyncSession, exclude_seller: int, side: str,
    *, goods: list[str] | None = None, limit: int = 6, offset: int = 0,
) -> list[MarketOrder]:
    """Чужие активные лоты стороны side со всего мира (свои не показываем)."""
    stmt = (_orders_q(exclude_seller, side, goods)
            .order_by(MarketOrder.id.desc()).limit(limit).offset(offset))
    return list((await session.execute(stmt)).scalars().all())


async def count_open_orders(
    session: AsyncSession, exclude_seller: int, side: str,
    *, goods: list[str] | None = None,
) -> int:
    sub = _orders_q(exclude_seller, side, goods).subquery()
    return await session.scalar(select(func.count()).select_from(sub)) or 0


async def count_seller_orders(
    session: AsyncSession, seller_id: int, side: str
) -> int:
    return await session.scalar(
        select(func.count(MarketOrder.id)).where(
            MarketOrder.seller_id == seller_id, MarketOrder.side == side)
    ) or 0


async def seller_orders(session: AsyncSession, seller_id: int) -> list[MarketOrder]:
    return list((await session.execute(
        select(MarketOrder).where(MarketOrder.seller_id == seller_id)
        .order_by(MarketOrder.id.desc())
    )).scalars().all())


async def get_order(
    session: AsyncSession, order_id: int, *, lock: bool = False
) -> MarketOrder | None:
    return await session.get(MarketOrder, order_id, with_for_update=lock)


async def delete_order(session: AsyncSession, order_id: int) -> None:
    await session.execute(delete(MarketOrder).where(MarketOrder.id == order_id))


async def delete_player_orders(session: AsyncSession, seller_id: int) -> None:
    """Снести все биржевые лоты игрока (при сбросе/удалении — чтоб не осиротели)."""
    await session.execute(
        delete(MarketOrder).where(MarketOrder.seller_id == seller_id))


async def best_buy_orders(
    session: AsyncSession, good: str, min_price: int,
    exclude_seller: int, *, limit: int, lock: bool = True,
) -> list[MarketOrder]:
    """Заявки «куплю» со всего мира по товару с ценой >= min_price (лучшие —
    дороже первыми). Для авто-сведения новой ПРОДАЖИ. lock — FOR UPDATE SKIP LOCKED."""
    stmt = (select(MarketOrder).where(
                MarketOrder.side == "buy",
                MarketOrder.good == good, MarketOrder.qty > 0,
                MarketOrder.unit_price >= min_price,
                MarketOrder.seller_id != exclude_seller)
            .order_by(MarketOrder.unit_price.desc(), MarketOrder.id)
            .limit(limit))
    if lock:
        stmt = stmt.with_for_update(skip_locked=True)
    return list((await session.execute(stmt)).scalars().all())


async def best_sell_orders(
    session: AsyncSession, good: str, max_price: int,
    exclude_seller: int, *, limit: int, lock: bool = True,
) -> list[MarketOrder]:
    """Лоты продажи со всего мира по товару с ценой <= max_price (лучшие —
    дешевле первыми). Для авто-сведения новой ЗАЯВКИ «куплю»."""
    stmt = (select(MarketOrder).where(
                MarketOrder.side == "sell",
                MarketOrder.good == good, MarketOrder.qty > 0,
                MarketOrder.unit_price <= max_price,
                MarketOrder.seller_id != exclude_seller)
            .order_by(MarketOrder.unit_price.asc(), MarketOrder.id)
            .limit(limit))
    if lock:
        stmt = stmt.with_for_update(skip_locked=True)
    return list((await session.execute(stmt)).scalars().all())


async def market_summary(session: AsyncSession) -> dict:
    """Сводка ЕДИНОЙ биржи по товарам: {good: {ask, ask_qty, bid, bid_qty}}.
    ask — лучшая (минимальная) цена продажи, bid — лучшая (макс.) цена покупки."""
    rows = (await session.execute(
        select(MarketOrder.good, MarketOrder.side,
               func.min(MarketOrder.unit_price), func.max(MarketOrder.unit_price),
               func.sum(MarketOrder.qty))
        .where(MarketOrder.qty > 0)
        .group_by(MarketOrder.good, MarketOrder.side)
    )).all()
    board: dict[str, dict] = {}
    for good, side, pmin, pmax, qsum in rows:
        d = board.setdefault(good, {})
        if side == "sell":
            d["ask"], d["ask_qty"] = int(pmin), int(qsum)
        else:
            d["bid"], d["bid_qty"] = int(pmax), int(qsum)
    return board


async def best_price(
    session: AsyncSession, good: str, side: str
) -> int | None:
    """Лучшая встречная цена на ЕДИНОЙ бирже: side='sell' → мин ask, 'buy' → макс bid."""
    col = (func.min(MarketOrder.unit_price) if side == "sell"
           else func.max(MarketOrder.unit_price))
    return await session.scalar(
        select(col).where(MarketOrder.side == side,
                          MarketOrder.good == good, MarketOrder.qty > 0))


async def stale_orders(
    session: AsyncSession, cutoff: datetime, limit: int = 30
) -> list[MarketOrder]:
    """Лоты старше cutoff — на авто-истечение (с возвратом товара/залога)."""
    return list((await session.execute(
        select(MarketOrder).where(MarketOrder.created_at < cutoff)
        .order_by(MarketOrder.id).limit(limit)
        .with_for_update(skip_locked=True)
    )).scalars().all())


async def recent_chronicle(
    session: AsyncSession, chat_id: int, limit: int = 10
) -> list[str]:
    """Последние записи летописи (свежие сверху)."""
    result = await session.execute(
        select(Chronicle.text)
        .where(Chronicle.chat_id == chat_id)
        .order_by(Chronicle.id.desc())
        .limit(limit)
    )
    return [row[0] for row in result.all()]


async def get_player(
    session: AsyncSession, telegram_id: int, *, for_update: bool = False
) -> Player | None:
    """Игрок по Telegram ID. for_update=True блокирует строку до конца
    транзакции — одновременные клики обрабатываются по очереди."""
    if for_update:
        return await session.get(Player, telegram_id, with_for_update=True)
    return await session.get(Player, telegram_id)


async def create_player(
    session: AsyncSession, telegram_id: int, username: str | None, first_name: str
) -> Player:
    player = Player(
        id=telegram_id,
        username=username,
        first_name=first_name,
        inventory=dict(balance.STARTING_INVENTORY),
    )
    session.add(player)
    await session.flush()
    return player


async def create_tavern(
    session: AsyncSession, player: Player, name: str, region: str
) -> Tavern:
    tavern = Tavern(
        player_id=player.id,
        name=name,
        last_income_at=datetime.now(timezone.utc),
    )
    player.region = region
    session.add(tavern)
    await session.flush()
    await session.refresh(player)
    return tavern


async def get_tavern(session: AsyncSession, player_id: int) -> Tavern | None:
    result = await session.execute(
        select(Tavern).where(Tavern.player_id == player_id)
    )
    return result.scalar_one_or_none()


async def assign_map_slot(session: AsyncSession, tavern: Tavern, region: str) -> int | None:
    """Выдаёт таверне свободный слот её зоны на карте мира."""
    from bot.game import worldmap

    if tavern.map_slot is not None:
        return tavern.map_slot
    # сериализуем выдачу слотов: два игрока не получат один круг
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(420001)"))
    result = await session.execute(
        select(Tavern.map_slot).where(Tavern.map_slot.is_not(None))
    )
    used = {row[0] for row in result}
    for sid in worldmap.zone_slots(region):
        if sid not in used:
            tavern.map_slot = sid
            await session.flush()
            return sid
    return None  # зона заполнена


async def get_map_taverns(session: AsyncSession) -> list[tuple[Tavern, Player]]:
    """Все таверны с их владельцами для рендера карты."""
    result = await session.execute(
        select(Tavern, Player).join(Player, Tavern.player_id == Player.id)
    )
    return list(result.all())


async def top_sellers(
    session: AsyncSession, limit: int = 10
) -> list[tuple[Tavern, Player]]:
    """Рейтинг продавцов: таверны с наибольшим объёмом проданного на бирже."""
    result = await session.execute(
        select(Tavern, Player).join(Player, Tavern.player_id == Player.id)
        .where(Tavern.auction_sold > 0)
        .order_by(Tavern.auction_sold.desc(), Tavern.id).limit(limit)
    )
    return list(result.all())


# ── Зазывала (рефералка) ──────────────────────────────────────────────────────
async def count_referrals(session: AsyncSession, inviter_id: int) -> int:
    """Сколько друзей этот игрок реально привёл (активировали кабак)."""
    return await session.scalar(
        select(func.count()).select_from(Player)
        .where(Player.referred_by == inviter_id, Player.ref_rewarded.is_(True))
    ) or 0


async def top_referrers(
    session: AsyncSession, limit: int = 10
) -> list[tuple[Player, int]]:
    """Топ зазывал: игроки по числу приведённых (активированных) друзей."""
    sub = (select(Player.referred_by.label("inv"), func.count().label("n"))
           .where(Player.referred_by.isnot(None), Player.ref_rewarded.is_(True))
           .group_by(Player.referred_by).subquery())
    rows = await session.execute(
        select(Player, sub.c.n).join(sub, Player.id == sub.c.inv)
        .order_by(sub.c.n.desc(), Player.id).limit(limit))
    return list(rows.all())


async def grant_referral_rewards(session: AsyncSession, invitee: Player) -> dict | None:
    """Выдать награды зазывалы при АКТИВАЦИИ новичка (завёл кабак). Строго один раз.
    Платим пригласившему (золото+репутация) и новичку (подъёмные), плюс тир-бонусы
    за вехи (5/10/25 друзей). Возвращает {'invitee_gold': N} для сообщения новичку."""
    if invitee.referred_by is None or invitee.ref_rewarded:
        return None
    invitee.ref_rewarded = True            # помечаем сразу (даже если пригласивший пропал)
    referrer = await session.get(Player, invitee.referred_by, with_for_update=True)
    if referrer is None or referrer.id == invitee.id:
        return None
    invitee.gold += balance.REFERRAL_INVITEE_GOLD
    economy.record(invitee, "referral", balance.REFERRAL_INVITEE_GOLD)
    referrer.gold += balance.REFERRAL_INVITER_GOLD
    economy.record(referrer, "referral", balance.REFERRAL_INVITER_GOLD)
    referrer.reputation += balance.REFERRAL_INVITER_REP
    if referrer.tavern is not None:
        referrer.tavern.reputation += balance.REFERRAL_INVITER_REP
    queue_notify(session, referrer.id,
                 f"🍻 Твой зазыв сработал — новый кабатчик в Недоливске! "
                 f"+{balance.REFERRAL_INVITER_GOLD} 🪙 и +{balance.REFERRAL_INVITER_REP} ⭐.",
                 kind="ref")
    activated = await count_referrals(session, referrer.id)   # включая этого (уже помечен)
    while (referrer.ref_tier < len(balance.REFERRAL_TIERS)
           and activated >= balance.REFERRAL_TIERS[referrer.ref_tier][0]):
        need, bonus = balance.REFERRAL_TIERS[referrer.ref_tier]
        referrer.gold += bonus
        economy.record(referrer, "referral", bonus)
        referrer.ref_tier += 1
        queue_notify(session, referrer.id,
                     f"🏅 Зазывала: {need} друзей в деле — жирный бонус +{bonus} 🪙!",
                     kind="ref")
    return {"invitee_gold": balance.REFERRAL_INVITEE_GOLD}
