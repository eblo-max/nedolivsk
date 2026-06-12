from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


class Player(Base):
    """Игрок = пользователь Telegram."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    level: Mapped[int] = mapped_column(default=1)
    gold: Mapped[int] = mapped_column(default=100)
    reputation: Mapped[int] = mapped_column(default=0)
    region: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(default=True)

    # Ресурсы
    wood: Mapped[int] = mapped_column(default=10)
    grain: Mapped[int] = mapped_column(default=10)
    hops: Mapped[int] = mapped_column(default=5)

    # Текущая вылазка работников (за одним ресурсом)
    expedition_resource: Mapped[str | None] = mapped_column(String(16))
    expedition_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    tavern: Mapped["Tavern | None"] = relationship(
        back_populates="player", uselist=False, lazy="selectin"
    )


class Tavern(Base):
    """Таверна игрока (одна на игрока)."""

    __tablename__ = "taverns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id"), unique=True
    )

    name: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(default=1)
    capacity: Mapped[int] = mapped_column(default=10)
    comfort: Mapped[int] = mapped_column(default=1)
    income_rate: Mapped[int] = mapped_column(default=10)  # золото в час
    reputation: Mapped[int] = mapped_column(default=0)

    upgrades: Mapped[dict] = mapped_column(JSONB, default=dict)
    buildings: Mapped[list] = mapped_column(JSONB, default=list)

    last_income_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    player: Mapped[Player] = relationship(back_populates="tavern")
