"""Ежедневный бонус («опохмел»).

Раз в сутки игроку выпадает claimable-баф из пула. Он висит 24ч и сгорает,
если не активировать. Активируешь когда хочешь — действует 4 часа; одновременно
активен только один. Эффекты намеренно скромные (10–15%), чтобы не ломать
экономику: дают приятный повод заходить каждый день, а не перекос в балансе.

Состояние на Player:
  bonus_kind / bonus_offered_at — висящее предложение и время его выдачи (TTL 24ч)
  buff_kind / buff_until        — активный баф и время его окончания
  bonus_next_at                 — когда разрешено выдать следующее предложение
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

OFFER_TTL_HOURS = 24   # сколько висит неактивированное предложение
BUFF_HOURS = 4         # длительность активного бафа
COOLDOWN_HOURS = 24    # как часто появляется новое предложение


@dataclass(frozen=True)
class Boon:
    id: str
    emoji: str
    name: str
    desc: str
    mult: float


BOONS: dict[str, Boon] = {
    "income": Boon("income", "🍺", "Бойкая касса",
                   "+10% золота с дохода и сбыта гостям", 1.10),
    "harvest": Boon("harvest", "⛏", "Щедрая жила",
                    "+15% ресурсов с вернувшихся бригад", 1.15),
    "trade": Boon("trade", "🤝", "Барыжья хватка",
                  "+10% золота с купца и аукциона", 1.10),
}
POOL = list(BOONS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def refresh(player, now: datetime | None = None) -> None:
    """Прокрутить состояние бонуса: снять истёкший баф, сжечь протухшее
    предложение, выдать новое по кулдауну. Вызывать перед показом таверны."""
    now = now or _now()
    # истёкший активный баф
    if player.buff_until is not None and player.buff_until <= now:
        player.buff_kind = None
        player.buff_until = None
    # протухшее (неактивированное за 24ч) предложение сгорает
    if (player.bonus_kind is not None and player.bonus_offered_at is not None
            and player.bonus_offered_at + timedelta(hours=OFFER_TTL_HOURS) <= now):
        player.bonus_kind = None
        player.bonus_offered_at = None
    # выдать новое предложение, если ничего не висит и кулдаун прошёл
    if player.bonus_kind is None and (
            player.bonus_next_at is None or player.bonus_next_at <= now):
        player.bonus_kind = random.choice(POOL)
        player.bonus_offered_at = now
        player.bonus_next_at = now + timedelta(hours=COOLDOWN_HOURS)


def offer(player) -> Boon | None:
    """Висящее claimable-предложение или None."""
    return BOONS.get(player.bonus_kind) if player.bonus_kind else None


def active(player, now: datetime | None = None) -> Boon | None:
    """Действующий сейчас баф или None."""
    now = now or _now()
    if player.buff_kind and player.buff_until and player.buff_until > now:
        return BOONS.get(player.buff_kind)
    return None


def minutes_left(player, now: datetime | None = None) -> int:
    now = now or _now()
    if player.buff_until and player.buff_until > now:
        return int((player.buff_until - now).total_seconds() // 60) + 1
    return 0


def offer_hours_left(player, now: datetime | None = None) -> int:
    """Сколько часов осталось до сгорания висящего предложения."""
    if player.bonus_kind is None or player.bonus_offered_at is None:
        return 0
    now = now or _now()
    left = (player.bonus_offered_at + timedelta(hours=OFFER_TTL_HOURS) - now)
    return max(0, int(left.total_seconds() // 3600) + 1)


@dataclass
class Activation:
    ok: bool
    reason: str = ""  # none | busy
    boon: Boon | None = None
    minutes: int = 0


def activate(player, now: datetime | None = None) -> Activation:
    """Активировать висящее предложение. Нельзя, пока действует другой баф."""
    now = now or _now()
    cur = active(player, now)
    if cur is not None:
        return Activation(False, "busy", boon=cur, minutes=minutes_left(player, now))
    boon = offer(player)
    if boon is None:
        return Activation(False, "none")
    player.buff_kind = boon.id
    player.buff_until = now + timedelta(hours=BUFF_HOURS)
    player.bonus_kind = None
    player.bonus_offered_at = None
    return Activation(True, boon=boon, minutes=BUFF_HOURS * 60)


def _mult(player, kind: str, now: datetime | None = None) -> float:
    b = active(player, now)
    return b.mult if b is not None and b.id == kind else 1.0


def gold_mult(player, now: datetime | None = None) -> float:
    """Множитель золота с кассы (пассив + сбыт гостям)."""
    return _mult(player, "income", now)


def yield_mult(player, now: datetime | None = None) -> float:
    """Множитель ресурсов с бригад."""
    return _mult(player, "harvest", now)


def sale_mult(player, now: datetime | None = None) -> float:
    """Множитель золота с купеческих сделок и аукциона."""
    return _mult(player, "trade", now)
