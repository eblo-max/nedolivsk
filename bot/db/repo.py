from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    Chronicle, CityState, KnownChat, Player, Tavern, WorldState,
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


async def add_chronicle(session: AsyncSession, chat_id: int, text: str) -> None:
    """Запись в летопись города."""
    session.add(Chronicle(chat_id=chat_id, text=text[:256]))


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
