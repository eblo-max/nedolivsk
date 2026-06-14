"""Игровой баланс: все числа в одном месте, чтобы легко крутить."""

# Регионы карты
REGIONS = {
    "north_wilds": "Северная глушь",
    "green_valleys": "Зелёные долины",
    "red_wastes": "Красные пустоши",
}

# Ресурсы (Ярус 0 — сырьё). Порядок = порядок кнопок в меню вылазок.
RESOURCES = (
    "wood", "grain", "hops", "water", "honey",
    "berries", "game", "ore", "clay", "herbs",
)
RESOURCE_NAMES = {
    "wood": "Древесина", "grain": "Зерно", "hops": "Хмель",
    "water": "Вода", "honey": "Мёд", "berries": "Ягоды",
    "game": "Дичь", "ore": "Руда", "clay": "Глина", "herbs": "Травы",
}
RESOURCE_EMOJI = {
    "wood": "🪵", "grain": "🌾", "hops": "🌿", "water": "💧", "honey": "🍯",
    "berries": "🍒", "game": "🥩", "ore": "⛏", "clay": "🪨", "herbs": "🌶",
}

# Полуфабрикаты/продукты (не добываются вылазками, но имеют имя и ценность)
GOODS_NAMES = {"malt": "Солод"}
GOODS_EMOJI = {"malt": "🌱"}

# Стартовые запасы новой таверны
STARTING_INVENTORY = {"wood": 10, "grain": 10, "hops": 5}

# Вылазки работников: игрок отправляет их за ОДНИМ ресурсом на выбор
EXPEDITION_HOURS = 2
EXPEDITION_YIELD = {  # (база на 1-м уровне, прирост за уровень)
    "wood": (25, 6),
    "grain": (20, 5),
    "hops": (12, 3),
    "water": (30, 7),
    "honey": (10, 2),
    "berries": (18, 4),
    "game": (9, 2),
    "ore": (8, 2),
    "clay": (16, 4),
    "herbs": (12, 3),
}
WORKER_PAY_PER_LEVEL = 5  # плата работникам за вылазку: 5 * уровень таверны

# Специализация зон: ресурсы зоны +50%, «чужие» -25%, прочие — как у всех.
# Каждый ресурс ровно один раз усилен и один раз ослаблен — зоны равноценны.
# Вода (water) нейтральна везде — основа любой варки.
REGION_BONUS = {
    "north_wilds": {"wood", "game", "ore"},       # тайга, охота, рудники
    "green_valleys": {"grain", "honey", "berries"},  # пашни, пасеки, сады
    "red_wastes": {"hops", "herbs", "clay"},       # степь, коренья, глина
}
REGION_PENALTY = {
    "north_wilds": {"grain", "berries", "herbs"},  # мороз бьёт по посевам
    "green_valleys": {"hops", "ore", "clay"},      # ни гор, ни карьеров
    "red_wastes": {"wood", "game", "honey"},       # голо, зверья и цветов нет
}
BONUS_MULT = 1.5
PENALTY_MULT = 0.75

# Счастливые вылазки: шанс двойной добычи
LUCKY_BASE_CHANCE = 8    # % у голого игрока
LUCKY_MAX_CHANCE = 40    # потолок с любой удачей
LUCKY_MULT = 2           # множитель добычи


def lucky_chance(luck: int) -> int:
    return min(LUCKY_MAX_CHANCE, LUCKY_BASE_CHANCE + luck)


# Доход
INCOME_CAP_HOURS = 10  # доход копится максимум за 10 часов

# Мировое событие «Ярмарка»: раз в день, спрос ×2 на время
FAIR_HOUR_UTC = 18          # час начала (UTC)
FAIR_DURATION_HOURS = 3     # сколько длится
FAIR_DEMAND_MULT = 2.0      # множитель спроса во время ярмарки
FAIR_PRE_HOURS = 4          # за сколько часов до начала кидать анонс в чат

# ── Живой город: события, отношения, фракции ──────────────────────────────
EVENT_COOLDOWN_HOURS = 4      # минимум между личными событиями игрока
EVENT_CHANCE = 0.40          # шанс события при сборе дохода (если кулдаун прошёл)
NEWBIE_SHIELD_LEVEL = 3      # ниже этого уровня — иммун к городскому негативу
NEWBIE_SHIELD_HOURS = 48     # и/или первые двое суток после регистрации

NPC_REL_MIN, NPC_REL_MAX = -100, 100
FACTION_MIN, FACTION_MAX = -100, 100
REL_FRIEND = 40              # «свой» — лучше исходы, доп. выборы
REL_FOE = -40               # «враг» — хуже исходы, блокировки

# Ставки события — множитель от дохода/час таверны (самомасштабирование)
STAKE_MULT = {"petty": 1.0, "minor": 2.5, "serious": 5.0, "major": 10.0}


def stake(income_rate: int, tier: str) -> int:
    """Денежная ставка события данного тира (в золоте)."""
    return max(1, int(income_rate * STAKE_MULT.get(tier, 1.0)))


def loss_cap(gold: int, income_rate: int) -> int:
    """Потолок денежного убытка за одно событие — мягко, без ухода в минус."""
    return max(0, min(gold // 4, income_rate * 8))


# ── Симуляция фракций города (фаза 3) ──────────────────────────────────
FACTION_DECAY_PER_HOUR = 0.5   # дрейф силы фракции к 0 в час (без подпитки)
SITUATION_THRESHOLD = 50       # сила фракции, при которой в городе включается ситуация
SITUATION_DURATION_HOURS = 12  # сколько длится городская ситуация
SITUATION_COOLDOWN_HOURS = 6   # пауза после ситуации перед новой
CITY_POWER_FROM_REP = 0.5      # доля личной репутации фракции, перетекающей в силу города
MOOD_DRIFT_PER_HOUR = 3        # скорость дрейфа настроения города к цели
MOOD_DEMAND_DIV = 1000         # настроение -> спрос: 1 + mood/div (±10% на краях)

# Перки за стояние у фракций (≥ порога — «в доску свои»)
PERK_THRESHOLD = 50
PERK_MERCHANT_DEMAND = 1.15    # купцы: множитель сбыта
PERK_THIEVES_EXPEDITION = 0.85  # воры: множитель платы бригадам

# Сбыт напитков (Ярус 2 → доход): гости раскупают погреб
DEMAND_PER_CAPACITY = 0.5   # кружек/час спроса на единицу вместимости
# Сегментация клиентуры: доля состоятельных гостей растёт с репутацией.
# Они берут дорогое-первым, пьянь — дешёвое-первым.
PREMIUM_SHARE_MAX = 0.6     # потолок доли состоятельных
PREMIUM_REP_DIV = 300       # репутация / это = доля премиум-спроса (до потолка)
COMMONER_MAX_PRICE = 5      # пьянь берёт только дешёвое (≤ этой цены)
FOOD_DEMAND_PER_CAPACITY = 0.3  # порций/час спроса на единицу вместимости (голод)
REP_PER_ALE_SOLD = 25       # +1 репутации за столько проданных кружек/порций

# Улучшение таверны
MAX_LEVEL = 10


def expedition_yield(resource: str, level: int, region: str) -> int:
    base, per_level = EXPEDITION_YIELD[resource]
    amount = base + per_level * (level - 1)
    if resource in REGION_BONUS.get(region, ()):
        return int(amount * BONUS_MULT)
    if resource in REGION_PENALTY.get(region, ()):
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


# ===== ВВП (валовый продукт таверны) =====
# Рыночные цены ресурсов в золоте — обратно пропорциональны лёгкости добычи
RESOURCE_PRICE = {
    "water": 1.0, "wood": 2.0, "clay": 2.0, "grain": 2.5, "berries": 3.0,
    "hops": 4.0, "herbs": 4.5, "honey": 6.0, "game": 6.5, "ore": 7.0,
    # полуфабрикаты (для ВВП): солод ≈ зерну, из которого смолот (10🌾→8 солода,
    # 10×2.5/8≈3.1) — помол не создаёт богатства, его создаёт только продажа эля
    "malt": 3.1,
}


def invested_value(level: int) -> float:
    """Капитализация здания: всё золото и ресурсы, вложенные в уровни."""
    total = 0.0
    for lvl in range(1, level):
        c = upgrade_cost(lvl)
        total += c["gold"]
        for res, price in RESOURCE_PRICE.items():
            total += c.get(res, 0) * price
    return total


def tavern_gdp(
    inventory: dict, gold: int, level: int, income_rate: int, reputation: int,
) -> int:
    """ВВП таверны: активы + капитализация + дневной оборот + репутация."""
    assets = float(gold)
    for res, qty in (inventory or {}).items():
        assets += RESOURCE_PRICE.get(res, 0) * qty
    return int(
        assets
        + invested_value(level)
        + income_rate * 24
        + reputation * 3
    )
