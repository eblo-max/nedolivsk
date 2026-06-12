from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Player, Tavern


async def get_player(session: AsyncSession, telegram_id: int) -> Player | None:
    return await session.get(Player, telegram_id)


async def create_player(
    session: AsyncSession, telegram_id: int, username: str | None, first_name: str
) -> Player:
    player = Player(id=telegram_id, username=username, first_name=first_name)
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
