"""Сезоны и праздники (фаза 4c). Привязаны к дате — глобально для всех чатов,
без хранения (как ярмарка). Меняют добычу на вылазках и спрос в кабаках,
открывают тематические события. Праздник — особый день со всплеском спроса.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from bot.game import balance

_EPOCH = date(2026, 1, 1)
_YEAR_DAYS = balance.SEASON_LENGTH_DAYS * 4


@dataclass(frozen=True)
class Season:
    id: str
    name: str
    emoji: str
    demand_mult: float          # множитель спроса в кабаках
    default_yield: float        # множитель добычи по умолчанию
    yield_mults: dict           # ресурс -> множитель добычи
    blurb: str                  # короткое описание (анонс/экран)


SEASONS: list[Season] = [
    Season("spring", "Весна", "🌸", 1.0, 1.0,
           {"herbs": 1.2, "water": 1.2, "game": 1.2, "wood": 1.15},
           "природа оживает, в лесах вдоволь трав и дичи"),
    Season("summer", "Лето", "☀️", 1.08, 1.0,
           {"berries": 1.2, "honey": 1.2, "water": 1.15},
           "жара гонит народ в кабаки, спрос выше"),
    Season("autumn", "Осень", "🍂", 1.0, 1.0,
           {"grain": 1.25, "hops": 1.25, "berries": 1.25, "herbs": 1.25,
            "honey": 1.2},
           "урожай поспел, закрома ломятся от добра"),
    Season("winter", "Зима", "❄️", 0.92, 0.85, {},
           "добывать тяжко, народ сидит по домам"),
]


@dataclass(frozen=True)
class Holiday:
    id: str
    name: str
    emoji: str
    blurb: str


# День цикла (0..27) -> праздник.
HOLIDAYS: dict[int, Holiday] = {
    13: Holiday("city_day", "День Недоливска", "🎉",
                "весь город гуляет — спрос взлетел до небес"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_since_epoch(now: datetime) -> int:
    return (now.date() - _EPOCH).days


def current(now: datetime | None = None) -> Season:
    idx = (_days_since_epoch(now or _now()) // balance.SEASON_LENGTH_DAYS) % 4
    return SEASONS[idx]


def season_index(now: datetime | None = None) -> int:
    return (_days_since_epoch(now or _now()) // balance.SEASON_LENGTH_DAYS) % 4


def days_left(now: datetime | None = None) -> int:
    into = _days_since_epoch(now or _now()) % balance.SEASON_LENGTH_DAYS
    return balance.SEASON_LENGTH_DAYS - into


def holiday(now: datetime | None = None) -> Holiday | None:
    return HOLIDAYS.get(_days_since_epoch(now or _now()) % _YEAR_DAYS)


def is_holiday(now: datetime | None = None) -> bool:
    return holiday(now) is not None


def demand_mult(now: datetime | None = None) -> float:
    """Множитель спроса: сезон × (праздник, если сегодня)."""
    now = now or _now()
    m = current(now).demand_mult
    if is_holiday(now):
        m *= balance.HOLIDAY_DEMAND
    return m


def yield_mult(resource: str, now: datetime | None = None) -> float:
    """Множитель добычи ресурса в текущем сезоне."""
    s = current(now)
    return s.yield_mults.get(resource, s.default_yield)
