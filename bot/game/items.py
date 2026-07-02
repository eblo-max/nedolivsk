"""Экипировка: каталог предметов, бонусы к экономике, боевые статы.

Боевые статы (damage, crit, armor, luck) пока копятся «впрок» —
заработают, когда появится охота.
Картинки предметов: assets/items/<item_id>.png (прозрачный фон).
"""

import hashlib
import math
from dataclasses import dataclass


def _stable(key: str, lo: int, hi: int) -> int:
    """Детерминированное «случайное» число в [lo, hi] по ключу (стабильно между
    запусками — на hashlib, не на builtin hash, который солится PYTHONHASHSEED)."""
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return lo + h % (hi - lo + 1)


@dataclass(frozen=True)
class Item:
    id: str
    slot: str               # слот на кукле
    name: str
    description: str        # жёсткий трактирный тон
    cost: dict              # gold/wood/grain/hops
    craft_hours: int
    sprite: str = ""        # имя файла арта в assets/items (без .png); "" = по id
    craftable: bool = True  # False — эксклюзив, только с рейд-боссов; в кузнице нет
    # экономика
    income_pct: int = 0         # +% к доходу таверны
    yield_pct: int = 0          # +% к добыче вылазок (все ресурсы)
    yield_wood_pct: int = 0     # +% только к древесине
    speed_pct: int = 0          # -% к времени вылазки
    pay_discount_pct: int = 0   # -% к плате работникам
    # бой
    damage: int = 0
    crit: int = 0
    armor: int = 0
    luck: int = 0
    vitality: int = 0       # +HP к максимуму здоровья (ось живучести «мясом»)


SLOTS = {
    "head": "Голова",
    "chest": "Грудь",
    "left_hand": "Левая рука",
    "right_hand": "Правая рука",
    "weapon": "Оружие",
    "belt": "Пояс",
    "legs": "Ноги",
    "boots": "Сапоги",
    "amulet": "Амулет",
    "talisman": "Талисман",
    "bag": "Сумка",
}

# ВРЕМЕННО для теста: вещи бесплатны и куются мгновенно.
# Перед боевым запуском поставить False!
TEST_FREE_CRAFT = False

# ===== Ярусы качества =====
TIER_MAX = 3
TIER_NAMES = {1: "обычный", 2: "добротный", 3: "мастерский"}
TIER_STARS = {1: "★", 2: "★★", 3: "★★★"}
TIER_COST_MULT = {1: 1, 2: 3, 3: 8}     # цена ковки данного яруса
TIER_INVESTED = {1: 1, 2: 4, 3: 12}     # суммарно вложено к ярусу (для ВВП)
# «Сжатие ярусов» (боевой пересмотр): раньше ярус множил ВСЕ статы ×1/×2/×3 —
# разрыв ветеран/новичок доходил до 6× и рвал co-op (орда/рейд) и полосы контента.
# Best practice социальных игр — держать разрыв ~2-3×. Боевые статы растут круче
# экономических (бой — главная ось яруса, экономика — приятный довесок).
TIER_COMBAT_MULT = {1: 1.0, 2: 1.6, 3: 2.2}
TIER_ECON_MULT = {1: 1.0, 2: 1.3, 3: 1.6}


def _cmul(v: int, tier: int) -> int:
    """Боевой стат с учётом яруса (округление вниз, минимум сохраняет знак)."""
    return int(v * TIER_COMBAT_MULT[tier])


def _emul(pct: int, tier: int) -> int:
    return int(pct * TIER_ECON_MULT[tier])


# ===== Бюджет статов предмета (WoW-lite itemization) =====
# «Очки силы»: сколько бюджета съедает 1 ед. стата. Проверяется тестом
# tests/test_itemization.py — предмет вне допуска бюджета не пройдёт CI.
STAT_WEIGHTS = {
    "damage": 1.0, "crit": 1.2, "armor": 0.7, "luck": 1.0, "vitality": 1.0,
    "income_pct": 1.5, "yield_pct": 1.2, "yield_wood_pct": 0.6,
    "speed_pct": 1.2, "pay_discount_pct": 0.8,
}
# Бюджет слота на ★ (кузня, множитель источника 1.0).
SLOT_BUDGET = {
    "weapon": 26, "chest": 22, "right_hand": 14, "left_hand": 14,
    "head": 12, "legs": 12, "boots": 12, "belt": 12,
    "amulet": 12, "talisman": 12, "bag": 10,
}
# Множитель источника: чем труднее добыть, тем жирнее бюджет.
SOURCE_MULT = {
    "forge": 1.0,        # стартовая кузня
    "hunt": 1.25,        # компоненты охоты
    "region": 1.2,       # региональные пояса
    "orc": 1.45,         # орочий сет (сет-бонус — сверх бюджета, за сбор)
    "raid_rat": 1.35, "raid_troll": 1.6, "raid_demon": 1.85, "raid_dragon": 2.1,
}
ITEM_SOURCE = {
    "skinner_knife": "hunt", "wolf_totem": "hunt",
    "fur_coat": "hunt", "fang_cleaver": "hunt", "swift_boots": "hunt", "prestige_ring": "hunt",
    "lynx_belt": "region", "tusk_belt": "region", "chitin_belt": "region",
    "orc_helm": "orc", "orc_plate": "orc", "orc_axe": "orc",
    "rat_crown": "raid_rat", "rat_pelt": "raid_rat", "rat_tail": "raid_rat",
    "troll_club": "raid_troll", "troll_hide": "raid_troll", "troll_eye": "raid_troll",
    "demon_fang": "raid_demon", "demon_hide": "raid_demon", "demon_core": "raid_demon",
    "dragon_fang": "raid_dragon", "dragon_scale": "raid_dragon", "dragon_heart": "raid_dragon",
}


def item_budget_points(item: "Item") -> float:
    """Сколько «очков силы» реально сидит в предмете (для теста бюджета)."""
    pts = 0.0
    for stat, w in STAT_WEIGHTS.items():
        pts += getattr(item, stat, 0) * w
    return pts


def item_budget_target(item: "Item") -> float:
    src = ITEM_SOURCE.get(item.id, "forge")
    return SLOT_BUDGET.get(item.slot, 12) * SOURCE_MULT[src]
# Множители цены ковки. Раздельно, чтобы крутить золото и сырьё независимо:
#   GEAR_COST_MULT  — золото (поднят против инфляции — золото обесценилось);
#   GEAR_RES_MULT   — ОБЫЧНОЕ сырьё (дерево/зерно/хмель/…): расход выше, чтобы ковка
#                     жгла ресурсы заметно (и была сток-цепочкой, а не «на сдачу»);
#   слиток и охот-компоненты (_SCARCE) НЕ раздуваем сверх золотого — они и так
#   редкие/гейт (горн, охота, региональный зверь), иначе ковка станет неподъёмной.
GEAR_COST_MULT = 1.5
GEAR_RES_MULT = 2.5
# Пол расхода ОБЫЧНОГО сырья на ★: у каждой вещи свой «живой» минимум в диапазоне
# [GEAR_RES_FLOOR, GEAR_RES_FLOOR_MAX] (детерминирован по предмету+ресурсу — 278/284/
# 269 и т.п., но стабилен). Ярус множит сверху (★ → ★★ ×3 → ★★★ ×8).
GEAR_RES_FLOOR = 250
GEAR_RES_FLOOR_MAX = 320
_SCARCE = {"ingot", "hide", "fang", "sinew", "ring", "pelt", "tusk", "chitin", "orc_scrap"}

# Орочий сет: полный комплект из 3 вещей даёт «ярость орды» — сильный боевой бонус
# (см. combat_stats) + немного дохода (income_multiplier). Сделан ЯВНО лучшим, т.к.
# собирается дольше всего (лотерея обрывков с побед над Ордой).
ORC_SET = ("orc_helm", "orc_plate", "orc_axe")
ORC_SET_BONUS = {"damage": 10, "crit": 6, "armor": 12, "luck": 6, "vitality": 10}
ORC_SET_INCOME_PCT = 5


PLUS_MAX = 5          # кап заточки
PLUS_STAT_PCT = 10    # шаг уровня: 10% от стата вещи, минимум +1 (дорого, но ощутимо)


def plus_bonus(v: int, plus: int) -> int:
    """Прибавка заточки: КАЖДЫЙ уровень даёт max(1, 10% стата) — плоский шаг,
    видимый на любом стате. +5 на крупном стате ≈ +50%, на мелком — +5."""
    if v <= 0 or plus <= 0:
        return 0
    return plus * max(1, round(v * PLUS_STAT_PCT / 100))


def item_combat_gain(entry: str, next_plus: int | None = None) -> dict:
    """Боевые статы вещи на текущей заточке (или дельта до next_plus) — для UI."""
    item_id, tier, plus, _aff = parse_full(entry)
    it = CATALOG.get(item_id)
    if it is None:
        return {}
    out = {}
    for k in ("damage", "crit", "armor", "luck", "vitality"):
        v = _cmul(getattr(it, k), tier)
        if v <= 0:
            continue
        if next_plus is None:
            out[k] = v + plus_bonus(v, plus)
        else:
            out[k] = plus_bonus(v, next_plus) - plus_bonus(v, plus)
    return {k: n for k, n in out.items() if n > 0}

# Аффиксы ковки: суффикс имени (родительный падеж — не зависит от рода вещи)
# + плоский боевой бонус ×ярус вещи. Ролл при заборе крафта T2+.
AFFIXES = {
    "zloby":      ("злобы",      {"damage": 2}),
    "kreposti":   ("крепости",   {"armor": 3}),
    "farta":      ("фарта",      {"luck": 1}),
    "zhivuchesti": ("живучести", {"vitality": 3}),
}


def parse_entry(entry: str) -> tuple[str, int]:
    """'kovsh:2' -> (kovsh, 2); полный формат см. parse_full."""
    item_id, tier, _plus, _aff = parse_full(entry)
    return item_id, tier


def parse_full(entry: str) -> tuple[str, int, int, str]:
    """'kovsh:2:3:zloby' -> (kovsh, ярус 2, заточка +3, аффикс zloby).
    Старые записи ('kovsh', 'kovsh:2') дополняются нулями — миграция не нужна."""
    parts = str(entry).split(":")

    def _num(idx: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(parts[idx])))
        except (IndexError, ValueError):
            return lo

    tier = _num(1, 1, TIER_MAX)
    plus = _num(2, 0, PLUS_MAX)
    aff = parts[3] if len(parts) > 3 and parts[3] in AFFIXES else ""
    return parts[0], tier, plus, aff


def make_entry(item_id: str, tier: int, plus: int = 0, affix: str = "") -> str:
    e = f"{item_id}:{tier}"
    if plus or affix:
        e += f":{plus}"
    if affix:
        e += f":{affix}"
    return e


def display_name(entry: str) -> str:
    """Имя вещи с аффиксом и заточкой: «Сабля стражника фарта +3»."""
    item_id, _tier, plus, aff = parse_full(entry)
    it = CATALOG.get(item_id)
    name = it.name if it else item_id
    if aff:
        name = f"{name} {AFFIXES[aff][0]}"
    if plus:
        name = f"{name} +{plus}"
    return name


def tier_cost(item: "Item", tier: int) -> dict:
    if TEST_FREE_CRAFT:
        return {k: 0 for k in item.cost}
    tmult = TIER_COST_MULT[tier]
    out = {}
    for k, v in item.cost.items():
        if not v:
            out[k] = 0
            continue
        if k == "gold" or k in _SCARCE:           # золото и редкое — без пола
            out[k] = max(1, math.ceil(v * tmult * GEAR_COST_MULT))
        else:                                     # обычное сырьё: «живой» пол на ★, ярус сверху
            floor = _stable(f"{item.id}:{k}", GEAR_RES_FLOOR, GEAR_RES_FLOOR_MAX)
            base1 = max(floor, math.ceil(v * GEAR_RES_MULT))
            out[k] = base1 * tmult
    return out


def tier_hours(item: "Item", tier: int) -> int:
    if TEST_FREE_CRAFT:
        return 0
    return item.craft_hours * tier


def equipped_tier(equipment: dict | None, item_id: str) -> int:
    """Какой ярус этого предмета надет (0 — не надет)."""
    if not equipment:
        return 0
    for entry in equipment.values():
        eid, tier = parse_entry(entry)
        if eid == item_id:
            return tier
    return 0


CATALOG: dict[str, Item] = {
    item.id: item
    for item in [
        Item(
            id="leather_cap", slot="head", name="Шапка трактирщика",
            description="Скрывает похмелье и лысину. Постояльцы доверяют.",
            cost={"gold": 300, "wood": 0, "grain": 30, "hops": 10},
            craft_hours=2, income_pct=4, armor=3, vitality=3, sprite="shapka",
        ),
        Item(
            id="fartuk", slot="chest", name="Фартук трактирщика",
            description="Пятна эля, жира и чьей-то крови. В основном эля.",
            cost={"gold": 700, "wood": 20, "grain": 40, "hops": 0},
            craft_hours=4, yield_pct=4, armor=12, vitality=6, sprite="bronya",
        ),
        Item(
            id="oak_shield", slot="left_hand", name="Щит дубовый",
            description="Им можно прикрыться, а можно подать на нём жаркое. "
                        "Окован железом — для крепости.",
            cost={"gold": 480, "wood": 40, "ingot": 8},
            craft_hours=3, pay_discount_pct=4, armor=12, vitality=4,
        ),
        Item(
            id="master_axe", slot="right_hand", name="Топор хозяйский",
            description="Дрова, разделка туш и последний аргумент в споре.",
            cost={"gold": 540, "wood": 30, "ingot": 8},
            craft_hours=3, yield_wood_pct=10, damage=8,
        ),
        Item(
            id="kovsh", slot="weapon", name="Ковш боевой",
            description="Черпает эль, проламывает черепа. Шипы — для убедительности.",
            cost={"gold": 1100, "wood": 20, "hops": 20, "ingot": 12},
            craft_hours=6, yield_pct=5, damage=13, crit=6, sprite="oruzhie",
        ),
        Item(
            id="poyas", slot="belt", name="Пояс мастеровой",
            description="Нож, молоток и кисти — всё хозяйство при себе.",
            cost={"gold": 350, "wood": 0, "grain": 20, "hops": 10},
            craft_hours=2, speed_pct=5, armor=4, vitality=2,
        ),
        Item(
            id="strong_pants", slot="legs", name="Портки крепкие",
            description="Не рвутся, даже когда бежишь от разбойников.",
            cost={"gold": 400, "wood": 0, "grain": 30, "hops": 5},
            craft_hours=2, speed_pct=5, armor=5, vitality=2,
        ),
        Item(
            id="sapogi", slot="boots", name="Сапоги рунные",
            description="Руны светятся, носы загнуты. Бегут почти сами.",
            cost={"gold": 800, "wood": 20, "grain": 0, "hops": 15},
            craft_hours=4, speed_pct=8, armor=3,
        ),
        Item(
            id="kruzhka", slot="amulet", name="Последняя капля",
            description="Кружка-оберег. Последняя капля из неё не прольётся никогда.",
            cost={"gold": 1000, "wood": 0, "grain": 20, "hops": 40},
            craft_hours=5, income_pct=6, luck=3, sprite="amulet",
        ),
        Item(
            id="rooster_talisman", slot="talisman", name="Талисман петуха",
            description="Орёт удачей на всю округу. Соседи завидуют.",
            cost={"gold": 900, "wood": 10, "grain": 30, "hops": 30},
            craft_hours=5, income_pct=5, luck=5,
        ),
        Item(
            id="sumka", slot="bag", name="Сумка торговца",
            description="Двойное дно, тройная выгода, обереги от налогов.",
            cost={"gold": 750, "wood": 10, "grain": 25, "hops": 20},
            craft_hours=4, pay_discount_pct=10, luck=2,
        ),
        # ═══════ КОМПОНЕНТНАЯ СНАРЯГА (Фаза 2): куётся из охот-трофеев (шкура/
        # клык/жила/перстень), закрывает разрыв между стартовой кузней и снарягой
        # боссов. craftable=True (ярусы — больше охоты), но слабее топ-снаряги ★★★.
        Item(
            id="fur_coat", slot="chest", name="Меховая доха",
            description="Шкуры зверья мехом внутрь. Тепло, и удар держит — не фартук.",
            cost={"gold": 1500, "ingot": 4, "hide": 6},
            craft_hours=5, armor=16, vitality=10, income_pct=2,   # свой спрайт assets/items/fur_coat.png
        ),
        Item(
            id="fang_cleaver", slot="weapon", name="Клычный тесак",
            description="Звериные клыки в рукоять. Рвёт мясо и спор не хуже ковша.",
            cost={"gold": 1800, "ingot": 4, "fang": 5},
            craft_hours=6, damage=22, crit=8,   # свой спрайт assets/items/fang_cleaver.png
        ),
        Item(
            id="swift_boots", slot="boots", name="Сапоги-скороходы",
            description="Прошиты звериными жилами. Бегут — не угонишься, и фарт при тебе.",
            cost={"gold": 900, "ingot": 2, "sinew": 4},
            craft_hours=4, speed_pct=10, luck=3,
        ),
        Item(
            id="prestige_ring", slot="talisman", name="Перстень-диковина",
            description="Снят с атамана. Блестит так, что и удача, и купцы косятся.",
            cost={"gold": 2000, "ingot": 6, "ring": 1},
            craft_hours=6, income_pct=5, luck=7,
        ),
        # ═══════ АЛЬТЕРНАТИВЫ В «МЁРТВЫЕ» СЛОТЫ (боевой пересмотр, фаза B):
        # в слотах был один предмет — выбора билда не существовало. Теперь ось:
        # правая рука — добытчик vs лесоруб; ноги — танк vs скороход;
        # амулет — фарт-боевой vs доходный. ═══════
        Item(
            id="skinner_knife", slot="right_hand", name="Нож-свежевальщик",
            description="Лёгкий, злой, всегда при деле. Добыче не нравится — тебе в самый раз.",
            cost={"gold": 1400, "ingot": 3, "fang": 3},
            craft_hours=4, damage=8, crit=4, luck=4,
        ),
        Item(
            id="chain_skirt", slot="legs", name="Кольчужные штаны",
            description="Тяжелей портков, зато колено не подломят. Ходишь как крепость.",
            cost={"gold": 900, "ingot": 6, "grain": 20},
            craft_hours=3, armor=7, vitality=7,
        ),
        Item(
            id="wolf_totem", slot="amulet", name="Тотем зверолова",
            description="Клык на жиле — на удачу в лесу и твёрдость руки в драке.",
            cost={"gold": 1300, "ingot": 2, "sinew": 3, "fang": 2},
            craft_hours=5, crit=3, luck=6, vitality=5,
        ),
        # ═══════ РЕГИОНАЛЬНЫЕ ПОЯСА (Фаза 4): из компонента зверя СВОЕГО региона.
        # СТАТЫ ИДЕНТИЧНЫ во всех регионах (паритет by-design) — отличается лишь
        # компонент и название. Слот пояса (раньше только слабый «поясок»). ═══════
        Item(
            id="lynx_belt", slot="belt", name="Пояс гарпьего пуха",
            description="Северная выделка: тугой гарпий пух да крепкая сыромять — лёгок и цепок.",
            cost={"gold": 1200, "ingot": 2, "pelt": 4},
            craft_hours=4, armor=6, crit=4, vitality=5,
        ),
        Item(
            id="tusk_belt", slot="belt", name="Пояс с рогами",
            description="Долинная работа: витые рога сатира по ремню — и грозно, и крепко.",
            cost={"gold": 1200, "ingot": 2, "tusk": 4},
            craft_hours=4, armor=6, crit=4, vitality=5,
        ),
        Item(
            id="chitin_belt", slot="belt", name="Чешуйчатый пояс",
            description="Пустошная ковка: змеиная чешуя внахлёст — гибко и прочно.",
            cost={"gold": 1200, "ingot": 2, "chitin": 4},
            craft_hours=4, armor=6, crit=4, vitality=5,
        ),
        # ═══════ ОРОЧИЙ СЕТ (трофеи Орды): куётся ТОЛЬКО из 🗞 обрывков чертежа,
        # которые редко падают с побеждённого нашествия. Собрал чертежи → скуёшь.
        # Полный комплект из 3 вещей даёт сет-бонус (см. ORC_SET / combat_stats). ═══════
        Item(
            id="orc_helm", slot="head", name="Шлем орочьего вождя",
            description="Рогатая черепушка с клыками. Постояльцы трезвеют от одного взгляда.",
            cost={"gold": 800, "ingot": 8, "orc_scrap": 2},
            craft_hours=6, armor=10, vitality=7, income_pct=2, sprite="orc_helm",
        ),
        Item(
            id="orc_plate", slot="chest", name="Доспех орды",
            description="Награблённые пластины на ремнях. Тяжёлый, вонючий, непробиваемый.",
            cost={"gold": 1200, "ingot": 12, "orc_scrap": 3},
            craft_hours=8, armor=24, vitality=15, sprite="orc_plate",
        ),
        Item(
            id="orc_axe", slot="weapon", name="Секира орды",
            description="Зазубренная сталь на древке в человеческий рост. Спор решает с одного маха.",
            cost={"gold": 1500, "ingot": 10, "orc_scrap": 4},
            craft_hours=8, damage=26, crit=9, sprite="orc_axe",
        ),
        # ═══════ ЭКСКЛЮЗИВ РЕЙД-БОССОВ (craftable=False, только выбить) ═══════
        # Статы множатся на ярус; падают рандомным ярусом, ★★★ — редчайшее.
        # cost — прокси-стоимость для ВВП (не куётся, цена символическая).
        # 🐀 Крысиный Король
        Item(
            id="rat_crown", slot="head", name="Корона Крысиного Короля",
            description="Жестяной обруч с подвала. Крысы кланялись — теперь кланяйся ты.",
            cost={"gold": 1500}, craft_hours=0, craftable=False,
            income_pct=3, armor=6, luck=3, vitality=4,
        ),
        Item(
            id="rat_pelt", slot="chest", name="Душегрейка крысиного бугра",
            description="Сшита из шкур подвальной знати. Воняет, но греет и держит удар.",
            cost={"gold": 1500}, craft_hours=0, craftable=False,
            yield_pct=3, armor=14, vitality=12,
        ),
        Item(
            id="rat_tail", slot="right_hand", name="Плеть из крысиных хвостов",
            description="Свистит и жалит. Гадко, зато по делу.",
            cost={"gold": 1500}, craft_hours=0, craftable=False,
            damage=12, crit=5,
        ),
        # 👹 Болотный Тролль
        Item(
            id="troll_club", slot="weapon", name="Дубина болотного тролля",
            description="Бревно с тролльей лапы. Махнул — и спор окончен.",
            cost={"gold": 4000}, craft_hours=0, craftable=False,
            damage=30, crit=8,
        ),
        Item(
            id="troll_hide", slot="chest", name="Шкура болотного тролля",
            description="Толстая, склизкая, непробиваемая. Работники боятся — и слушаются.",
            cost={"gold": 4000}, craft_hours=0, craftable=False,
            pay_discount_pct=3, armor=22, vitality=17,
        ),
        Item(
            id="troll_eye", slot="amulet", name="Глаз тролля",
            description="Мутный, но видит фарт за версту. Носи — и удача косится на тебя.",
            cost={"gold": 4000}, craft_hours=0, craftable=False,
            income_pct=4, luck=7, vitality=6,
        ),
        # 🐲 Древний Змей
        Item(
            id="dragon_fang", slot="weapon", name="Клык Древнего Змея",
            description="Длиннее руки, острее совести. Лучшее оружие Недоливска.",
            cost={"gold": 9000}, craft_hours=0, craftable=False,
            damage=38, crit=13,
        ),
        Item(
            id="dragon_scale", slot="chest", name="Чешуя Древнего Змея",
            description="Не берёт ни клинок, ни топор, ни косой взгляд кредитора.",
            cost={"gold": 9000}, craft_hours=0, craftable=False,
            armor=30, vitality=24,
        ),
        Item(
            id="dragon_heart", slot="talisman", name="Сердце Древнего Змея",
            description="Тлеет углём по сей день. Удача, деньги и нюх на добычу — при тебе.",
            cost={"gold": 9000}, craft_hours=0, craftable=False,
            income_pct=6, yield_pct=5, luck=10,
        ),
        # 😈 Адский Слизень
        Item(
            id="demon_fang", slot="weapon", name="Бесовский клык",
            description="Выломан из адской пасти, ещё дымится серой. Бьёт — и спорщик кается.",
            cost={"gold": 6500}, craft_hours=0, craftable=False,
            damage=34, crit=11,
        ),
        Item(
            id="demon_hide", slot="chest", name="Смоляная шкура беса",
            description="Липкая, горячая, не берёт ни клинок, ни огонь. Чужие удары вязнут.",
            cost={"gold": 6500}, craft_hours=0, craftable=False,
            armor=26, vitality=21,
        ),
        Item(
            id="demon_core", slot="talisman", name="Адское ядро",
            description="Уголёк из самого нутра твари. Греет мошну и косит удачу на тебя.",
            cost={"gold": 6500}, craft_hours=0, craftable=False,
            income_pct=5, yield_pct=4, luck=9,
        ),
    ]
}

# Региональная снаряга (Фаза 4): id → регион. Куётся из компонента своего региона,
# поэтому форж показывает игроку только ЕГО пояс (чужие скрафтить нельзя).
REGION_GEAR = {
    "lynx_belt": "north_wilds",
    "tusk_belt": "green_valleys",
    "chitin_belt": "red_wastes",
}


def equipped_items(equipment: dict | None) -> list[tuple[Item, int]]:
    """[(предмет, ярус), ...] — статы предмета умножаются на ярус."""
    if not equipment:
        return []
    result = []
    for entry in equipment.values():
        item_id, tier = parse_entry(entry)
        if item_id in CATALOG:
            result.append((CATALOG[item_id], tier))
    return result


def income_multiplier(equipment: dict | None) -> float:
    pct = sum(_emul(i.income_pct, t) for i, t in equipped_items(equipment))
    if orc_set_complete(equipment):              # сет-бонус: + доход за полный комплект
        pct += ORC_SET_INCOME_PCT
    return 1 + pct / 100


def yield_multiplier(equipment: dict | None, resource: str) -> float:
    pairs = equipped_items(equipment)
    pct = sum(_emul(i.yield_pct, t) for i, t in pairs)
    if resource == "wood":
        pct += sum(_emul(i.yield_wood_pct, t) for i, t in pairs)
    return 1 + pct / 100


def speed_multiplier(equipment: dict | None) -> float:
    pct = min(50, sum(_emul(i.speed_pct, t) for i, t in equipped_items(equipment)))
    return 1 - pct / 100


def pay_multiplier(equipment: dict | None) -> float:
    pct = min(50, sum(_emul(i.pay_discount_pct, t) for i, t in equipped_items(equipment)))
    return 1 - pct / 100


def orc_set_complete(equipment: dict | None) -> bool:
    """Надеты ли все 3 части орочьего сета (любого яруса)."""
    if not equipment:
        return False
    worn = {parse_entry(e)[0] for e in equipment.values()}
    return all(p in worn for p in ORC_SET)


def combat_stats(equipment: dict | None) -> dict:
    stats = {"damage": 0, "crit": 0, "armor": 0, "luck": 0, "vitality": 0}
    for entry in (equipment or {}).values():
        item_id, tier, plus, aff = parse_full(entry)
        it = CATALOG.get(item_id)
        if it is None:
            continue
        for k in stats:
            v = _cmul(getattr(it, k), tier)
            stats[k] += v + plus_bonus(v, plus)      # заточка растит статы вещи
        if aff:                                       # аффикс: плоский бонус ×ярус
            for k, v in AFFIXES[aff][1].items():
                stats[k] = stats.get(k, 0) + v * tier
    if orc_set_complete(equipment):              # сет-бонус «ярость орды»
        for k, v in ORC_SET_BONUS.items():
            stats[k] = stats.get(k, 0) + v
    return stats


def _base_value(item: Item) -> float:
    from bot.game.balance import RESOURCE_PRICE

    total = float(item.cost.get("gold", 0))
    for res, price in RESOURCE_PRICE.items():
        total += item.cost.get(res, 0) * price
    return total


def gear_value(equipment: dict | None) -> int:
    """Стоимость экипировки в золоте с учётом ярусов (для ВВП)."""
    total = 0.0
    for item, tier in equipped_items(equipment):
        total += _base_value(item) * TIER_INVESTED[tier]
    return int(total)
