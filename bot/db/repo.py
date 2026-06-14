from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    Chronicle, CityState, KnownChat, LootDrop, Player, Tavern, WorldState,
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
