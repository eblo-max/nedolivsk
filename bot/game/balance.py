"""Игровой баланс: все числа в одном месте, чтобы легко крутить."""

# Регионы карты
REGIONS = {
    "north_wilds": "Северная глушь",
    "green_valleys": "Зелёные долины",
    "red_wastes": "Красные пустоши",
}

# Ресурсы
RESOURCE_NAMES = {"wood": "Древесина", "grain": "Зерно", "hops": "Хмель"}
RESOURCE_EMOJI = {"wood": "🪵", "grain": "🌾", "hops": "🌿"}

# Вылазки работников: игрок отправляет их за ОДНИМ ресурсом на выбор
EXPEDITION_HOURS = 2
EXPEDITION_YIELD = {  # (база на 1-м уровне, прирост за уровень)
    "wood": (25, 6),
    "grain": (20, 5),
    "hops": (12, 3),
}
WORKER_PAY_PER_LEVEL = 5  # плата работникам за вылазку: 5 * уровень таверны

# Специализация зон: свой ресурс +50%, чужой -25%, третий — как у всех.
# Каждый ресурс ровно один раз усилен и один раз ослаблен — зоны равноценны,
# различается стратегия, а не сложность.
REGION_BONUS = {
    "north_wilds": "wood",      # тайга
    "green_valleys": "grain",   # пашни
    "red_wastes": "hops",       # дикий степной хмель
}
REGION_PENALTY = {
    "north_wilds": "hops",      # хмель не вызревает в холоде
    "green_valleys": "wood",    # леса вырублены под поля
    "red_wastes": "grain",      # зерно сохнет на жаре
}
BONUS_MULT = 1.5
PENALTY_MULT = 0.75

# Доход
INCOME_CAP_HOURS = 10  # доход копится максимум за 10 часов

# Улучшение таверны
MAX_LEVEL = 10


def expedition_yield(resource: str, level: int, region: str) -> int:
    base, per_level = EXPEDITION_YIELD[resource]
    amount = base + per_level * (level - 1)
    if REGION_BONUS.get(region) == resource:
        return int(amount * BONUS_MULT)
    if REGION_PENALTY.get(region) == resource:
        return max(1, int(amount * PENALTY_MULT))
    return amount


def worker_pay(level: int) -> int:
    return WORKER_PAY_PER_LEVEL * level


def upgrade_cost(level: int) -> dict:
    """Стоимость перехода с level на level+1."""
    return {
        "gold": 100 * level * level,
        "wood": 30 * level,
        "grain": 25 * level,
        "hops": 15 * level,
    }


def stats_for_level(level: int) -> dict:
    """Параметры таверны на уровне level."""
    return {
        "capacity": 10 + (level - 1) * 5,
        "comfort": level,
        "income_rate": 10 + (level - 1) * 8,  # золото в час
    }


def reputation_for_upgrade(new_level: int) -> int:
    return new_level * 5
