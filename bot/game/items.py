"""Экипировка: каталог предметов, бонусы к экономике, боевые статы.

Боевые статы (damage, crit, armor, luck) пока копятся «впрок» —
заработают, когда появится охота.
Картинки предметов: assets/items/<item_id>.png (прозрачный фон).
"""

from dataclasses import dataclass


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
    # бой (на будущее)
    damage: int = 0
    crit: int = 0
    armor: int = 0
    luck: int = 0


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


def parse_entry(entry: str) -> tuple[str, int]:
    """'kovsh:2' -> (kovsh, 2); старый формат 'kovsh' -> (kovsh, 1)."""
    if ":" in entry:
        item_id, _, tier_s = entry.partition(":")
        try:
            tier = max(1, min(TIER_MAX, int(tier_s)))
        except ValueError:
            tier = 1
        return item_id, tier
    return entry, 1


def make_entry(item_id: str, tier: int) -> str:
    return f"{item_id}:{tier}"


def tier_cost(item: "Item", tier: int) -> dict:
    if TEST_FREE_CRAFT:
        return {k: 0 for k in item.cost}
    mult = TIER_COST_MULT[tier]
    return {k: v * mult for k, v in item.cost.items()}


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
            craft_hours=2, income_pct=5, armor=2, sprite="shapka",
        ),
        Item(
            id="fartuk", slot="chest", name="Фартук трактирщика",
            description="Пятна эля, жира и чьей-то крови. В основном эля.",
            cost={"gold": 700, "wood": 20, "grain": 40, "hops": 0},
            craft_hours=4, yield_pct=5, armor=8, sprite="bronya",
        ),
        Item(
            id="oak_shield", slot="left_hand", name="Щит дубовый",
            description="Им можно прикрыться, а можно подать на нём жаркое. "
                        "Окован железом — для крепости.",
            cost={"gold": 480, "wood": 40, "ingot": 8},
            craft_hours=3, pay_discount_pct=5, armor=10,
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
            craft_hours=6, yield_pct=10, damage=14, crit=7, sprite="oruzhie",
        ),
        Item(
            id="poyas", slot="belt", name="Пояс мастеровой",
            description="Нож, молоток и кисти — всё хозяйство при себе.",
            cost={"gold": 350, "wood": 0, "grain": 20, "hops": 10},
            craft_hours=2, speed_pct=5, armor=1,
        ),
        Item(
            id="strong_pants", slot="legs", name="Портки крепкие",
            description="Не рвутся, даже когда бежишь от разбойников.",
            cost={"gold": 400, "wood": 0, "grain": 30, "hops": 5},
            craft_hours=2, speed_pct=5, armor=3,
        ),
        Item(
            id="sapogi", slot="boots", name="Сапоги рунные",
            description="Руны светятся, носы загнуты. Бегут почти сами.",
            cost={"gold": 800, "wood": 20, "grain": 0, "hops": 15},
            craft_hours=4, speed_pct=10, armor=4,
        ),
        Item(
            id="kruzhka", slot="amulet", name="Последняя капля",
            description="Кружка-оберег. Последняя капля из неё не прольётся никогда.",
            cost={"gold": 1000, "wood": 0, "grain": 20, "hops": 40},
            craft_hours=5, income_pct=10, luck=3, sprite="amulet",
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
            craft_hours=4, pay_discount_pct=15, luck=2,
        ),
        # ═══════ КОМПОНЕНТНАЯ СНАРЯГА (Фаза 2): куётся из охот-трофеев (шкура/
        # клык/жила/перстень), закрывает разрыв между стартовой кузней и снарягой
        # боссов. craftable=True (ярусы — больше охоты), но слабее топ-снаряги ★★★.
        Item(
            id="fur_coat", slot="chest", name="Меховая доха",
            description="Шкуры зверья мехом внутрь. Тепло, и удар держит — не фартук.",
            cost={"gold": 1500, "ingot": 4, "hide": 6},
            craft_hours=5, armor=14, income_pct=2, sprite="bronya",
        ),
        Item(
            id="fang_cleaver", slot="weapon", name="Клычный тесак",
            description="Звериные клыки в рукоять. Рвёт мясо и спор не хуже ковша.",
            cost={"gold": 1800, "ingot": 4, "fang": 5},
            craft_hours=6, damage=22, crit=5, sprite="oruzhie",
        ),
        Item(
            id="swift_boots", slot="boots", name="Сапоги-скороходы",
            description="Прошиты звериными жилами. Бегут — не угонишься, и фарт при тебе.",
            cost={"gold": 900, "ingot": 2, "sinew": 4},
            craft_hours=4, speed_pct=10, luck=4,
        ),
        Item(
            id="prestige_ring", slot="talisman", name="Перстень-диковина",
            description="Снят с атамана. Блестит так, что и удача, и купцы косятся.",
            cost={"gold": 2000, "ingot": 6, "ring": 1},
            craft_hours=6, income_pct=5, luck=8,
        ),
        # ═══════ ЭКСКЛЮЗИВ РЕЙД-БОССОВ (craftable=False, только выбить) ═══════
        # Статы множатся на ярус; падают рандомным ярусом, ★★★ — редчайшее.
        # cost — прокси-стоимость для ВВП (не куётся, цена символическая).
        # 🐀 Крысиный Король
        Item(
            id="rat_crown", slot="head", name="Корона Крысиного Короля",
            description="Жестяной обруч с подвала. Крысы кланялись — теперь кланяйся ты.",
            cost={"gold": 1500}, craft_hours=0, craftable=False,
            income_pct=3, armor=6, luck=4,
        ),
        Item(
            id="rat_pelt", slot="chest", name="Душегрейка крысиного бугра",
            description="Сшита из шкур подвальной знати. Воняет, но греет и держит удар.",
            cost={"gold": 1500}, craft_hours=0, craftable=False,
            yield_pct=4, armor=12,
        ),
        Item(
            id="rat_tail", slot="right_hand", name="Плеть из крысиных хвостов",
            description="Свистит и жалит. Гадко, зато по делу.",
            cost={"gold": 1500}, craft_hours=0, craftable=False,
            damage=10, crit=4,
        ),
        # 👹 Болотный Тролль
        Item(
            id="troll_club", slot="weapon", name="Дубина болотного тролля",
            description="Бревно с тролльей лапы. Махнул — и спор окончен.",
            cost={"gold": 4000}, craft_hours=0, craftable=False,
            damage=18, crit=4,
        ),
        Item(
            id="troll_hide", slot="chest", name="Шкура болотного тролля",
            description="Толстая, склизкая, непробиваемая. Работники боятся — и слушаются.",
            cost={"gold": 4000}, craft_hours=0, craftable=False,
            pay_discount_pct=5, armor=24,
        ),
        Item(
            id="troll_eye", slot="amulet", name="Глаз тролля",
            description="Мутный, но видит фарт за версту. Носи — и удача косится на тебя.",
            cost={"gold": 4000}, craft_hours=0, craftable=False,
            income_pct=4, luck=8,
        ),
        # 🐲 Древний Змей
        Item(
            id="dragon_fang", slot="weapon", name="Клык Древнего Змея",
            description="Длиннее руки, острее совести. Лучшее оружие Недоливска.",
            cost={"gold": 9000}, craft_hours=0, craftable=False,
            damage=28, crit=10, luck=3,
        ),
        Item(
            id="dragon_scale", slot="chest", name="Чешуя Древнего Змея",
            description="Не берёт ни клинок, ни топор, ни косой взгляд кредитора.",
            cost={"gold": 9000}, craft_hours=0, craftable=False,
            income_pct=6, armor=35,
        ),
        Item(
            id="dragon_heart", slot="talisman", name="Сердце Древнего Змея",
            description="Тлеет углём по сей день. Удача, деньги и нюх на добычу — при тебе.",
            cost={"gold": 9000}, craft_hours=0, craftable=False,
            income_pct=6, yield_pct=5, luck=12,
        ),
    ]
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
    return 1 + sum(i.income_pct * t for i, t in equipped_items(equipment)) / 100


def yield_multiplier(equipment: dict | None, resource: str) -> float:
    pairs = equipped_items(equipment)
    pct = sum(i.yield_pct * t for i, t in pairs)
    if resource == "wood":
        pct += sum(i.yield_wood_pct * t for i, t in pairs)
    return 1 + pct / 100


def speed_multiplier(equipment: dict | None) -> float:
    pct = min(50, sum(i.speed_pct * t for i, t in equipped_items(equipment)))
    return 1 - pct / 100


def pay_multiplier(equipment: dict | None) -> float:
    pct = min(50, sum(i.pay_discount_pct * t for i, t in equipped_items(equipment)))
    return 1 - pct / 100


def combat_stats(equipment: dict | None) -> dict:
    pairs = equipped_items(equipment)
    return {
        "damage": sum(i.damage * t for i, t in pairs),
        "crit": sum(i.crit * t for i, t in pairs),
        "armor": sum(i.armor * t for i, t in pairs),
        "luck": sum(i.luck * t for i, t in pairs),
    }


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
