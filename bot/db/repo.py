from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Player, Tavern
from bot.game import balance


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
