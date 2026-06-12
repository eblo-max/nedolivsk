"""Игровая логика поверх моделей. Все функции меняют объекты, коммит — снаружи."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db.models import Player, Tavern
from bot.game import balance


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CollectResult:
    ok: bool
    wait_minutes: int = 0
    gained: dict | None = None


def collect_resources(player: Player) -> CollectResult:
    """Сбор ресурсов по кулдауну."""
    now = _now()
    if player.last_collect_at is not None:
        elapsed = now - player.last_collect_at
        cooldown = timedelta(minutes=balance.COLLECT_COOLDOWN_MIN)
        if elapsed < cooldown:
            wait = int((cooldown - elapsed).total_seconds() // 60) + 1
            return CollectResult(ok=False, wait_minutes=wait)

    level = player.tavern.level if player.tavern else 1
    gained = {
        res: balance.collect_amount(res, level, player.region)
        for res in balance.COLLECT_BASE
    }
    player.wood += gained["wood"]
    player.grain += gained["grain"]
    player.hops += gained["hops"]
    player.last_collect_at = now
    return CollectResult(ok=True, gained=gained)


@dataclass
class IncomeResult:
    ok: bool
    gold: int = 0
    minutes: int = 0


def collect_income(player: Player, tavern: Tavern) -> IncomeResult:
    """Пассивный доход: копится со времени последнего сбора, с потолком."""
    now = _now()
    since = tavern.last_income_at or now
    hours = (now - since).total_seconds() / 3600
    hours = min(hours, balance.INCOME_CAP_HOURS)
    gold = int(tavern.income_rate * hours)
    if gold <= 0:
        minutes_left = max(1, int(60 / max(tavern.income_rate, 1)))
        return IncomeResult(ok=False, minutes=minutes_left)

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
