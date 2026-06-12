"""Игровой баланс: все числа в одном месте, чтобы легко крутить."""

# Регионы карты
REGIONS = {
    "north": "Северные холмы",
    "river": "Речная долина",
    "forest": "Лесной край",
    "trade": "Торговый тракт",
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

# Бонус региона к добыче (+50% к своему ресурсу)
REGION_BONUS = {
    "north": "wood",
    "river": "grain",
    "forest": "wood",
    "trade": "hops",
}

# Доход
INCOME_CAP_HOURS = 10  # доход копится максимум за 10 часов

# Улучшение таверны
MAX_LEVEL = 10


def expedition_yield(resource: str, level: int, region: str) -> int:
    base, per_level = EXPEDITION_YIELD[resource]
    amount = base + per_level * (level - 1)
    if REGION_BONUS.get(region) == resource:
        amount = int(amount * 1.5)
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
