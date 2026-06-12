"""Игровой баланс: все числа в одном месте, чтобы легко крутить."""

# Регионы карты
REGIONS = {
    "north": "Северные холмы",
    "river": "Речная долина",
    "forest": "Лесной край",
    "trade": "Торговый тракт",
}

# Сбор ресурсов
COLLECT_COOLDOWN_MIN = 30  # минут между сборами
COLLECT_BASE = {"wood": 6, "grain": 6, "hops": 3}  # за сбор на 1-м уровне

# Бонус региона к сбору (+50% к ресурсу)
REGION_BONUS = {
    "north": "wood",
    "river": "grain",
    "forest": "wood",
    "trade": "hops",
}

# Доход
INCOME_CAP_HOURS = 8  # доход копится максимум за 8 часов

# Улучшение таверны
MAX_LEVEL = 10


def collect_amount(resource: str, level: int, region: str) -> int:
    base = COLLECT_BASE[resource] + (level - 1) * 2
    if REGION_BONUS.get(region) == resource:
        base = int(base * 1.5)
    return base


def upgrade_cost(level: int) -> dict:
    """Стоимость перехода с level на level+1."""
    return {
        "gold": 100 * level * level,
        "wood": 20 * level,
        "grain": 15 * level,
        "hops": 10 * level,
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
