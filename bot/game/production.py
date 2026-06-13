"""Производство на пристройках (Ярус 1→2).

Партия масштабируется с уровнем таверны: вход и выход ×уровень. Один слот на
здание. Состояние партий — в tavern.production (JSONB), выход фиксируется в
момент запуска (level-snapshot), чтобы апгрейд во время варки не менял итог.

Шаг 2a: мельница (зерно→солод). Пивоварня — следующим шагом.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import inventory

MATURE_CHANCE = 55  # % успеха выдержки (+1 ярус), иначе −1 ярус

PRODUCERS = {"mill", "brewery", "meadery"}  # здания с производством

MILL_MINUTES = 40
MILL_GRAIN = 10   # зерна на 1 уровень
MILL_MALT = 8     # солода на 1 уровень

# Медоварня: рецепт -> (вход на 1 уровень, часы, выход кружек на уровень).
# Ключ рецепта = ключ напитка в погребе.
MEADERY = {
    "mead":   ({"honey": 10, "water": 8}, 8, 12),            # паритет 10×12/8=15/ч
    "sbiten": ({"honey": 8, "herbs": 6, "water": 6}, 10, 12),  # пряный премиум, травы
}


def meadery_inputs(recipe: str, level: int) -> dict:
    return {k: v * level for k, v in MEADERY[recipe][0].items()}


def meadery_hours(recipe: str) -> int:
    return MEADERY[recipe][1]


def meadery_output(recipe: str, level: int) -> int:
    return MEADERY[recipe][2] * level

# Пивоварня: ярус -> (вход на 1 уровень, часы ферментации, выход кружек на уровень)
BREW = {
    1: ({"malt": 8, "hops": 5, "water": 6}, 4, 12),
    2: ({"malt": 8, "hops": 5, "water": 6, "honey": 6}, 8, 12),
    3: ({"malt": 8, "hops": 5, "water": 6, "honey": 12}, 12, 12),
}
# Цена ∝ ферментации (4/8/12 ч) → доход/час одинаков у всех ярусов (15×уровень):
# ярус — выбор по ВВП-марже / мёду / спросу, а не доминирование по золоту.
ALE_PRICE = {1: 5, 2: 10, 3: 15}    # цена за кружку (доход и ВВП)
ALE_STARS = {1: "★", 2: "★★", 3: "★★★"}


@dataclass(frozen=True)
class Drink:
    key: str       # ключ в погребе (tavern.products)
    emoji: str
    name: str
    price: int     # цена за кружку (доход + ВВП)


# Единый реестр напитков. Эль — из ярусов; медовуха добавится в Медоварне.
DRINKS: dict[str, Drink] = {
    f"ale{t}": Drink(f"ale{t}", "🍺", f"Эль {ALE_STARS[t]}", ALE_PRICE[t])
    for t in (1, 2, 3)
}
DRINKS["mead"] = Drink("mead", "🍶", "Медовуха", 10)
DRINKS["sbiten"] = Drink("sbiten", "🌿", "Сбитень", 13)


def ale_key(tier: int) -> str:
    return f"ale{tier}"


def brew_inputs(tier: int, level: int) -> dict:
    return {k: v * level for k, v in BREW[tier][0].items()}


def brew_hours(tier: int) -> int:
    return BREW[tier][1]


def brew_output(tier: int, level: int) -> int:
    return BREW[tier][2] * level


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mill_inputs(level: int) -> dict:
    return {"grain": MILL_GRAIN * level}


def mill_output(level: int) -> int:
    return MILL_MALT * level


def state(tavern, building: str) -> tuple[str, int]:
    """("none"|"active"|"ready", минут до готовности)."""
    batch = (tavern.production or {}).get(building)
    if not batch or not batch.get("ready_at"):
        return "none", 0
    left = (datetime.fromisoformat(batch["ready_at"]) - _now()).total_seconds()
    if left > 0:
        return "active", int(left // 60) + 1
    return "ready", 0


def _set_batch(tavern, building: str, batch: dict | None) -> None:
    prod = dict(tavern.production or {})
    if batch is None:
        prod.pop(building, None)
    else:
        prod[building] = batch
    tavern.production = prod  # переприсваивание — чтобы JSONB заметил


def start_mill(player, tavern) -> tuple[bool, str, dict | None]:
    """(ok, reason, inputs). reason: busy | not_enough."""
    if state(tavern, "mill")[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = mill_inputs(level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, "mill", {
        "out_res": "malt",
        "out_qty": mill_output(level),
        "ready_at": (_now() + timedelta(minutes=MILL_MINUTES)).isoformat(),
    })
    return True, "", cin


def claim_mill(player, tavern) -> int:
    """Забрать готовый солод в инвентарь. Возвращает количество (0 — нечего)."""
    if state(tavern, "mill")[0] != "ready":
        return 0
    batch = (tavern.production or {})["mill"]
    qty = int(batch.get("out_qty", 0))
    inventory.add(player, batch.get("out_res", "malt"), qty)
    _set_batch(tavern, "mill", None)
    return qty


def start_brew(player, tavern, tier: int) -> tuple[bool, str, dict | None]:
    """(ok, reason, inputs). reason: unknown | busy | not_enough."""
    if tier not in BREW:
        return False, "unknown", None
    if state(tavern, "brewery")[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = brew_inputs(tier, level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, "brewery", {
        "tier": tier,
        "out_qty": brew_output(tier, level),
        "ready_at": (_now() + timedelta(hours=brew_hours(tier))).isoformat(),
    })
    return True, "", cin


def _brew_grace_minutes(tier: int) -> int:
    """Окно безопасного разлива после созревания выдержки."""
    return max(120, brew_hours(tier) * 60 // 2)


def brew_phase(tavern) -> tuple[str, int]:
    """Фаза пивоварни: empty|fermenting|ready|aging|ripe|overripe + минуты.
    Для 'ripe' минуты — сколько осталось разлить до перекисания."""
    batch = (tavern.production or {}).get("brewery")
    if not batch:
        return "empty", 0
    ready = datetime.fromisoformat(batch["ready_at"])
    left = (ready - _now()).total_seconds()
    if batch.get("stage", "ferment") == "ferment":
        return ("fermenting", int(left // 60) + 1) if left > 0 else ("ready", 0)
    # выдержка
    if left > 0:
        return "aging", int(-(-left // 60))
    over_min = (-left) / 60
    grace = _brew_grace_minutes(int(batch["tier"]))
    if over_min <= grace:
        return "ripe", int(grace - over_min) + 1
    return "overripe", 0


def start_age(player, tavern) -> bool:
    """Поставить готовый эль на выдержку (только если ярус < макс)."""
    if brew_phase(tavern)[0] != "ready":
        return False
    batch = dict((tavern.production or {})["brewery"])
    tier = int(batch["tier"])
    if tier >= 3:
        return False
    batch["stage"] = "aging"
    batch["ready_at"] = (_now() + timedelta(hours=brew_hours(tier))).isoformat()
    batch.pop("notified", None)
    _set_batch(tavern, "brewery", batch)
    return True


def claim_brew(player, tavern) -> tuple[str, int, int] | None:
    """Разлить эль. Возвращает (исход, ярус, кол-во):
    bottled | matured | soured | lost. None — ещё не готово."""
    phase, _ = brew_phase(tavern)
    batch = (tavern.production or {}).get("brewery")
    if batch is None or phase in ("fermenting", "aging", "empty"):
        return None
    tier = int(batch["tier"])
    qty = int(batch.get("out_qty", 0))

    if phase == "ready":
        outcome, out_tier = "bottled", tier
    elif phase == "ripe" and random.randint(1, 100) <= MATURE_CHANCE:
        outcome, out_tier = "matured", min(3, tier + 1)
    else:  # ripe-fail или overripe — скисло на ступень
        outcome, out_tier = "soured", tier - 1

    if out_tier >= 1 and qty > 0:
        key = ale_key(out_tier)
        products = dict(tavern.products or {})
        products[key] = products.get(key, 0) + qty
        tavern.products = products
    else:
        outcome, qty = "lost", 0

    _set_batch(tavern, "brewery", None)
    return outcome, out_tier, qty


def start_meadery(player, tavern, recipe: str) -> tuple[bool, str, dict | None]:
    """(ok, reason, inputs). reason: unknown | busy | not_enough."""
    if recipe not in MEADERY:
        return False, "unknown", None
    if state(tavern, "meadery")[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = meadery_inputs(recipe, level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, "meadery", {
        "recipe": recipe,
        "out_qty": meadery_output(recipe, level),
        "ready_at": (_now() + timedelta(hours=meadery_hours(recipe))).isoformat(),
    })
    return True, "", cin


def claim_meadery(player, tavern) -> tuple[str, int] | None:
    """Разлить готовый напиток медоварни. Возвращает (ключ, количество)."""
    if state(tavern, "meadery")[0] != "ready":
        return None
    batch = (tavern.production or {})["meadery"]
    recipe = batch.get("recipe", "mead")
    qty = int(batch.get("out_qty", 0))
    products = dict(tavern.products or {})
    products[recipe] = products.get(recipe, 0) + qty
    tavern.products = products
    _set_batch(tavern, "meadery", None)
    return recipe, qty


def products_value(tavern) -> int:
    """Стоимость напитков в погребе (для ВВП)."""
    total = 0
    for key, qty in (tavern.products or {}).items():
        d = DRINKS.get(key)
        if d:
            total += d.price * qty
    return int(total)
