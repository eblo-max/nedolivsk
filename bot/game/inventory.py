"""Доступ к инвентарю игрока (JSONB-словарь {ресурс: количество}).

Золото живёт отдельной колонкой `player.gold` — но в словарях стоимости
(апгрейд, крафт) встречается ключ "gold", поэтому can_afford/pay умеют
тратить и его. JSONB меняем только переприсваиванием нового dict —
иначе SQLAlchemy не заметит изменения.
"""

from bot.db.models import Player


def get(player: Player, resource: str) -> int:
    return int((player.inventory or {}).get(resource, 0))


def add(player: Player, resource: str, amount: int) -> None:
    inv = dict(player.inventory or {})
    inv[resource] = max(0, inv.get(resource, 0) + amount)
    player.inventory = inv


def can_afford(player: Player, cost: dict) -> bool:
    """Хватает ли на стоимость (gold — из колонки, прочее — из инвентаря)."""
    for res, need in cost.items():
        have = player.gold if res == "gold" else get(player, res)
        if have < need:
            return False
    return True


def pay(player: Player, cost: dict) -> None:
    """Списать стоимость. Вызывать после проверки can_afford."""
    inv = dict(player.inventory or {})
    for res, need in cost.items():
        if not need:
            continue
        if res == "gold":
            player.gold -= need
        else:
            inv[res] = max(0, inv.get(res, 0) - need)
    player.inventory = inv
