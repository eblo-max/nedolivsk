"""Игровая логика поверх моделей. Все функции меняют объекты, коммит — снаружи."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db.models import Player, Tavern
from bot.game import balance, inventory, items, perks, production, season


def _now() -> datetime:
    return datetime.now(timezone.utc)


def expedition_slots(tavern: Tavern) -> int:
    """Число бригад (параллельных вылазок), растёт с уровнем таверны."""
    level = tavern.level if tavern else 1
    return 1 + (level - 1) // 3


def _exps(player: Player) -> list:
    return list(player.expeditions or [])


@dataclass
class ExpeditionCounts:
    out: int = 0       # в пути
    ready: int = 0     # вернулись, ждут забора
    free: int = 0      # свободные слоты
    total: int = 0     # всего слотов
    next_minutes: int = 0  # до ближайшего возвращения


def expedition_counts(player: Player, tavern: Tavern) -> ExpeditionCounts:
    now = _now()
    exps = _exps(player)
    ready = out = 0
    next_min = 0
    for e in exps:
        left = (datetime.fromisoformat(e["ends_at"]) - now).total_seconds()
        if left > 0:
            out += 1
            m = int(left // 60) + 1
            next_min = m if next_min == 0 else min(next_min, m)
        else:
            ready += 1
    total = expedition_slots(tavern)
    return ExpeditionCounts(
        out=out, ready=ready, free=max(0, total - len(exps)),
        total=total, next_minutes=next_min,
    )


@dataclass
class ExpeditionStart:
    ok: bool
    reason: str = ""  # no_slot | no_gold
    pay: int = 0


def start_expedition(player: Player, tavern: Tavern, resource: str) -> ExpeditionStart:
    """Отправить ещё одну бригаду за ресурсом, если есть свободный слот."""
    exps = _exps(player)
    if len(exps) >= expedition_slots(tavern):
        return ExpeditionStart(ok=False, reason="no_slot")

    level = tavern.level if tavern else 1
    equipment = getattr(player, "equipment", None)
    pay = max(1, int(balance.worker_pay(level) * items.pay_multiplier(equipment)
                     * perks.expedition_pay_mult(player)))
    if player.gold < pay:
        return ExpeditionStart(ok=False, reason="no_gold", pay=pay)

    player.gold -= pay
    hours = balance.EXPEDITION_HOURS * items.speed_multiplier(equipment)
    exps.append({
        "resource": resource,
        "ends_at": (_now() + timedelta(hours=hours)).isoformat(),
        "notified": False,
    })
    player.expeditions = exps
    return ExpeditionStart(ok=True, pay=pay)


def claim_expeditions(player: Player) -> list[tuple[str, int, bool]]:
    """Забрать всех вернувшихся бригад. Возвращает [(ресурс, кол-во, удача)]."""
    now = _now()
    level = player.tavern.level if player.tavern else 1
    equipment = getattr(player, "equipment", None)
    kept: list = []
    claimed: list[tuple[str, int, bool]] = []
    for e in _exps(player):
        if (datetime.fromisoformat(e["ends_at"]) - now).total_seconds() > 0:
            kept.append(e)
            continue
        resource = e["resource"]
        amount = balance.expedition_yield(resource, level, player.region)
        amount = int(amount * items.yield_multiplier(equipment, resource)
                     * season.yield_mult(resource))
        luck = items.combat_stats(equipment)["luck"] + perks.luck_bonus(player)
        lucky = random.randint(1, 100) <= balance.lucky_chance(luck)
        if lucky:
            amount *= balance.LUCKY_MULT
        inventory.add(player, resource, amount)
        claimed.append((resource, amount, lucky))
    player.expeditions = kept
    return claimed


@dataclass
class IncomeResult:
    ok: bool
    gold: int = 0
    passive: int = 0
    sales: int = 0
    sold: dict | None = None       # {ключ напитка: продано}
    spoiled: dict | None = None    # {ключ: скисло} — излишек погреба прокис
    rep_gain: int = 0
    premium_unsold: bool = False   # остался премиум — состоятельных мало
    fair: bool = False             # доход собран во время ярмарки
    skim: int = 0                  # доля, утекшая из-за городской ситуации
    city_label: str = ""           # активная городская ситуация (для показа)
    perk_demand: float = 1.0       # множитель сбыта от перка (купеческая протекция)
    mood_factor: float = 1.0       # множитель спроса от настроения города
    season_demand: float = 1.0     # множитель спроса от сезона/праздника
    season_label: str = ""         # подпись сезона/праздника (для показа)


def collect_income(
    player: Player, tavern: Tavern, demand_mult: float = 1.0
) -> IncomeResult:
    """Гибрид: полный пассив + сбыт напитков и еды. Спрос (жажда) делится на
    два пула — состоятельные (дороже-первым) и пьянь (дешевле-первым); еда —
    отдельный пул голода. demand_mult>1 — ярмарка (наплыв гостей)."""
    now = _now()
    since = tavern.last_income_at or now
    hours = min((now - since).total_seconds() / 3600, balance.INCOME_CAP_HOURS)
    if hours <= 0:
        return IncomeResult(ok=False)

    mult = items.income_multiplier(getattr(player, "equipment", None))
    passive = int(tavern.income_rate * hours * mult * perks.passive_mult(player))

    demand = int(tavern.capacity * balance.DEMAND_PER_CAPACITY * hours * demand_mult)
    share = min(balance.PREMIUM_SHARE_MAX, tavern.reputation / balance.PREMIUM_REP_DIV)
    premium_demand = int(demand * share)
    commoner_demand = demand - premium_demand

    products = dict(tavern.products or {})
    sold: dict[str, int] = {}
    sales = 0

    def sell(key: str, budget: int) -> int:
        nonlocal sales
        n = min(products.get(key, 0), budget)
        if n > 0:
            products[key] -= n
            sold[key] = sold.get(key, 0) + n
            sales += n * production.GOODS[key].price
        return n

    # Напитки: два пула (жажда). Состоятельные — дороже-первым, пьянь — дешёвое.
    keys = [k for k in products if k in production.DRINKS and products[k] > 0]
    by_price = sorted(keys, key=lambda k: production.DRINKS[k].price)
    for key in reversed(by_price):
        if premium_demand <= 0:
            break
        premium_demand -= sell(key, premium_demand)
    for key in by_price:
        if commoner_demand <= 0:
            break
        if production.DRINKS[key].price > balance.COMMONER_MAX_PRICE:
            break
        commoner_demand -= sell(key, commoner_demand)

    # Еда: отдельный пул (голод) — сытый гость доплачивает за блюдо.
    hunger = int(tavern.capacity * balance.FOOD_DEMAND_PER_CAPACITY * hours
                 * demand_mult * perks.food_mult(player))
    food_keys = sorted(
        (k for k in products if k in production.FOODS and products[k] > 0),
        key=lambda k: -production.FOODS[k].price,
    )
    for key in food_keys:
        if hunger <= 0:
            break
        hunger -= sell(key, hunger)

    premium_unsold = any(
        products.get(k, 0) > 0 and production.DRINKS[k].price >= 10
        for k in keys
    ) and share < 0.4

    # Порча: непроданный излишек сверх вместимости погреба киснет за период.
    spoiled = _spoilage(tavern, products, hours)

    total_sold = sum(sold.values())
    rep_gain = total_sold // balance.REP_PER_ALE_SOLD
    if total_sold and perks.has_fame(player):  # знаменитый кабак — слава со сбыта
        rep_gain += 1
    gold = passive + sales
    if gold <= 0 and rep_gain == 0 and not spoiled:
        return IncomeResult(ok=False)

    player.gold += gold
    if total_sold or spoiled:
        tavern.products = products
    if rep_gain:
        tavern.reputation += rep_gain
        player.reputation += rep_gain
    tavern.last_income_at = now
    return IncomeResult(
        ok=True, gold=gold, passive=passive, sales=sales,
        sold=sold, spoiled=spoiled or None, rep_gain=rep_gain,
        premium_unsold=premium_unsold, fair=demand_mult > 1.0,
    )


def _spoilage(tavern: Tavern, products: dict, hours: float) -> dict:
    """Излишек товара сверх вместимости погреба киснет. Мутирует products,
    возвращает {ключ: скисло}. Бьёт пропорционально по запасам."""
    goods = [k for k in production.GOODS if products.get(k, 0) > 0]
    total = sum(products[k] for k in goods)
    cap = balance.cellar_capacity(tavern.capacity)
    if total <= cap:
        return {}
    excess = total - cap
    spoil_total = int(excess * balance.SPOIL_PCT_PER_DAY * hours / 24)
    if spoil_total <= 0:
        return {}
    spoiled: dict[str, int] = {}
    for k in sorted(goods, key=lambda x: -products[x]):
        s = min(products[k], int(round(spoil_total * products[k] / total)))
        if s > 0:
            products[k] -= s
            spoiled[k] = s
    return spoiled


@dataclass
class UpgradeResult:
    ok: bool
    reason: str = ""
    cost: dict | None = None
    new_level: int = 0


def try_upgrade(player: Player, tavern: Tavern) -> UpgradeResult:
    """Улучшение таверны на следующий уровень."""
    if tavern.level >= balance.MAX_LEVEL:
        return UpgradeResult(ok=False, reason="max_level")

    cost = balance.upgrade_cost(tavern.level)
    if not inventory.can_afford(player, cost):
        return UpgradeResult(ok=False, reason="not_enough", cost=cost)

    inventory.pay(player, cost)

    tavern.level += 1
    stats = balance.stats_for_level(tavern.level)
    tavern.capacity = stats["capacity"]
    tavern.comfort = stats["comfort"]
    tavern.income_rate = stats["income_rate"]

    rep = balance.reputation_for_upgrade(tavern.level)
    tavern.reputation += rep
    player.reputation += rep
    player.level = tavern.level

    return UpgradeResult(ok=True, cost=cost, new_level=tavern.level)


def craft_state(player: Player) -> tuple[str, int]:
    """("none"|"active"|"ready", минут до готовности)."""
    if player.craft_item is None or player.craft_ends_at is None:
        return "none", 0
    left = (player.craft_ends_at - _now()).total_seconds()
    if left > 0:
        return "active", int(left // 60) + 1
    return "ready", 0


@dataclass
class CraftStart:
    ok: bool
    reason: str = ""  # busy | unknown | not_enough | max_tier
    item: object = None
    tier: int = 1
    cost: dict | None = None
    hours: int = 0


def next_craft_tier(player: Player, item_id: str) -> int:
    """Какой ярус будет коваться: 1 для новой вещи, +1 для надетой."""
    return items.equipped_tier(getattr(player, "equipment", None), item_id) + 1


def start_craft(player: Player, item_id: str) -> CraftStart:
    """Заказать вещь у мастера. Один заказ за раз.
    Если предмет уже надет — перековка на следующий ярус."""
    state, _ = craft_state(player)
    if state != "none":
        return CraftStart(ok=False, reason="busy")
    item = items.CATALOG.get(item_id)
    if item is None:
        return CraftStart(ok=False, reason="unknown")

    tier = next_craft_tier(player, item_id)
    if tier > items.TIER_MAX:
        return CraftStart(ok=False, reason="max_tier", item=item)

    c = items.tier_cost(item, tier)
    hours = items.tier_hours(item, tier)
    if not inventory.can_afford(player, c):
        return CraftStart(ok=False, reason="not_enough", item=item,
                          tier=tier, cost=c, hours=hours)

    inventory.pay(player, c)
    player.craft_item = items.make_entry(item_id, tier)
    player.craft_ends_at = _now() + timedelta(hours=hours)
    player.craft_notified = False
    return CraftStart(ok=True, item=item, tier=tier, cost=c, hours=hours)


@dataclass
class CraftClaim:
    ok: bool
    reason: str = ""  # none | not_ready
    minutes_left: int = 0
    item: object = None
    tier: int = 1


def claim_craft(player: Player) -> CraftClaim:
    """Забрать готовую вещь — сразу надевается в свой слот."""
    state, minutes = craft_state(player)
    if state == "none":
        return CraftClaim(ok=False, reason="none")
    if state == "active":
        return CraftClaim(ok=False, reason="not_ready", minutes_left=minutes)

    item_id, tier = items.parse_entry(player.craft_item)
    item = items.CATALOG[item_id]
    equipment = dict(player.equipment or {})
    equipment[item.slot] = items.make_entry(item_id, tier)
    player.equipment = equipment
    player.craft_item = None
    player.craft_ends_at = None
    return CraftClaim(ok=True, item=item, tier=tier)
