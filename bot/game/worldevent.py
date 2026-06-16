"""Мировые события: один временный эффект на весь мир (погода + экономика).

Лучшие практики (Stardew/RDR2): не «флэт-минус», а трейд-оффы — одно занятие
лучше, другое хуже, игрок адаптируется. Дебаффы мягкие и НЕ бьют по новичкам
(щит story_state.is_shielded). Одно событие за раз, ~1/сутки, анонс на старте.

Эффект применяется множителями рядом с личными баффами (logic/production/auction/
trade). Активное событие держит лёгкий кэш (ставит нотифаер раз в тик), чтобы
геттеры не дёргали БД на каждый расчёт.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, story_state


@dataclass(frozen=True)
class WEvent:
    id: str
    emoji: str
    name: str
    blurb: str               # анонс в трактирном стиле
    hours: int
    weight: int = 10
    # Каналы-множители. >1 — выгода, <1 — урон (для income/harvest/sale);
    # для скоростей наоборот: <1 быстрее (выгода), >1 медленнее (урон).
    income: float = 1.0
    harvest: float = 1.0
    sale: float = 1.0
    exp_speed: float = 1.0
    prod_speed: float = 1.0


EVENTS: dict[str, WEvent] = {
    # ── чистые баффы ──
    "clear": WEvent("clear", "☀️", "Вёдро",
                    "Ясное небо над Недоливском — бригады резвее в дороге.",
                    4, exp_speed=0.80),
    "harvest": WEvent("harvest", "🌾", "Урожайный год",
                      "Земля щедра как никогда — добыча так и прёт.", 6, harvest=1.20),
    "goldrush": WEvent("goldrush", "🪙", "Золотая лихорадка",
                       "Купцы при деньгах — за товар дают щедро.", 4, sale=1.20),
    "bazaar": WEvent("bazaar", "🍺", "Базарный гул",
                     "Народ гуляет и кутит — касса звенит.", 4, income=1.15),
    # ── трейд-оффы (одно лучше, другое хуже) ──
    "rain": WEvent("rain", "🌧", "Ненастье",
                   "Ливни развезли тракт — зато в тепле спорится варка.",
                   4, exp_speed=1.25, prod_speed=0.80),
    "frost": WEvent("frost", "❄️", "Лютая стужа",
                    "Мороз бьёт по добыче, но греться элем идут охотнее.",
                    5, harvest=0.85, income=1.15),
    "drought": WEvent("drought", "🔥", "Засуха",
                      "Воды и зерна мало — зато за товар дают больше.",
                      5, harvest=0.85, sale=1.15),
    # ── мягкие дебаффы (переждать) ──
    "storm": WEvent("storm", "🌪", "Буря",
                    "Купцы попрятались — торг застопорился. Переждать да продолжить.",
                    3, sale=0.80),
    "plague": WEvent("plague", "🦠", "Поветрие",
                     "Хворь разогнала гостей — самое время делать товар впрок.",
                     5, income=0.85),
}

# Лёгкий кэш активного события (id + конец) — ставит нотифаер раз в тик.
_active_id: str | None = None
_active_until: datetime | None = None


def set_active(event_id: str | None, until: datetime | None = None) -> None:
    global _active_id, _active_until
    _active_id, _active_until = event_id, until


def active() -> WEvent | None:
    return EVENTS.get(_active_id) if _active_id else None


def active_until() -> datetime | None:
    return _active_until


def _now() -> datetime:
    return datetime.now(timezone.utc)


def roll(rng: random.Random | None = None) -> str:
    """Случайное событие по весам."""
    rng = rng or random
    ids = list(EVENTS)
    return rng.choices(ids, weights=[EVENTS[i].weight for i in ids])[0]


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def advance(world, now: datetime, rng: random.Random | None = None) -> "WEvent | None":
    """Прокрутить мировое событие (мутирует world.event_kind/until/next):
      активно и истекло → снять + назначить кулдаун;
      нет события и кулдаун прошёл → катнуть новое (вернуть его для анонса).
    Кэш активного ставит вызывающий ПОСЛЕ коммита (set_active). Чистая логика —
    тестируется без БД."""
    rng = rng or random
    until = _aware(world.event_until)
    nxt = _aware(world.event_next_at)
    cd = timedelta(hours=rng.uniform(balance.WORLDEVENT_COOLDOWN_MIN_HOURS,
                                     balance.WORLDEVENT_COOLDOWN_MAX_HOURS))
    if world.event_kind:
        if until is not None and now >= until:        # событие кончилось
            world.event_kind = None
            world.event_until = None
            world.event_next_at = now + cd
        return None
    if nxt is None:                                    # первичная пауза — не палим сразу
        world.event_next_at = now + cd
        return None
    if now >= nxt:                                     # кулдаун прошёл — новое событие
        e = EVENTS[roll(rng)]
        world.event_kind = e.id
        world.event_until = now + timedelta(hours=e.hours)
        world.event_next_at = None
        return e
    return None


def _ch(player, val: float, higher_better: bool) -> float:
    """Множитель канала с учётом щита новичка: урон-сторона не бьёт новичка."""
    if val == 1.0:
        return 1.0
    is_debuff = val < 1.0 if higher_better else val > 1.0
    if is_debuff and player is not None and story_state.is_shielded(player, _now()):
        return 1.0
    return val


def income_mult(player=None) -> float:
    e = active()
    return _ch(player, e.income, True) if e else 1.0


def harvest_mult(player=None) -> float:
    e = active()
    return _ch(player, e.harvest, True) if e else 1.0


def sale_mult(player=None) -> float:
    e = active()
    return _ch(player, e.sale, True) if e else 1.0


def exp_speed_mult(player=None) -> float:
    e = active()
    return _ch(player, e.exp_speed, False) if e else 1.0


def prod_speed_mult(player=None) -> float:
    e = active()
    return _ch(player, e.prod_speed, False) if e else 1.0
