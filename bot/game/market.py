"""Динамический рынок Недоливска (по-чатовый общий рынок).

Оптовая цена (fv) у заезжих купцов проседает, когда товар заваливает рынок,
и восстанавливается, когда сбыт стихает. Сдерживание цен — рыночное: завал
(glut) копится от сбыта (и гостям, и купцам) и тает экспоненциально к нулю,
как излишки впитывает спрос. Состояние — на CityState.market:
{good: glut_units, '_t': iso-метка последнего распада}.

Розница (гости в collect_income) платит фиксированную цену — это локальный
спрос. А заезжий ОПТОВИК берёт партию на перепродажу и режет цену тем сильнее,
чем больше этого товара уже выброшено на рынок. Так переизбыток бьёт по сбыту.
"""

import math
from datetime import datetime, timezone

from bot.game import balance

_TKEY = "_t"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def factor(city, good: str) -> float:
    """Множитель справедливой цены good от завала рынка чата (≤1, не ниже пола)."""
    if city is None:
        return 1.0
    glut = float((city.market or {}).get(good, 0.0))
    return balance.market_factor(glut)


def glut(city, good: str) -> float:
    if city is None:
        return 0.0
    return float((city.market or {}).get(good, 0.0))


def nudge(city, good: str, delta: float) -> None:
    """Сдвинуть баланс рынка по товару: +delta — завал (цена вниз),
    −delta — дефицит/скупка (цена вверх)."""
    if city is None or delta == 0:
        return
    m = dict(city.market or {})
    m[good] = float(m.get(good, 0.0)) + delta
    m.setdefault(_TKEY, _now().isoformat())
    city.market = m  # переприсваивание — чтобы JSONB заметил


def add_supply(city, good: str, qty: int) -> None:
    """Сбыт партии выбрасывает товар на рынок — давит его оптовую цену."""
    if qty > 0:
        nudge(city, good, qty)


def decay(city, now: datetime | None = None) -> None:
    """Рынок впитывает перекос: тает экспоненциально к нулю (τ часов).
    Пустой рынок чистим до {}, чтобы не писать в БД каждый тик и чтобы новая
    партия не «впиталась» мгновенно из-за устаревшей метки."""
    if city is None:
        return
    m = dict(city.market or {})
    goods = [g for g in m if g != _TKEY]
    if not goods:                       # впитывать нечего
        if m:                           # остались только метки — сбрасываем
            city.market = {}
        return
    now = now or _now()
    t = m.get(_TKEY)
    if not t:                           # старое состояние без метки — проставим
        m[_TKEY] = now.isoformat()
        city.market = m
        return
    elapsed_h = (now - datetime.fromisoformat(t)).total_seconds() / 3600
    if elapsed_h <= 0:
        return
    k = math.exp(-elapsed_h / balance.MARKET_ABSORB_HOURS)
    for g in goods:
        nv = m[g] * k
        if abs(nv) < 0.5:               # перекос впитался — убираем ключ
            m.pop(g)
        else:
            m[g] = round(nv, 3)
    remaining = [g for g in m if g != _TKEY]
    city.market = {**m, _TKEY: now.isoformat()} if remaining else {}
