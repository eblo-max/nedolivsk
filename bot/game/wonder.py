"""Общие стройки — «чудеса города» (модель Ишгарда).

Фаза 0 — только ДАННЫЕ: реестр чудес, их фазы, лор и описание баффа. Механику
вклада (очки по ценности, курс зодара, убывающая отдача, перцентильные бонусы,
капстоун) и активные буфы (`active_bonuses`) добавляет Фаза 1 — рядом, чтобы
показ и действие считала одна и та же котировка (инвариант проекта).

Валюта строек — «Зодар» (Player.zodar): даётся ТОЛЬКО за участие, не
покупается и не торгуется. Тратится в Лавке Артели (Фаза 2). См. docs/wonders.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    """Одна фаза стройки: ключ (для спрайта/анонса), название и цель в очках
    ЦЕННОСТИ на одного активного игрока — реальная цель = base_target × активных
    (масштаб по размеру мира, как market_scale/faction_decay_per_active). Числа
    предварительные: калибруются прод-пробой в Фазе 5."""
    key: str
    title: str
    base_target: int


@dataclass(frozen=True)
class WonderDef:
    key: str
    emoji: str
    name: str
    blurb: str            # анонс/лор в трактирном стиле
    phases: tuple         # tuple[Phase, ...] — от фундамента к вершине
    bonus: str            # человекочитаемый глобальный эффект (для экрана)
    sprite: str           # базовое имя картового спрайта; стадии — {sprite}_p{n}


WONDERS: dict[str, WonderDef] = {
    "wall": WonderDef(
        "wall", "🏯", "Твердыня",
        "Недоливск одевается в камень: ров, стены, ворота и детинец — "
        "теперь Орде так просто не пройти.",
        phases=(
            Phase("foundation", "Ров и фундамент", 1200),
            Phase("walls",      "Стены и ворота",  1800),
            Phase("keep",       "Башни и детинец", 2400),
        ),
        bonus="Орда приходит слабее — всему городу легче отбиться",
        sprite="wonder_wall",
    ),
}

# Какое чудо строим первым (Фаза 0 — без ротации; ротацию/выбор добавит Фаза 4).
FIRST_WONDER = "wall"

# Обкатка: вкладка «Стройка города» и эндпоинты — ТОЛЬКО админу (как invasion.TEST_MODE).
# Открыть всем = поставить False (плюс снять t.admin-гейт кнопки в Tavern.tsx).
WONDER_ADMIN_ONLY = True


def get(key: str) -> WonderDef | None:
    return WONDERS.get(key)


# ── Экономика вклада (Фаза 1). Числа ПРЕДВАРИТЕЛЬНЫЕ — «долго» by design, точная
# калибровка прод-пробой в Фазе 5. ──────────────────────────────────────────
GOLD_POINT_RATE = 0.5       # золото → очки: 1🪙 = 0.5 очка (труд ценнее денег)
ZODAR_PER_POINTS = 180      # очков ценности за 1 зодар
DAILY_SOFT_CAP = 2500       # очков/сутки на полном курсе; сверх — вдвое реже (анти-кит)
DIMINISHED_DIV = 2.0        # во сколько раз хуже эффективность сверх дневного порога
PHASE_BONUS_ZODAR = 6       # базовый бонус зодаров за закрытую фазу (× множитель брекета)
# Перцентильные брекеты (модель Elite Dangerous): доля топа по вкладу → множитель бонуса.
BONUS_BRACKETS = ((0.10, 3.0), (0.25, 2.0), (0.50, 1.5), (1.00, 1.0))

WALL_ESCAL_MULT = 0.85  # Твердыня готова → Орда на 15% СЛАБЕЕ (escal влияет на бой,
#                         в отличие от threshold — тот лишь эталон сложности)


def item_points(items: dict | None) -> int:
    """Ценность вклада в ОЧКАХ: сырьё×RESOURCE_PRICE, товары×GOODS.price,
    золото×GOLD_POINT_RATE. Неизвестные ключи игнорируются (безопасно)."""
    from bot.game import balance, production as prod
    pts = 0.0
    for k, qty in (items or {}).items():
        q = int(qty or 0)
        if q <= 0:
            continue
        if k == "gold":
            pts += q * GOLD_POINT_RATE
        elif k in prod.GOODS:
            pts += q * prod.GOODS[k].price
        elif k in balance.RESOURCE_PRICE:
            pts += q * balance.RESOURCE_PRICE[k]
    return int(pts)


def phase_target(base_target: int, active: int) -> int:
    """Цель фазы = базовая × активные (долгая стройка под размер мира; снимок при
    старте фазы в Wonder.target)."""
    return max(base_target, base_target * max(1, int(active)))


def effective_points(points: int, today_before: int) -> float:
    """Эффективные очки для конверсии в зодар: до дневного порога — полный курс,
    сверх — вдвое реже (убыв. отдача, анти-кит). today_before — очки за сегодня ДО."""
    if points <= 0:
        return 0.0
    room = max(0, DAILY_SOFT_CAP - max(0, today_before))
    full = min(points, room)
    return full + (points - full) / DIMINISHED_DIV


def _award_from_carry(carry: float, eff: float) -> tuple[int, float]:
    """Накопить эффективные очки в carry, выдать целые зодары, остаток перенести
    (как rep_progress — ни очка не пропадает)."""
    carry = max(0.0, carry) + max(0.0, eff)
    award = int(carry // ZODAR_PER_POINTS)
    return award, carry - award * ZODAR_PER_POINTS


def apply_contribution(wonder, pid: str, name: str, raw_points: int,
                       eff_points: float, active: int) -> dict:
    """Применить вклад к чуду (мутирует duck-typed объект с .key/.phase/.progress/
    .target/.contributions/.status). raw_points → ПРОГРЕСС и доска; eff_points (с
    дневной убыв. отдачей) → зодар через carry. Детектит закрытие фазы, завершение
    чуда и капстоун (чей вклад перевёл через порог). Возвращает
    {award, phase_done, wonder_done, capstone}. player.zodar/дневной учёт — снаружи."""
    wdef = WONDERS.get(wonder.key)
    contribs = dict(wonder.contributions or {})
    c = dict(contribs.get(pid) or {"pts": 0, "zodar": 0, "carry": 0.0})
    award, new_carry = _award_from_carry(float(c.get("carry", 0.0)), eff_points)
    c.update(pts=int(c.get("pts", 0)) + int(raw_points),
             zodar=int(c.get("zodar", 0)) + award, carry=new_carry,
             name=name)
    contribs[pid] = c
    wonder.contributions = contribs                 # переприсваивание — для JSONB

    before = int(wonder.progress or 0)
    after = before + max(0, int(raw_points))
    target = int(wonder.target or 0)
    phase_done = target > 0 and after >= target
    capstone = phase_done and before < target       # именно этот вклад закрыл фазу
    wonder_done = False
    if phase_done:
        last_phase = bool(wdef) and int(wonder.phase) >= len(wdef.phases)
        if last_phase:
            wonder.progress = target
            wonder.status = "sealing"   # вклады закрыты; бонус/буф доплатит нотифаер
            wonder_done = True
        else:                                        # перелив уносим в следующую фазу
            over = after - target
            wonder.phase = int(wonder.phase) + 1
            nb = wdef.phases[int(wonder.phase) - 1].base_target if wdef else target
            wonder.target = phase_target(nb, active)
            wonder.progress = over
    else:
        wonder.progress = after
    return {"award": award, "phase_done": phase_done,
            "wonder_done": wonder_done, "capstone": capstone}


def phase_bonus(contributions: dict | None) -> dict[str, int]:
    """Бонус зодаров вкладчикам фазы по перцентилю вклада (модель ED). Топ жмут
    больше, но и «хвост» что-то получает — награда за ШИРОТУ участия."""
    ranked = sorted(((pid, int(c.get("pts", 0)))
                     for pid, c in (contributions or {}).items()
                     if int(c.get("pts", 0)) > 0), key=lambda x: -x[1])
    n = len(ranked)
    out: dict[str, int] = {}
    for i, (pid, _pts) in enumerate(ranked):
        frac = (i + 1) / n
        mult = next(m for cut, m in BONUS_BRACKETS if frac <= cut)
        out[pid] = int(PHASE_BONUS_ZODAR * mult)
    return out


def active_bonuses(world) -> dict:
    """Глобальные буфы ГОТОВЫХ чудес — ЕДИНЫЙ источник (показ = действие). Читает
    world.live['wonders_done'] = [key,...]. Пусто → {}."""
    done = set((getattr(world, "live", None) or {}).get("wonders_done") or [])
    out: dict = {}
    if "wall" in done:
        out["invasion_escal_mult"] = WALL_ESCAL_MULT
    return out


def invasion_escal_mult(world) -> float:
    """Множитель СИЛЫ Орды от готовых чудес (Твердыня ×0.85 — Орда слабее). 1.0 — нет
    буфа. Вешаем на escal (он влияет на simulate), НЕ на threshold (тот на бой не
    влияет). Одна котировка и для механики (invasion), и для экрана."""
    return active_bonuses(world).get("invasion_escal_mult", 1.0)
