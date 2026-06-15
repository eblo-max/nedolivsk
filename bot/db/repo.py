from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    Chronicle, CityState, KnownChat, LogEntry, LootDrop, MarketOrder,
    Notification, Player, Tavern, WorldState,
)
from bot.game import balance


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


async def get_or_create_city(
    session: AsyncSession, chat_id: int, *, lock: bool = False
) -> CityState:
    """Состояние живого города для конкретного чата (ленивое создание).
    lock=True блокирует строку до конца транзакции — для безопасной правки
    силы фракций при одновременных событиях."""
    city = await session.get(CityState, chat_id, with_for_update=lock)
    if city is None:
        city = CityState(chat_id=chat_id)
        session.add(city)
        await session.flush()
    return city


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
def queue_notify(session: AsyncSession, user_id: int, text: str) -> None:
    """Положить личку игроку в очередь (атомарно со сделкой; шлёт нотифаер)."""
    session.add(Notification(user_id=user_id, text=text[:512]))


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
