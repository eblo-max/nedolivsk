"""Производство на пристройках (Ярус 1→2).

Партия масштабируется с уровнем таверны: вход и выход ×уровень. Один слот на
здание. Состояние партий — в tavern.production (JSONB), выход фиксируется в
момент запуска (level-snapshot), чтобы апгрейд во время варки не менял итог.

Шаг 2a: мельница (зерно→солод). Пивоварня — следующим шагом.
"""

from datetime import datetime, timedelta, timezone

from bot.game import inventory

PRODUCERS = {"mill"}  # здания с производством (пополняется в 2b)

MILL_MINUTES = 40
MILL_GRAIN = 10   # зерна на 1 уровень
MILL_MALT = 8     # солода на 1 уровень


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mill_inputs(level: int) -> dict:
    return {"grain": MILL_GRAIN * level}


def mill_output(level: int) -> int:
    return MILL_MALT * level


def state(tavern, building: str) -> tuple[str, int]:
    """("none"|"active"|"ready", минут до готовности)."""
    batch = (tavern.production or {}).get(building)
    if not batch or not batch.get("ready_at"):
        return "none", 0
    left = (datetime.fromisoformat(batch["ready_at"]) - _now()).total_seconds()
    if left > 0:
        return "active", int(left // 60) + 1
    return "ready", 0


def _set_batch(tavern, building: str, batch: dict | None) -> None:
    prod = dict(tavern.production or {})
    if batch is None:
        prod.pop(building, None)
    else:
        prod[building] = batch
    tavern.production = prod  # переприсваивание — чтобы JSONB заметил


def start_mill(player, tavern) -> tuple[bool, str, dict | None]:
    """(ok, reason, inputs). reason: busy | not_enough."""
    if state(tavern, "mill")[0] != "none":
        return False, "busy", None
    level = tavern.level
    cin = mill_inputs(level)
    if not inventory.can_afford(player, cin):
        return False, "not_enough", cin
    inventory.pay(player, cin)
    _set_batch(tavern, "mill", {
        "out_res": "malt",
        "out_qty": mill_output(level),
        "ready_at": (_now() + timedelta(minutes=MILL_MINUTES)).isoformat(),
    })
    return True, "", cin


def claim_mill(player, tavern) -> int:
    """Забрать готовый солод в инвентарь. Возвращает количество (0 — нечего)."""
    if state(tavern, "mill")[0] != "ready":
        return 0
    batch = (tavern.production or {})["mill"]
    qty = int(batch.get("out_qty", 0))
    inventory.add(player, batch.get("out_res", "malt"), qty)
    _set_batch(tavern, "mill", None)
    return qty
