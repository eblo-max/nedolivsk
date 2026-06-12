"""Игровая логика поверх моделей. Все функции меняют объекты, коммит — снаружи."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db.models import Player, Tavern
from bot.game import balance, items


def _now() -> datetime:
    return datetime.now(timezone.utc)


def expedition_state(player: Player) -> tuple[str, int]:
    """Состояние вылазки: ("none"|"active"|"ready", минут до возвращения)."""
    if player.expedition_resource is None or player.expedition_ends_at is None:
        return "none", 0
    left = (player.expedition_ends_at - _now()).total_seconds()
    if left > 0:
        return "active", int(left // 60) + 1
    return "ready", 0


@dataclass
class ExpeditionStart:
    ok: bool
    reason: str = ""  # busy | no_gold
    pay: int = 0


def start_expedition(player: Player, resource: str) -> ExpeditionStart:
    """Отправить работников за одним ресурсом."""
    state, _ = expedition_state(player)
    if state != "none":
        return ExpeditionStart(ok=False, reason="busy")

    level = player.tavern.level if player.tavern else 1
    equipment = getattr(player, "equipment", None)
    pay = max(1, int(balance.worker_pay(level) * items.pay_multiplier(equipment)))
    if player.gold < pay:
        return ExpeditionStart(ok=False, reason="no_gold", pay=pay)

    player.gold -= pay
    player.expedition_resource = resource
    hours = balance.EXPEDITION_HOURS * items.speed_multiplier(equipment)
    player.expedition_ends_at = _now() + timedelta(hours=hours)
    player.expedition_notified = False
    return ExpeditionStart(ok=True, pay=pay)


@dataclass
class ExpeditionClaim:
    ok: bool
    reason: str = ""  # none | not_ready
    minutes_left: int = 0
    resource: str = ""
    amount: int = 0


def claim_expedition(player: Player) -> ExpeditionClaim:
    """Забрать добычу вернувшихся работников."""
    state, minutes = expedition_state(player)
    if state == "none":
        return ExpeditionClaim(ok=False, reason="none")
    if state == "active":
        return ExpeditionClaim(ok=False, reason="not_ready", minutes_left=minutes)

    resource = player.expedition_resource
    level = player.tavern.level if player.tavern else 1
    amount = balance.expedition_yield(resource, level, player.region)
    amount = int(amount * items.yield_multiplier(getattr(player, "equipment", None), resource))

    setattr(player, resource, getattr(player, resource) + amount)
    player.expedition_resource = None
    player.expedition_ends_at = None
    return ExpeditionClaim(ok=True, resource=resource, amount=amount)


@dataclass
class IncomeResult:
    ok: bool
    gold: int = 0


def collect_income(player: Player, tavern: Tavern) -> IncomeResult:
    """Пассивный доход: копится со времени последнего сбора, с потолком."""
    now = _now()
    since = tavern.last_income_at or now
    hours = (now - since).total_seconds() / 3600
    hours = min(hours, balance.INCOME_CAP_HOURS)
    mult = items.income_multiplier(getattr(player, "equipment", None))
    gold = int(tavern.income_rate * hours * mult)
    if gold <= 0:
        return IncomeResult(ok=False)

    player.gold += gold
    tavern.last_income_at = now
    return IncomeResult(ok=True, gold=gold)


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
    if (
        player.gold < cost["gold"]
        or player.wood < cost["wood"]
        or player.grain < cost["grain"]
        or player.hops < cost["hops"]
    ):
        return UpgradeResult(ok=False, reason="not_enough", cost=cost)

    player.gold -= cost["gold"]
    player.wood -= cost["wood"]
    player.grain -= cost["grain"]
    player.hops -= cost["hops"]

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
    if (player.gold < c.get("gold", 0) or player.wood < c.get("wood", 0)
            or player.grain < c.get("grain", 0) or player.hops < c.get("hops", 0)):
        return CraftStart(ok=False, reason="not_enough", item=item,
                          tier=tier, cost=c, hours=hours)

    player.gold -= c.get("gold", 0)
    player.wood -= c.get("wood", 0)
    player.grain -= c.get("grain", 0)
    player.hops -= c.get("hops", 0)
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
