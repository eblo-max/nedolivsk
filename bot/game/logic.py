"""Игровая логика поверх моделей. Все функции меняют объекты, коммит — снаружи."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db.models import Player, Tavern
from bot.game import balance


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
    pay = balance.worker_pay(level)
    if player.gold < pay:
        return ExpeditionStart(ok=False, reason="no_gold", pay=pay)

    player.gold -= pay
    player.expedition_resource = resource
    player.expedition_ends_at = _now() + timedelta(hours=balance.EXPEDITION_HOURS)
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
    gold = int(tavern.income_rate * hours)
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
