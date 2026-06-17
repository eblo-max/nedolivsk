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
    # Спрос-событие («мода»): премия к ЦЕНЕ одного случайного товара (рознице и
    # бирже разом). >1 — товар в моде. Конкретный товар хранится в world.event_good.
    good_price: float = 1.0


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
    # ── спрос-событие (мода на товар) ──
    "fashion": WEvent("fashion", "🔥", "Ажиотаж",
                      "Весь Недоливск вдруг помешался на одном товаре — он в цене, "
                      "налетай: вари, скупай на бирже и сбывай втридорога!",
                      5, weight=16, good_price=1.5),
}

# Лёгкий кэш активного события (id + конец + трендовый товар) — ставит нотифаер раз в тик.
_active_id: str | None = None
_active_until: datetime | None = None
_active_good: str | None = None


def set_active(event_id: str | None, until: datetime | None = None,
               good: str | None = None) -> None:
    global _active_id, _active_until, _active_good
    _active_id, _active_until, _active_good = event_id, until, good


def active() -> WEvent | None:
    return EVENTS.get(_active_id) if _active_id else None


def active_until() -> datetime | None:
    return _active_until


def fashion_good() -> str | None:
    """ID товара, на который сейчас мода (или None)."""
    e = active()
    return _active_good if (e is not None and e.good_price != 1.0) else None


def good_price_mult(good: str) -> float:
    """Премия к цене товара от моды (рознице и бирже). 1.0 — товар не в моде."""
    e = active()
    if e is not None and e.good_price != 1.0 and good == _active_good:
        return e.good_price
    return 1.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def effect_summary(e: WEvent) -> str:
    """Человекочитаемые последствия события из каналов: «−15% добыча, +15% доход».
    Время вылазок/варки: <1 — быстрее (показываем −%), >1 — медленнее (+%)."""
    parts: list[str] = []

    def higher_better(mult: float, label: str) -> None:
        if mult != 1.0:
            parts.append(f"{'+' if mult > 1 else '−'}{round(abs(mult - 1) * 100)}% {label}")

    def lower_better(mult: float, label: str) -> None:  # время: меньше = выгода
        if mult != 1.0:
            parts.append(f"{'−' if mult < 1 else '+'}{round(abs(mult - 1) * 100)}% {label}")

    higher_better(e.income, "доход")
    higher_better(e.harvest, "добыча")
    higher_better(e.sale, "сбыт")
    lower_better(e.exp_speed, "время вылазок")
    lower_better(e.prod_speed, "время варки")
    if e.good_price != 1.0:   # мода: премия к цене конкретного товара
        parts.append(f"+{round((e.good_price - 1) * 100)}% цена модного товара")
    return ", ".join(parts)


def roll(rng: random.Random | None = None) -> str:
    """Случайное событие по весам."""
    rng = rng or random
    ids = list(EVENTS)
    return rng.choices(ids, weights=[EVENTS[i].weight for i in ids])[0]


def _pct(v: float) -> str:
    return f"+{round((v - 1) * 100)}%" if v > 1 else f"−{round((1 - v) * 100)}%"


def _spd(v: float, label: str) -> str:
    return (f"{label} быстрее на {round((1 - v) * 100)}%" if v < 1
            else f"{label} медленнее на {round((v - 1) * 100)}%")


def describe(e: "WEvent") -> str:
    """Человекочитаемые последствия события (для экрана таверны), в одну строку."""
    parts = []
    if e.income != 1.0:
        parts.append(f"🪙 доход {_pct(e.income)}")
    if e.harvest != 1.0:
        parts.append(f"⛏ добыча {_pct(e.harvest)}")
    if e.sale != 1.0:
        parts.append(f"💰 сбыт {_pct(e.sale)}")
    if e.exp_speed != 1.0:
        parts.append("🦵 " + _spd(e.exp_speed, "вылазки"))
    if e.prod_speed != 1.0:
        parts.append("🍺 " + _spd(e.prod_speed, "варка"))
    return " · ".join(parts)


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
            world.event_good = None
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
        world.event_good = _pick_good(rng) if e.good_price != 1.0 else None
        return e
    return None


def _pick_good(rng: random.Random) -> str:
    """Случайный товар для моды (лениво импортируем каталог — без цикла импорта)."""
    from bot.game import production as prod
    return rng.choice(list(prod.GOODS))


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
