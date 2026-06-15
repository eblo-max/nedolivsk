"""Игровая логика поверх моделей. Все функции меняют объекты, коммит — снаружи."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db.models import Player, Tavern
from bot.game import balance, buff, inventory, items, perks, production, season


def _now() -> datetime:
    return datetime.now(timezone.utc)


def expedition_slots(tavern: Tavern) -> int:
    """Число бригад (параллельных вылазок), растёт с уровнем таверны.
    +1 бригада каждые 3 уровня, первая прибавка — уже на 3-м уровне."""
    level = tavern.level if tavern else 1
    return 1 + level // 3


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
    hours = (balance.EXPEDITION_HOURS * items.speed_multiplier(equipment)
             * buff.expedition_speed_mult(player))  # баф «Быстрые ноги»
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
                     * season.yield_mult(resource) * buff.yield_mult(player))
        luck = (items.combat_stats(equipment)["luck"] + perks.luck_bonus(player)
                + buff.luck_bonus(player))  # баф «Фартовый день»
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
    order: dict | None = None      # {ключ: сколько ХОТЯТ выкупить} — на подтверждение
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
    """Пассив капает сразу; СБЫТ гостям — на подтверждение (order). Порча
    погреба идёт независимо от продажи. Спрос гостей считается, но не
    исполняется — игрок сам решает, наливать ли (см. apply_retail)."""
    now = _now()
    since = tavern.last_income_at or now
    hours = min((now - since).total_seconds() / 3600, balance.INCOME_CAP_HOURS)
    if hours <= 0:
        return IncomeResult(ok=False)

    mult = items.income_multiplier(getattr(player, "equipment", None))
    passive = int(tavern.income_rate * hours * mult * perks.passive_mult(player)
                  * buff.gold_mult(player))

    order, premium_unsold = _retail_demand(
        tavern, hours, demand_mult, perks.food_mult(player))

    # Порча: излишек сверх вместимости киснет за период (независимо от продажи).
    products = dict(tavern.products or {})
    spoiled = _spoilage(player, tavern, products, hours)
    if spoiled:
        tavern.products = products

    if passive <= 0 and not order and not spoiled:
        return IncomeResult(ok=False)

    player.gold += passive  # пассив — сразу, без подтверждения
    tavern.last_income_at = now
    return IncomeResult(
        ok=True, gold=passive, passive=passive, order=order or None,
        spoiled=spoiled or None, premium_unsold=premium_unsold,
    )


def _retail_demand(
    tavern: Tavern, hours: float, demand_mult: float, food_mult: float
) -> tuple[dict, bool]:
    """Что гости ХОТЯТ выкупить (без исполнения): (want{ключ:кол}, premium_unsold).
    Состоятельные — дороже-первым, пьянь — дешёвое (≤порога), еда — пул голода."""
    products = tavern.products or {}
    avail = {k: int(v) for k, v in products.items() if v > 0}
    want: dict[str, int] = {}

    def take(key: str, budget: int) -> int:
        n = min(avail.get(key, 0), budget)
        if n > 0:
            avail[key] -= n
            want[key] = want.get(key, 0) + n
        return n

    demand = int(tavern.capacity * balance.DEMAND_PER_CAPACITY * hours * demand_mult)
    share = min(balance.PREMIUM_SHARE_MAX, tavern.reputation / balance.PREMIUM_REP_DIV)
    premium = int(demand * share)
    commoner = demand - premium

    keys = [k for k in products if k in production.DRINKS and products[k] > 0]
    by_price = sorted(keys, key=lambda k: production.DRINKS[k].price)
    for key in reversed(by_price):
        if premium <= 0:
            break
        premium -= take(key, premium)
    for key in by_price:
        if commoner <= 0:
            break
        if production.DRINKS[key].price > balance.COMMONER_MAX_PRICE:
            break
        commoner -= take(key, commoner)

    # Еда: тот же принцип сегментации, что и у напитков. Состоятельные едоки
    # берут дорогое (пирог/сыр), простой люд — дешёвое (хлеб) — чтобы дешёвая
    # еда не простаивала вечно за спиной дорогой.
    hunger = int(tavern.capacity * balance.FOOD_DEMAND_PER_CAPACITY * hours
                 * demand_mult * food_mult)
    foods = [k for k in products if k in production.FOODS and products[k] > 0]
    by_food_price = sorted(foods, key=lambda k: production.FOODS[k].price)
    food_premium = int(hunger * share)
    food_common = hunger - food_premium
    for key in reversed(by_food_price):   # состоятельные — дорогое первым
        if food_premium <= 0:
            break
        food_premium -= take(key, food_premium)
    for key in by_food_price:             # простой люд — дешёвое первым
        if food_common <= 0:
            break
        food_common -= take(key, food_common)

    premium_unsold = any(
        avail.get(k, 0) > 0 and production.DRINKS[k].price >= 10 for k in keys
    ) and share < 0.4
    return want, premium_unsold


def retail_total(want: dict | None, player: Player | None = None) -> int:
    """Выручка от сбыта по фиксированным ценам (для показа на подтверждении).
    С игроком — учитывает активный баф «Бойкая касса», чтобы показанная сумма
    совпала с фактически начисленной в apply_retail."""
    base = sum(int(q) * production.GOODS[k].price
               for k, q in (want or {}).items() if k in production.GOODS)
    return int(base * buff.gold_mult(player)) if player is not None else base


def apply_retail(player: Player, tavern: Tavern, want: dict | None):
    """Исполнить подтверждённый сбыт гостям. Возвращает (sold{}, gold, rep_gain).
    Перепроверяет наличие — продаёт не больше, чем сейчас в погребе."""
    products = dict(tavern.products or {})
    sold: dict[str, int] = {}
    gold = 0
    for key, qty in (want or {}).items():
        if key not in production.GOODS:
            continue
        n = min(int(qty), products.get(key, 0))
        if n > 0:
            products[key] -= n
            sold[key] = n
            gold += n * production.GOODS[key].price
    if not sold:
        return {}, 0, 0
    gold = int(gold * buff.gold_mult(player))  # баф «Бойкая касса»
    tavern.products = products
    player.gold += gold
    total = sum(sold.values())
    rep_gain = total // balance.REP_PER_ALE_SOLD
    if perks.has_fame(player):  # знаменитый кабак — слава со сбыта
        rep_gain += 1
    if rep_gain:
        tavern.reputation += rep_gain
        player.reputation += rep_gain
    return sold, gold, rep_gain


def _spoilage(player: Player, tavern: Tavern, products: dict, hours: float) -> dict:
    """Излишек товара сверх вместимости погреба киснет. Мутирует products,
    возвращает {ключ: скисло}. Бьёт пропорционально по запасам.
    Баф «Холодный погреб» режет порчу вдвое."""
    goods = [k for k in production.GOODS if products.get(k, 0) > 0]
    total = sum(products[k] for k in goods)
    cap = balance.cellar_capacity(tavern.capacity)
    if total <= cap:
        return {}
    excess = total - cap
    spoil_total = int(excess * balance.SPOIL_PCT_PER_DAY * hours / 24
                      * buff.spoil_mult(player))
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
