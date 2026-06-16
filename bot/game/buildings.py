"""Пристройки таверны (Ярус 1 — производство).

Стройка — один слот за раз (как заказ в кузнице): оплата из инвентаря вперёд,
по времени достраивается и попадает в tavern.buildings. Само производство
на этих зданиях — следующий шаг.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import inventory


@dataclass(frozen=True)
class Building:
    id: str
    emoji: str
    name: str
    description: str       # жёсткий трактирный тон
    cost: dict             # gold + сырьё
    build_hours: int
    requires: tuple = ()       # какие здания нужны сперва
    req_reputation: int = 0    # минимальная репутация для постройки
    unlocks: str = ""          # что откроет (для описания)
    image: str = ""            # имя файла арта в assets/ (без .png)


CATALOG: dict[str, Building] = {
    "mill": Building(
        id="mill", emoji="🌾", name="Мельница",
        description="Жернова скрипят, мельник вечно под хмельком. "
                    "Зато зерно в солод мелет — что надо.",
        cost={"gold": 500, "wood": 160, "clay": 60},
        build_hours=1, unlocks="солод из зерна", image="melnica",
    ),
    "brewery": Building(
        id="brewery", emoji="🍺", name="Пивоварня",
        description="Чаны, пар и дух, от которого слезятся глаза. "
                    "Тут из солода, хмеля и воды рождается эль.",
        cost={"gold": 1400, "wood": 120, "ore": 80, "clay": 40},
        build_hours=2, requires=("mill",), unlocks="варка эля", image="pivovarnya",
    ),
    "meadery": Building(
        id="meadery", emoji="🍶", name="Медоварня",
        description="Котлы с мёдом томятся и пузырятся. Сладкий хмельной дух "
                    "влечёт публику почище, чем эль.",
        cost={"gold": 1200, "wood": 120, "clay": 60},
        build_hours=2, req_reputation=40, unlocks="медовуха для состоятельных",
        image="medovuxa",
    ),
    "kitchen": Building(
        id="kitchen", emoji="🍖", name="Кухня",
        description="Вертел скрипит, жир капает в огонь. Сытый гость пьёт "
                    "дольше и платит охотнее.",
        cost={"gold": 1000, "wood": 120, "clay": 60, "stone": 50},
        build_hours=2, unlocks="блюда — отдельный спрос на сытость",
        image="kyxnya",
    ),
    "winery": Building(
        id="winery", emoji="🍷", name="Винокурня",
        description="Дубовые бочки, тягучий ягодный дух. Вино — для самых "
                    "разборчивых и богатых гостей.",
        cost={"gold": 1400, "wood": 120, "clay": 60},
        build_hours=2, req_reputation=80, unlocks="вино из ягод для богачей",
        image="vinodelnya",
    ),
    "smelter": Building(
        id="smelter", emoji="🔩", name="Горн",
        description="Угли пышут, меха хрипят. Руда плавится в слитки — "
                    "из них кузнец и куёт доброе железо.",
        cost={"gold": 900, "wood": 100, "clay": 100, "stone": 90},
        build_hours=2, unlocks="слитки из руды (дешевле снаряга)", image="gorn",
    ),
    "bakery": Building(
        id="bakery", emoji="🥖", name="Пекарня",
        description="Печь дышит жаром, пахнет хлебом на всю улицу. "
                    "Из муки — хлеб да пироги, и гость сыт.",
        cost={"gold": 1000, "wood": 120, "clay": 80, "stone": 60},
        build_hours=2, requires=("mill",), unlocks="хлеб и пироги из муки",
        image="pekarnya",
    ),
    "smokehouse": Building(
        id="smokehouse", emoji="💨", name="Коптильня",
        description="Дым да соль — и дичь с рыбой лежат месяцами. "
                    "Солонина и копчёности всегда в цене.",
        cost={"gold": 900, "wood": 140, "clay": 40},
        build_hours=2, req_reputation=30, unlocks="солонина и копчёная рыба",
        image="koptilnya",
    ),
    "dairy": Building(
        id="dairy", emoji="🧀", name="Сыроварня",
        description="Чаны с молоком, головы сыра под прессом. "
                    "Сыр да масло — закуска для состоятельных.",
        cost={"gold": 1100, "wood": 120, "clay": 60},
        build_hours=2, req_reputation=50, unlocks="сыр и масло из молока",
        image="syrovarnya",
    ),
}
ORDER = ["mill", "brewery", "meadery", "kitchen", "winery",
         "smelter", "bakery", "smokehouse", "dairy"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_built(tavern, building_id: str) -> bool:
    return building_id in (tavern.buildings or [])


def missing_requirements(tavern, building: Building) -> list[Building]:
    return [CATALOG[r] for r in building.requires if not is_built(tavern, r)]


def rep_locked(tavern, building: Building) -> bool:
    return tavern.reputation < building.req_reputation


def buildable(tavern, building: Building) -> bool:
    return not missing_requirements(tavern, building) and not rep_locked(tavern, building)


def build_state(player) -> tuple[str, int]:
    """("none"|"active"|"ready", минут до готовности)."""
    if not player.build_item or not player.build_ends_at:
        return "none", 0
    left = (player.build_ends_at - _now()).total_seconds()
    if left > 0:
        return "active", int(left // 60) + 1
    return "ready", 0


@dataclass
class BuildStart:
    ok: bool
    reason: str = ""  # unknown | built | busy | requires | not_enough
    building: Building | None = None
    cost: dict | None = None
    hours: int = 0


def start_build(player, tavern, building_id: str) -> BuildStart:
    b = CATALOG.get(building_id)
    if b is None:
        return BuildStart(ok=False, reason="unknown")
    if is_built(tavern, building_id):
        return BuildStart(ok=False, reason="built", building=b)
    if build_state(player)[0] != "none":
        return BuildStart(ok=False, reason="busy", building=b)
    if missing_requirements(tavern, b):
        return BuildStart(ok=False, reason="requires", building=b)
    if rep_locked(tavern, b):
        return BuildStart(ok=False, reason="reputation", building=b)
    if not inventory.can_afford(player, b.cost):
        return BuildStart(ok=False, reason="not_enough", building=b,
                          cost=b.cost, hours=b.build_hours)

    inventory.pay(player, b.cost)
    player.build_item = building_id
    player.build_ends_at = _now() + timedelta(hours=b.build_hours)
    return BuildStart(ok=True, building=b, cost=b.cost, hours=b.build_hours)


def invested_value(tavern) -> int:
    """Капитализация построенных пристроек (для ВВП): золото + сырьё в цене."""
    from bot.game.balance import RESOURCE_PRICE

    total = 0.0
    for bid in (tavern.buildings or []):
        b = CATALOG.get(bid)
        if b is None:
            continue
        total += b.cost.get("gold", 0)
        for res, price in RESOURCE_PRICE.items():
            total += b.cost.get(res, 0) * price
    return int(total)


def finalize_build(player, tavern) -> Building | None:
    """Если стройка завершилась — заносим здание в таверну. Идемпотентно."""
    if build_state(player)[0] != "ready":
        return None
    bid = player.build_item
    built = list(tavern.buildings or [])
    if bid not in built:
        built.append(bid)
    tavern.buildings = built  # переприсваивание — чтобы JSONB заметил
    player.build_item = None
    player.build_ends_at = None
    return CATALOG.get(bid)
