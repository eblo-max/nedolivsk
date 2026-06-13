"""Мировые события. Этап 1: ярмарка (спрос ×2 раз в день).

Источник правды — строка WorldState в БД (переживает рестарт). Для быстрых
чтений (экраны, доход) держим кэш в процессе, который обновляет планировщик
нотифаера каждую минуту. Писатель один — advance()/open_fair() в нотифаере/
админке; читатели — is_fair()/demand_mult()/fair_minutes_left().
"""

from datetime import datetime, timedelta, timezone

from bot.game import balance

_fair_until: datetime | None = None  # кэш окончания текущей ярмарки


def _now() -> datetime:
    return datetime.now(timezone.utc)


def refresh_cache(world) -> None:
    global _fair_until
    _fair_until = world.fair_until


def is_fair() -> bool:
    return _fair_until is not None and _fair_until > _now()


def fair_minutes_left() -> int:
    if not is_fair():
        return 0
    return int((_fair_until - _now()).total_seconds() // 60) + 1


def demand_mult() -> float:
    return balance.FAIR_DEMAND_MULT if is_fair() else 1.0


def _next_fair_time(after: datetime) -> datetime:
    """Ближайшее наступление FAIR_HOUR_UTC строго после `after`."""
    t = after.replace(
        hour=balance.FAIR_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if t <= after:
        t += timedelta(days=1)
    return t


def advance(world) -> str | None:
    """Двигает расписание ярмарки по строке мира. Возвращает событие для
    анонса в чат: 'pre' | 'open' | 'close' | None. Мутирует world, кэш —
    снаружи. За тик отдаём максимум одно событие (они разнесены во времени)."""
    now = _now()
    if world.next_fair_at is None:
        world.next_fair_at = _next_fair_time(now)
        world.fair_pre_announced = False
        return None
    if world.fair_until is not None and world.fair_until <= now:
        world.fair_until = None
        return "close"
    if world.fair_until is None and now >= world.next_fair_at:
        world.fair_until = now + timedelta(hours=balance.FAIR_DURATION_HOURS)
        world.next_fair_at = _next_fair_time(world.fair_until)
        world.fair_pre_announced = False  # анонс для следующей ярмарки
        return "open"
    pre_at = world.next_fair_at - timedelta(hours=balance.FAIR_PRE_HOURS)
    if world.fair_until is None and not world.fair_pre_announced and now >= pre_at:
        world.fair_pre_announced = True
        return "pre"
    return None


def open_fair(world) -> None:
    """Открыть ярмарку немедленно (админ-команда /fair). Сдвигаем плановую и
    сбрасываем флаг анонса, чтобы её предупреждение пришло как обычно."""
    world.fair_until = _now() + timedelta(hours=balance.FAIR_DURATION_HOURS)
    world.next_fair_at = _next_fair_time(world.fair_until)
    world.fair_pre_announced = False
    refresh_cache(world)
