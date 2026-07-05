"""Производство на пристройках (Ярус 1→2).

Партия масштабируется с уровнем таверны: вход и выход ×уровень. Один слот на
здание. Состояние партий — в tavern.production (JSONB), выход фиксируется в
момент запуска (level-snapshot), чтобы апгрейд во время варки не менял итог.

Шаг 2a: мельница (зерно→солод). Пивоварня — следующим шагом.
"""

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, buff, inventory, worldevent


def _scaled_inputs(base: dict, level: int) -> dict:
    """Вход рецепта × уровень × множитель затрат (вариант B). Округление вверх."""
    m = balance.PRODUCTION_INPUT_MULT
    return {k: math.ceil(v * level * m) for k, v in base.items()}

MATURE_CHANCE = 55  # % успеха выдержки (+1 ярус), иначе −1 ярус

# Грайндеры: сырьё → полуфабрикат в ИНВЕНТАРЬ (как мельница). Вход НЕ ×INPUT_MULT
# (передел сырья, а не товара). building -> recipe -> (вход/уровень, минуты, выход/уровень).
GRIND = {
    "mill": {
        "malt":  ({"grain": 10}, 40, 8),   # зерно → солод (для эля)
        "flour": ({"grain": 10}, 40, 8),   # зерно → мука (для выпечки)
    },
    "smelter": {
        "ingot": ({"ore": 6}, 90, 4),      # руда → слиток (для снаряги)
    },
}

# Рецептурные пристройки: вход → товар в ПОГРЕБ/кладовую (как кухня).
# Вход ×INPUT_MULT. building -> recipe(=ключ товара) -> (вход/уровень, часы, выход/уровень).
# Времена выровнены так, чтобы чистая прибыль/час (~12) была в одной лиге с
# существующими (жаркое/вино/медовуха) — без доминирующей стратегии. Реализм
# на стороне: копчение, выдержка сыра и сдобный пирог объективно небыстры.
RECIPES = {
    "bakery": {
        "bread": ({"flour": 8, "water": 6}, 5, 12),
        "pie":   ({"flour": 8, "berries": 6, "honey": 4}, 8, 10),
        # эксклюзив зодчих (Ф2b): рецепт из Лавки Артели, гейт по владению (EXCLUSIVE)
        "mason_loaf": ({"flour": 10, "milk": 6, "honey": 4, "salt": 3}, 8, 10),
    },
    "smokehouse": {
        "cured":       ({"game": 8, "salt": 4}, 8, 12),
        "smoked_fish": ({"fish": 10, "salt": 4}, 7, 12),
    },
    "dairy": {
        "cheese": ({"milk": 12, "salt": 3}, 10, 12),
        "butter": ({"milk": 14, "salt": 2}, 8, 12),
    },
}

PRODUCERS = ({"mill", "brewery", "meadery", "kitchen", "winery", "smelter"}
             | set(RECIPES))

# Кухня: рецепт -> (вход на 1 уровень, часы, выход порций на уровень)
KITCHEN = {
    "roast": ({"game": 6, "grain": 6, "herbs": 4}, 6, 12),  # Жаркое
    # эксклюзив зодчих (Ф2b): «Пир зодчих» — рецепт из Лавки Артели (EXCLUSIVE)
    "zodchy_feast": ({"game": 10, "herbs": 6, "honey": 5, "salt": 3}, 10, 10),
}

# Винокурня: рецепт -> (вход, часы, выход). Берри-тяжёлое премиум-вино.
WINERY = {
    "wine": ({"berries": 22, "honey": 6, "water": 6}, 12, 12),
    # эксклюзив зодчих (Ф2b): «Артельный нектар» — рецепт из Лавки Артели
    "artel_nectar": ({"berries": 24, "honey": 10, "herbs": 5}, 12, 10),
}

# Медоварня: рецепт -> (вход на 1 уровень, часы, выход кружек на уровень).
# Ключ рецепта = ключ напитка в погребе.
MEADERY = {
    "mead":   ({"honey": 10, "water": 8}, 8, 12),            # паритет 10×12/8=15/ч
    "sbiten": ({"honey": 8, "herbs": 6, "water": 6}, 10, 12),  # пряный премиум, травы
    # эксклюзив зодчих (Ф2b): «Громовой сбитень» — рецепт из Лавки Артели
    "thunder_sbiten": ({"honey": 12, "herbs": 8, "hops": 6, "water": 6}, 10, 10),
}

# ── Эксклюзив-рецепты зодчих (Ф2b) ────────────────────────────────────────
# Варить может ТОЛЬКО владелец рецепта, купленного в Лавке Артели за зодары
# (bind-on-earn, см. bot/game/artel_shop.py). Гейт двойной: в списке рецептов
# (webapi скрывает невладеемые) И в start_* (серверная защита ниже). ключ→здание.
EXCLUSIVE = {
    "zodchy_feast": "kitchen",
    "artel_nectar": "winery",
    "thunder_sbiten": "meadery",
    "mason_loaf": "bakery",
}


def owns_recipe(player, key: str) -> bool:
    """Куплен ли рецепт эксклюзив-товара (владение из Лавки Артели)."""
    from bot.game import artel_shop
    return artel_shop.owns_recipe(player, key)


def recipe_locked(player, key: str) -> bool:
    """Эксклюзив-рецепт, которым игрок ещё не владеет (варить нельзя)."""
    return key in EXCLUSIVE and not owns_recipe(player, key)


def npc_tradable(key: str) -> bool:
    """Продаётся ли товар НПС (розница гостям, заезжий купец, аукцион). Эксклюзив
    зодчих — НЕТ: имба ходит ТОЛЬКО P2P на бирже между игроками (не сливается НПС
    за золото и не выпивается гостями). Биржа проверяет владение отдельно."""
    return key not in EXCLUSIVE


def meadery_inputs(recipe: str, level: int) -> dict:
    return _scaled_inputs(MEADERY[recipe][0], level)


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
DRINKS["wine"] = Drink("wine", "🍷", "Вино", 15)
# эксклюзив зодчих (Ф2b): премиум-напитки, самые дорогие в погребе (берут богачи)
DRINKS["artel_nectar"] = Drink("artel_nectar", "🍷", "Артельный нектар", 35)
DRINKS["thunder_sbiten"] = Drink("thunder_sbiten", "⚡", "Громовой сбитень", 30)

# Еда (Кухня/Пекарня/Коптильня/Сыроварня): отдельный пул спроса (голод).
FOODS: dict[str, Drink] = {
    "roast": Drink("roast", "🍖", "Жаркое", 8),
    "bread": Drink("bread", "🥖", "Хлеб", 6),
    "pie": Drink("pie", "🥧", "Пирог", 12),
    "cured": Drink("cured", "🥓", "Солонина", 10),
    "smoked_fish": Drink("smoked_fish", "🐠", "Копчёная рыба", 9),
    "cheese": Drink("cheese", "🧀", "Сыр", 12),
    "butter": Drink("butter", "🧈", "Масло", 10),
    # эксклюзив зодчих (Ф2b): премиум-стол
    "zodchy_feast": Drink("zodchy_feast", "🍗", "Пир зодчих", 30),
    "mason_loaf": Drink("mason_loaf", "🍞", "Каравай каменщика", 28),
}

# Всё, что лежит в погребе/кладовой (для ВВП и названий при сбыте)
GOODS: dict[str, Drink] = {**DRINKS, **FOODS}


def ale_key(tier: int) -> str:
    return f"ale{tier}"


def brew_inputs(tier: int, level: int) -> dict:
    return _scaled_inputs(BREW[tier][0], level)


def brew_hours(tier: int) -> int:
    return BREW[tier][1]


def brew_output(tier: int, level: int) -> int:
    return BREW[tier][2] * level


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ready_at(player, *, hours: float = 0, minutes: float = 0) -> str:
    """Время готовности партии с учётом бафа «Спорая варка» (−20% времени)."""
    m = buff.prod_speed_mult(player) * worldevent.prod_speed_mult(player)  # +Ненастье
    return (_now() + timedelta(hours=hours * m, minutes=minutes * m)).isoformat()


# ── Грайндеры (мельница/горн): сырьё → полуфабрикат в инвентарь ───────────
def grind_inputs(building: str, recipe: str, level: int) -> dict:
    return {k: v * level for k, v in GRIND[building][recipe][0].items()}


def grind_minutes(building: str, recipe: str) -> int:
    return GRIND[building][recipe][1]


def grind_output(building: str, recipe: str, level: int) -> int:
    return GRIND[building][recipe][2] * level


def start_grind(player, tavern, building: str, recipe: str
                ) -> tuple[bool, str, dict | None]:
    """(ok, reason, inputs). reason: unknown | busy | not_enough."""
    if building not in GRIND or recipe not in GRIND[building]:
        return False, "unknown", None
    if state(tavern, building)[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = grind_inputs(building, recipe, level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, building, {
        "out_res": recipe,  # ключ полуфабриката = ключ рецепта (malt/flour/ingot)
        "out_qty": grind_output(building, recipe, level),
        "ready_at": _ready_at(player, minutes=grind_minutes(building, recipe)),
    })
    return True, "", cin


def claim_grind(player, tavern, building: str) -> tuple[str, int] | None:
    """Забрать готовый полуфабрикат в инвентарь. (ресурс, кол-во) или None."""
    if state(tavern, building)[0] != "ready":
        return None
    batch = (tavern.production or {})[building]
    res = batch.get("out_res", "malt")
    qty = int(batch.get("out_qty", 0))
    inventory.add(player, res, qty)
    _set_batch(tavern, building, None)
    return res, qty


# ── Рецептурные пристройки (пекарня/коптильня/сыроварня): вход → товар ─────
def recipe_inputs(building: str, recipe: str, level: int) -> dict:
    return _scaled_inputs(RECIPES[building][recipe][0], level)


def recipe_hours(building: str, recipe: str) -> int:
    return RECIPES[building][recipe][1]


def recipe_output(building: str, recipe: str, level: int) -> int:
    return RECIPES[building][recipe][2] * level


def start_recipe(player, tavern, building: str, recipe: str
                 ) -> tuple[bool, str, dict | None]:
    """(ok, reason, inputs). reason: unknown | locked | busy | not_enough."""
    if building not in RECIPES or recipe not in RECIPES[building]:
        return False, "unknown", None
    if recipe_locked(player, recipe):             # эксклюзив без рецепта из Лавки
        return False, "locked", None
    if state(tavern, building)[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = recipe_inputs(building, recipe, level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, building, {
        "recipe": recipe,
        "out_qty": recipe_output(building, recipe, level),
        "ready_at": _ready_at(player, hours=recipe_hours(building, recipe)),
    })
    return True, "", cin


def claim_recipe(player, tavern, building: str) -> tuple[str, int] | None:
    """Разлить/забрать готовый товар в погреб. (ключ товара, кол-во) или None."""
    if state(tavern, building)[0] != "ready":
        return None
    batch = (tavern.production or {})[building]
    recipe = batch.get("recipe")
    qty = int(batch.get("out_qty", 0))
    products = dict(tavern.products or {})
    products[recipe] = products.get(recipe, 0) + qty
    tavern.products = products
    _set_batch(tavern, building, None)
    return recipe, qty


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
        "ready_at": _ready_at(player, hours=brew_hours(tier)),
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
    batch["ready_at"] = _ready_at(player, hours=brew_hours(tier))
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
    """(ok, reason, inputs). reason: unknown | locked | busy | not_enough."""
    if recipe not in MEADERY:
        return False, "unknown", None
    if recipe_locked(player, recipe):
        return False, "locked", None
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
        "ready_at": _ready_at(player, hours=meadery_hours(recipe)),
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


def kitchen_inputs(recipe: str, level: int) -> dict:
    return _scaled_inputs(KITCHEN[recipe][0], level)


def kitchen_hours(recipe: str) -> int:
    return KITCHEN[recipe][1]


def kitchen_output(recipe: str, level: int) -> int:
    return KITCHEN[recipe][2] * level


def start_kitchen(player, tavern, recipe: str) -> tuple[bool, str, dict | None]:
    if recipe not in KITCHEN:
        return False, "unknown", None
    if recipe_locked(player, recipe):
        return False, "locked", None
    if state(tavern, "kitchen")[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = kitchen_inputs(recipe, level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, "kitchen", {
        "recipe": recipe,
        "out_qty": kitchen_output(recipe, level),
        "ready_at": _ready_at(player, hours=kitchen_hours(recipe)),
    })
    return True, "", cin


def claim_kitchen(player, tavern) -> tuple[str, int] | None:
    if state(tavern, "kitchen")[0] != "ready":
        return None
    batch = (tavern.production or {})["kitchen"]
    recipe = batch.get("recipe", "roast")
    qty = int(batch.get("out_qty", 0))
    products = dict(tavern.products or {})
    products[recipe] = products.get(recipe, 0) + qty
    tavern.products = products
    _set_batch(tavern, "kitchen", None)
    return recipe, qty


def winery_inputs(recipe: str, level: int) -> dict:
    return _scaled_inputs(WINERY[recipe][0], level)


def winery_hours(recipe: str) -> int:
    return WINERY[recipe][1]


def winery_output(recipe: str, level: int) -> int:
    return WINERY[recipe][2] * level


def start_winery(player, tavern, recipe: str) -> tuple[bool, str, dict | None]:
    if recipe not in WINERY:
        return False, "unknown", None
    if recipe_locked(player, recipe):
        return False, "locked", None
    if state(tavern, "winery")[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = winery_inputs(recipe, level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, "winery", {
        "recipe": recipe,
        "out_qty": winery_output(recipe, level),
        "ready_at": _ready_at(player, hours=winery_hours(recipe)),
    })
    return True, "", cin


def claim_winery(player, tavern) -> tuple[str, int] | None:
    if state(tavern, "winery")[0] != "ready":
        return None
    batch = (tavern.production or {})["winery"]
    recipe = batch.get("recipe", "wine")
    qty = int(batch.get("out_qty", 0))
    products = dict(tavern.products or {})
    products[recipe] = products.get(recipe, 0) + qty
    tavern.products = products
    _set_batch(tavern, "winery", None)
    return recipe, qty


def products_value(tavern) -> int:
    """Стоимость напитков и еды в погребе/кладовой (для ВВП)."""
    total = 0
    for key, qty in (tavern.products or {}).items():
        g = GOODS.get(key)
        if g:
            total += g.price * qty
    return int(total)
