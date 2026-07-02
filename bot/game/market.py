"""Единый (глобальный) динамический рынок Недоливска.

Оптовая цена (fv) у заезжих купцов проседает, когда товар заваливает рынок,
и восстанавливается, когда сбыт стихает. Рынок ОДИН на весь мир: завал (glut)
копят сделки ВСЕХ чатов (сбыт купцам, NPC-аукцион, P2P-биржа), и цена одна для
всех. Завал тает экспоненциально к нулю, как излишки впитывает спрос. Состояние
живёт на WorldState.market: {good: glut_units, '_t': iso-метка распада}.

Розница (гости в collect_income) платит фиксированную цену — её объём двигает
МЕСТНОЕ настроение/ситуация города (живой колорит чата), но на ГЛОБАЛЬНУЮ
оптовую цену настроение уже не влияет — она едина для всех. Заезжий ОПТОВИК
режет цену тем сильнее, чем больше товара выброшено на общий рынок.

`holder` — носитель состояния рынка (WorldState, глобально). None → базовые цены.
"""

import math
from datetime import datetime, timezone

from bot.game import balance

_TKEY = "_t"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def factor(holder, good: str) -> float:
    """Множитель справедливой цены good от завала мирового рынка (≤1, не ниже пола).
    Пороги — адаптивные: множатся на holder.market_scale (число активных чатов)."""
    if holder is None:
        return 1.0
    glut = float((holder.market or {}).get(good, 0.0))
    scale = getattr(holder, "market_scale", 1) or 1
    return balance.market_factor(glut, scale)


def glut(holder, good: str) -> float:
    if holder is None:
        return 0.0
    return float((holder.market or {}).get(good, 0.0))


def nudge(holder, good: str, delta: float) -> None:
    """Сдвинуть баланс рынка по товару: +delta — завал (цена вниз),
    −delta — дефицит/скупка (цена вверх)."""
    if holder is None or delta == 0:
        return
    m = dict(holder.market or {})
    m[good] = float(m.get(good, 0.0)) + delta
    m.setdefault(_TKEY, _now().isoformat())
    holder.market = m  # переприсваивание — чтобы JSONB заметил


def add_supply(holder, good: str, qty: int) -> None:
    """Сбыт партии выбрасывает товар на рынок — давит его оптовую цену."""
    if qty > 0:
        nudge(holder, good, qty)


def decay(holder, now: datetime | None = None) -> None:
    """Рынок впитывает перекос: тает экспоненциально к нулю (τ часов).
    Пустой рынок чистим до {}, чтобы не писать в БД каждый тик и чтобы новая
    партия не «впиталась» мгновенно из-за устаревшей метки."""
    if holder is None:
        return
    m = dict(holder.market or {})
    goods = [g for g in m if g != _TKEY and isinstance(m[g], (int, float))]
    if not goods:                       # впитывать нечего
        if m and all(g == _TKEY for g in m):   # остались только метки — сбрасываем
            holder.market = {}
        return
    now = now or _now()
    t = m.get(_TKEY)
    if not t:                           # старое состояние без метки — проставим
        m[_TKEY] = now.isoformat()
        holder.market = m
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
    remaining = [g for g in m if g != _TKEY and isinstance(m.get(g), (int, float))]
    holder.market = {**m, _TKEY: now.isoformat()} if remaining else {}
