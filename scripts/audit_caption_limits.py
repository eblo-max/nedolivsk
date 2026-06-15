"""Аудит лимита подписи к фото (1024 UTF-16 code units) для панелей-картинок.
Слишком длинная подпись Telegram'ом отвергается, а show_photo_panel при этом
удаляет панель и падает. Меряем худший случай (энд-гейм, всё в проде).

Запуск: python -m scripts.audit_caption_limits
"""

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot import texts
from bot.game import balance

LIMIT = 1024
future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
future = future_dt.isoformat()  # для JSONB-полей (ends_at/ready_at)


def utf16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def maxed_player():
    # все 9 пристроек строятся/работают одновременно
    production = {
        "brewery": {"tier": 3, "ready_at": future, "stage": "ferment", "out_qty": 36},
        "mill": {"out_res": "malt", "ready_at": future, "out_qty": 80},
        "meadery": {"recipe": "sbiten", "ready_at": future, "out_qty": 120},
        "kitchen": {"recipe": "roast", "ready_at": future, "out_qty": 120},
        "winery": {"recipe": "wine", "ready_at": future, "out_qty": 120},
        "smelter": {"out_res": "ingot", "ready_at": future, "out_qty": 40},
        "bakery": {"recipe": "pie", "ready_at": future, "out_qty": 100},
        "smokehouse": {"recipe": "smoked_fish", "ready_at": future, "out_qty": 120},
        "dairy": {"recipe": "cheese", "ready_at": future, "out_qty": 120},
    }
    products = {k: 999 for k in ("ale1", "ale2", "ale3", "mead", "sbiten", "wine",
                                 "roast", "bread", "pie", "cured", "smoked_fish",
                                 "cheese", "butter")}
    tavern = SimpleNamespace(
        name="К" * 40,  # максимум имени при создании (2..40)
        level=10, capacity=55, comfort=10, income_rate=82, reputation=999,
        buildings=list(production.keys()),
        production=production, products=products, auction={},
        last_income_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    # снаряга во все 11 слотов, ярус 3
    from bot.game import items as it
    equipment = {}
    for iid, item in it.CATALOG.items():
        equipment[item.slot] = it.make_entry(iid, 3)
    inventory = {r: 9999 for r in balance.RESOURCES}
    inventory.update({"malt": 999, "flour": 999, "ingot": 999})
    player = SimpleNamespace(
        id=1, first_name="Кабатчик", username="x", gold=9_999_999,
        region="north_wilds", reputation=999, level=10,
        equipment=equipment, inventory=inventory, expeditions=[
            {"resource": "wood", "ends_at": future, "notified": False},
            {"resource": "ore", "ends_at": future, "notified": False},
            {"resource": "fish", "ends_at": future, "notified": False},
        ],
        buff_kind="income", buff_until=future_dt, bonus_kind=None,
        bonus_offered_at=datetime.now(timezone.utc), bonus_next_at=None,
        story={}, chat_id=None, tavern=tavern,
        craft_item="kovsh:2", craft_ends_at=future_dt,
        build_item=None, build_ends_at=None,
        hp=35, hp_at=datetime.now(timezone.utc), hunt_ready_at=None,
    )
    tavern.player = player
    return player, tavern


def main() -> int:
    player, tavern = maxed_player()
    cases = {
        "tavern_screen": lambda: texts.tavern_screen(player, tavern),
        "warehouse_screen": lambda: texts.warehouse_screen(player, tavern),
        "storehouse_caption": lambda: texts.storehouse_caption(player, tavern),
        "character_screen": lambda: texts.character_screen(player, texts.craft_line(player)),
        "forge_screen": lambda: texts.forge_screen(player),
        "auction_screen": lambda: texts.auction_screen(tavern),
    }
    fails = 0
    print(f"Лимит подписи: {LIMIT} UTF-16 code units\n")
    for name, fn in cases.items():
        try:
            s = fn()
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {name}: ИСКЛЮЧЕНИЕ при рендере — {e!r}")
            fails += 1
            continue
        n = utf16(s)
        mark = "✅" if n <= LIMIT else "❌ ПРЕВЫШЕН"
        if n > LIMIT:
            fails += 1
        print(f"  {mark} {name}: {n} / {LIMIT}  (запас {LIMIT - n})")
    print()
    if fails:
        print(f"❌ Проблемных подписей: {fails}")
        return 1
    print("✅ Все подписи помещаются в лимит")
    return 0


sys.exit(main())
