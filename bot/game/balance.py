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
WORKER_PAY_PER_LEVEL = 10  # плата работникам за вылазку: 10 * уровень таверны

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
# Кулдаун событий — СЛУЧАЙНЫЙ: то густо (всплеск), то пусто (затишье).
EVENT_COOLDOWN_MIN_HOURS = 0.5   # самый короткий кулдаун (во всплеске)
EVENT_COOLDOWN_MAX_HOURS = 9.0   # самый длинный (в затишье)
EVENT_BURST_CHANCE = 0.30        # шанс «всплеска» — короткий кулдаун подряд
EVENT_BURST_MAX_HOURS = 1.5      # граница «короткого» кулдауна
EVENT_CHANCE = 0.45          # шанс события при сборе дохода (если кулдаун прошёл)
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

# Сезоны (фаза 4c): игровой цикл, неделя на сезон, 28-дневный «год»
SEASON_LENGTH_DAYS = 7
HOLIDAY_DEMAND = 1.5           # множитель спроса в праздник

# Торг с купцами (гибрид A+D). Частота заземлена на рыночный городок:
# в обычный день оптовый покупатель заходит редко (~раз в сутки при сборе
# дохода 3–5 раз/день), а ярмарка — рыночный день, когда съезжаются торговцы.
TRADE_CHANCE = 0.20           # шанс прихода покупателя при сборе дохода
TRADE_FAIR_CHANCE = 0.60     # шанс на ярмарке (рыночный день — торг кипит)
TRADE_FAIR_FV_MULT = 1.2     # ярмарка поднимает справедливую цену
TRADE_MAX_OVER = 1.8         # потолок цены покупателя (×fv) — анти-гужёвка
TRADE_MIN_UNDER = 0.6        # пол цены покупателя (×fv)
TRADE_PRICE_TIERS = (0.85, 1.05, 1.4)  # дёшево / по рынку / дорого (× fv)
TRADE_COUNTER_MARGIN = 1.25  # просишь не более +25% к потолку -> купец контрит
TRADE_QTY_MIN = 3
TRADE_QTY_MAX = 10

# Динамический рынок: оптовая цена (fv) дышит в обе стороны и впитывается.
# Завал (glut) — баланс рынка: >0 товар выброшен (цена вниз), <0 дефицит/скупка
# (цена вверх). Тает экспоненциально к 0, как рынок впитывает перекос.
MARKET_SATURATION = 160     # завал, при котором цена падает до пола
MARKET_PRICE_FLOOR = 0.55   # минимум множителя fv при заваленном рынке
MARKET_SHORTAGE = 120       # дефицит (−glut), при котором цена на потолке
MARKET_PRICE_CEIL = 1.35    # максимум множителя fv при дефиците/ажиотаже
MARKET_ABSORB_HOURS = 14    # постоянная времени впитывания перекоса (τ)
# Климат спроса: настроение города и активная фракционная ситуация двигают
# ОПТОВУЮ цену (купеческий бум ↑, пост ↓) — и в показе, и в реальных сделках.
MARKET_MOOD_DIV = 500       # настроение → опт: 1 + mood/div (±20% на краях)
MARKET_SITUATION_WEIGHT = 0.5  # доля влияния ситуации на опт (смягчение от розницы)
MARKET_CLIMATE_MIN = 0.75   # пол климата спроса
MARKET_CLIMATE_MAX = 1.25   # потолок климата спроса
# Вклад в перекос рынка: оптовый сброс купцу — полный сигнал предложения;
# розница гостям — конечное потребление, лишь слабый признак изобилия товара.
MARKET_WHOLESALE_WEIGHT = 1.0
MARKET_RETAIL_WEIGHT = 0.4


def market_factor(glut: float) -> float:
    """Множитель справедливой цены от перекоса рынка: завал → пол, дефицит → потолок."""
    if glut > 0:
        drop = min(1.0, glut / MARKET_SATURATION)
        return round(1.0 - drop * (1.0 - MARKET_PRICE_FLOOR), 3)
    if glut < 0:
        up = min(1.0, -glut / MARKET_SHORTAGE)
        return round(1.0 + up * (MARKET_PRICE_CEIL - 1.0), 3)
    return 1.0


# Пульс рынка: иногда горожанин двигает спрос/предложение своими делами.
# Заземлено на рыночный городок (~58 именитых душ ≈ 1.5–2.5 тыс. населения):
# заметная рыночная новость — как от глашатая, примерно раз в сутки, не чаще.
# Тик нотифаера = 60с → 1440 тиков/сутки; 0.0008 × 1440 ≈ 1.2 события/сутки.
MARKET_PULSE_CHANCE = 0.0008


# Порча погреба: излишек товара сверх вместимости киснет (давление сбывать).
CELLAR_FREE_PER_CAP = 8     # единиц товара на 1 место, что хранятся свежими
SPOIL_PCT_PER_DAY = 0.35    # доля ИЗЛИШКА сверх вместимости, киснущая в сутки


def cellar_capacity(capacity: int) -> int:
    """Сколько товара погреб держит свежим (сверх — портится)."""
    return max(1, int(capacity * CELLAR_FREE_PER_CAP))


# Аукцион (асинхронный сбыт со ставками). Лот живёт сам: нотифаер катит,
# не зайдёт ли горожанин и не перебьёт ли цену. Кто и насколько щедро ставит —
# те же архетипы + настроение города + дефицит рынка + ярмарка. Потолок ставки
# тот же, что у купца (fv×TRADE_MAX_OVER) — без новых эксплойтов.
AUCTION_DURATION_HOURS = 6     # сколько идут торги
AUCTION_QTY_MAX = 20           # максимум в одном лоте
AUCTION_BID_CHANCE = 0.014     # шанс ставки на лот за тик (~5 ставок за 6ч)
AUCTION_FAIR_BID_MULT = 2.0    # на ярмарке ставят вдвое охотнее
AUCTION_BID_STEP = 0.06        # шаг перебивки (× fv). Настроение уже в fv (климат).
AUCTION_PRICE_TIERS = (1.0, 1.2, 1.4)  # стартовая цена: по рынку / бодро / дорого
AUCTION_QTY_PRESETS = (5, 10, 20)      # пресеты объёма лота


# Перки за стояние у фракций (≥ порога — «в доску свои»)
PERK_THRESHOLD = 50
PERK_MERCHANT_DEMAND = 1.15    # купцы: множитель сбыта
PERK_THIEVES_EXPEDITION = 0.85  # воры: множитель платы бригадам

# Подкидыш в общий чат: иногда что-то «теряется», кто первый нажал — подобрал.
LOOT_DROP_CHANCE = 0.0167     # шанс подкидыша на чат за тик (~раз в час на чат)
LOOT_RESOURCE_CHANCE = 0.45   # доля исхода «ресурс»
LOOT_NOTHING_CHANCE = 0.25    # доля «пусто» (остальное — хлам)
LOOT_QTY_MIN = 3
LOOT_QTY_MAX = 7
LOOT_EXPIRE_MINUTES = 60      # сколько подкидыш «лежит», потом сгнил


# Сбыт напитков (Ярус 2 → доход): гости раскупают погреб
DEMAND_PER_CAPACITY = 0.5   # кружек/час спроса на единицу вместимости
# Сегментация клиентуры: доля состоятельных гостей растёт с репутацией.
# Они берут дорогое-первым, пьянь — дешёвое-первым.
PREMIUM_SHARE_MAX = 0.6     # потолок доли состоятельных
PREMIUM_REP_DIV = 300       # репутация / это = доля премиум-спроса (до потолка)
COMMONER_MAX_PRICE = 5      # пьянь берёт только дешёвое (≤ этой цены)
FOOD_DEMAND_PER_CAPACITY = 0.3  # порций/час спроса на единицу вместимости (голод)
REP_PER_ALE_SOLD = 25       # +1 репутации за столько проданных кружек/порций

# Производство: множитель ВХОДА рецептов (вариант B). Выход не трогаем —
# доход/час паритетный (15·L), но сырья на партию больше → больше вылазок.
PRODUCTION_INPUT_MULT = 1.75

# Охота/бой: снаряга наконец работает (урон/крит/броня из items.combat_stats).
BASE_HP = 35                # база здоровья охотника (фикс на бой)
BASE_DAMAGE = 3             # кулаки (без оружия)
ARMOR_DR_DIV = 3           # броня режет входящий урон: −armor//div за удар
HUNT_MAX_ROUNDS = 20        # не убил за столько — поражение (зверь силён)
HUNT_COOLDOWN_MINUTES = 45  # пауза между охотами (после победы)
HUNT_WOUND_HOURS = 2        # ранение при поражении — дольше не охотишься
HUNT_CRIT_CAP = 75          # потолок шанса крита, %
HUNT_LOSS_GOLD_DIV = 10     # при поражении теряешь до gold//div (щепотка)


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
    """Стоимость перехода с level на level+1 (вариант B: ~3× к прежнему)."""
    return {
        "gold": 250 * level * level,
        "wood": 75 * level,
        "grain": 60 * level,
        "hops": 40 * level,
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
