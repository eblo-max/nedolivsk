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
    # mult — представительная величина эффекта (для income/harvest/trade — прямой
    # множитель; для остальных смысл задаётся в *_mult/*_bonus ниже).
    "income": Boon("income", "🍺", "Бойкая касса",
                   "+10% золота с дохода и сбыта гостям", 1.10),
    "trade": Boon("trade", "🤝", "Барыжья хватка",
                  "+10% золота с купца и аукциона", 1.10),
    "harvest": Boon("harvest", "⛏", "Щедрая жила",
                    "+15% ресурсов с вернувшихся бригад", 1.15),
    "swift": Boon("swift", "🦵", "Быстрые ноги",
                  "−25% времени вылазки бригад", 0.75),
    "brew": Boon("brew", "🔥", "Спорая варка",
                 "−20% времени производства на пристройках", 0.80),
    "scent": Boon("scent", "🐾", "Звериный нюх",
                  "+20% золота и добычи с охоты", 1.20),
    "tough": Boon("tough", "🛡", "Толстая шкура",
                  "−20% урона по тебе в бою", 0.80),
    "luck": Boon("luck", "🍀", "Фартовый день",
                 "+удача: крит, редкая добыча и фарт бригад", 1.0),
    "cellar": Boon("cellar", "❄️", "Холодный погреб",
                   "−50% порчи излишков в погребе", 0.50),
    "mend": Boon("mend", "❤️‍🩹", "Быстрое заживление",
                 "здоровье восстанавливается вдвое быстрее", 0.50),
}
POOL = list(BOONS)

LUCK_BONUS = 20  # сколько очков удачи даёт «Фартовый день»


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


def _has(player, kind: str, now: datetime | None = None) -> bool:
    b = active(player, now)
    return b is not None and b.id == kind


def gold_mult(player, now: datetime | None = None) -> float:
    """Множитель золота с кассы (пассив + сбыт гостям) — «Бойкая касса»."""
    return BOONS["income"].mult if _has(player, "income", now) else 1.0


def sale_mult(player, now: datetime | None = None) -> float:
    """Множитель золота с купца и аукциона — «Барыжья хватка»."""
    return BOONS["trade"].mult if _has(player, "trade", now) else 1.0


def yield_mult(player, now: datetime | None = None) -> float:
    """Множитель ресурсов с бригад — «Щедрая жила»."""
    return BOONS["harvest"].mult if _has(player, "harvest", now) else 1.0


def expedition_speed_mult(player, now: datetime | None = None) -> float:
    """Множитель времени вылазки (меньше — быстрее) — «Быстрые ноги»."""
    return BOONS["swift"].mult if _has(player, "swift", now) else 1.0


def prod_speed_mult(player, now: datetime | None = None) -> float:
    """Множитель времени производства (меньше — быстрее) — «Спорая варка»."""
    return BOONS["brew"].mult if _has(player, "brew", now) else 1.0


def hunt_gold_mult(player, now: datetime | None = None) -> float:
    """Множитель золота/добычи с охоты — «Звериный нюх»."""
    return BOONS["scent"].mult if _has(player, "scent", now) else 1.0


def tough_mult(player, now: datetime | None = None) -> float:
    """Множитель урона ПО игроку в бою (меньше — крепче) — «Толстая шкура»."""
    return BOONS["tough"].mult if _has(player, "tough", now) else 1.0


def regen_mult(player, now: datetime | None = None) -> float:
    """Множитель времени восстановления HP (меньше — быстрее) — «Заживление»."""
    return BOONS["mend"].mult if _has(player, "mend", now) else 1.0


def spoil_mult(player, now: datetime | None = None) -> float:
    """Множитель порчи погреба (меньше — бережнее) — «Холодный погреб»."""
    return BOONS["cellar"].mult if _has(player, "cellar", now) else 1.0


def luck_bonus(player, now: datetime | None = None) -> int:
    """Прибавка очков удачи — «Фартовый день» (крит, редкая добыча, фарт бригад)."""
    return LUCK_BONUS if _has(player, "luck", now) else 0
