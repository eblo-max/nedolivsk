"""Ф2b: эксклюзив-рецепты зодчих — гейт варки/ковки по владению (Лавка Артели).

Инвариант: имба-товар/шмотку можно готовить ТОЛЬКО с рецептом, купленным за
зодары. Гейт продублирован (production.EXCLUSIVE + items.WONDER_GEAR) и проверен
и как чистый предикат, и в самих start_*-функциях (серверная защита).
"""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, items, logic, production  # noqa: E402


def _tavern():
    return NS(level=1, products={}, production={}, upgrades=[], buildings=[],
              reputation=0, comfort=0, capacity=20, income_rate=10,
              last_income_at=None, rep_progress=0, auction_sold=0, auction=None)


def _player(tav, recipes=None):
    # инвентарь щедрый: сырьё + полуфабрикаты (мука/слиток нужны для каравая/молота)
    stock = {k: 9999 for k in (*balance.RESOURCES, *balance.GOODS_NAMES)}
    return NS(level=1, gold=100000, equipment={}, region="green_valleys",
              inventory=stock,
              buff_kind=None, buff_until=None, perks={}, econ={},
              story={"artel": {"recipes": list(recipes or [])}},
              craft_item=None, craft_ends_at=None, craft_notified=False,
              tavern=tav, hp=None, hp_at=None)


# ── чистые предикаты гейта ──────────────────────────────────────────────
def test_recipe_locked_predicate():
    tav = _tavern()
    p = _player(tav)
    for key in production.EXCLUSIVE:
        assert production.recipe_locked(p, key)                 # нет рецепта — заперто
    assert not production.recipe_locked(p, "roast")             # обычный — открыт всегда
    owner = _player(tav, recipes=list(production.EXCLUSIVE))
    for key in production.EXCLUSIVE:
        assert not production.recipe_locked(owner, key)         # владеет — открыт


def test_wonder_gear_locked_predicate():
    tav = _tavern()
    p = _player(tav)
    for gid in items.WONDER_GEAR:
        assert items.wonder_gear_locked(p, gid)
    assert not items.wonder_gear_locked(p, "kovsh")             # обычная снаряга — не заперта
    owner = _player(tav, recipes=list(items.WONDER_GEAR))
    for gid in items.WONDER_GEAR:
        assert not items.wonder_gear_locked(owner, gid)


# ── гейт в самих start_*-функциях (серверная защита) ────────────────────
def test_start_production_blocked_then_opened():
    starters = {
        "zodchy_feast": lambda p, t: production.start_kitchen(p, t, "zodchy_feast"),
        "artel_nectar": lambda p, t: production.start_winery(p, t, "artel_nectar"),
        "thunder_sbiten": lambda p, t: production.start_meadery(p, t, "thunder_sbiten"),
        "mason_loaf": lambda p, t: production.start_recipe(p, t, "bakery", "mason_loaf"),
    }
    for key, run in starters.items():
        tav = _tavern()
        locked = run(_player(tav), tav)
        assert locked[:2] == (False, "locked"), f"{key}: без рецепта должно быть locked"
        tav2 = _tavern()
        opened = run(_player(tav2, recipes=[key]), tav2)
        assert opened[0] is True, f"{key}: с рецептом и сырьём должно запуститься"
        assert (tav2.production or {}).get(production.EXCLUSIVE[key])  # партия заложена в здание


def test_start_craft_gear_blocked_then_opened():
    tav = _tavern()
    locked = logic.start_craft(_player(tav), "zodchy_hammer")
    assert not locked.ok and locked.reason == "locked"
    tav2 = _tavern()
    opened = logic.start_craft(_player(tav2, recipes=["zodchy_hammer"]), "zodchy_hammer")
    assert opened.ok, "с рецептом «Молот Зодчего» должен куеться"


# ── имба-инвариант: эффекты реально сильнее лучших обычных ───────────────
def test_exclusive_flask_effects_are_top_tier():
    fe = balance.FLASK_EFFECTS
    assert fe["thunder_sbiten"]["dmg"] > fe["ale3"]["dmg"] * 2          # урон ×3.1
    assert fe["artel_nectar"]["crit"] > fe["wine"]["crit"] * 2          # крит ×3.3
    assert fe["zodchy_feast"]["hp"] > fe["roast"]["hp"] * 2             # HP ×3.2
    assert fe["mason_loaf"]["dodge"] > fe["mead"]["dodge"]              # уворот сильнее
    assert fe["mason_loaf"].get("antidote")                            # + антидот


def test_exclusive_goods_registered_and_priced():
    for key in production.EXCLUSIVE:
        g = production.GOODS.get(key)
        assert g and g.price > 15, f"{key}: нет в GOODS или дёшев"
    # шмотка сильнее лучшего рейд-оружия и укладывается в бюджет 'wonder'
    hammer = items.CATALOG["zodchy_hammer"]
    dragon = items.CATALOG["dragon_fang"]
    assert hammer.damage > dragon.damage and hammer.crit > dragon.crit


def test_exclusive_goods_sold_only_p2p_on_bourse():
    """Решение по балансу: имба-расходники продаются ТОЛЬКО игрокам на бирже —
    НЕ гостям (розница), НЕ купцу, НЕ на аукционе НПС."""
    import random as _r
    from bot.game import auction, logic, trade

    ex = next(iter(production.EXCLUSIVE))            # любой эксклюзив-товар
    normal = "ale1"

    # розница: гости не покупают эксклюзив, обычное — да
    tav = _tavern()
    tav.capacity, tav.reputation = 200, 1000
    tav.products = {ex: 500, normal: 500}
    want, _pu, _pl = logic._retail_demand(tav, hours=10, demand_mult=3.0, food_mult=1.0)
    assert ex not in want and want.get(normal, 0) > 0

    # купец: с одним лишь эксклюзивом в погребе — нечего продать, оффера нет
    tav_ex = _tavern(); tav_ex.products = {ex: 500}
    assert trade.has_sellable(tav_ex) is False
    assert trade.make_offer(tav_ex, _player(tav_ex), fair=False,
                            rng=_r.Random(0), world=None) is None
    tav_n = _tavern(); tav_n.products = {normal: 500}
    assert trade.has_sellable(tav_n) is True

    # аукцион: эксклюзив не в списке и создать лот нельзя (серверный гейт)
    tav_a = _tavern(); tav_a.products = {ex: 500, normal: 500}
    assert ex not in auction.sellable_goods(tav_a) and normal in auction.sellable_goods(tav_a)
    ok, reason = auction.create(_player(tav_a), tav_a, ex, qty=5, unit_min=99)
    assert not ok and reason == "empty"

    # биржа (P2P): эксклюзив продавать МОЖНО — канал открыт
    assert production.npc_tradable(ex) is False and production.npc_tradable(normal) is True


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def test_bot_keyboards_hide_exclusives():
    """Легаси-бот НЕ показывает эксклюзив зодчих (иначе кнопка-пустышка): ни рецептов
    в пекарне, ни «Молота» в кузнице. Эксклюзив — фича мини-аппа."""
    from bot.game import buildings
    from bot.keyboards import inline as kb

    tav = _tavern()
    p = _player(tav, recipes=list(production.EXCLUSIVE) + list(items.WONDER_GEAR))  # даже владелец
    bakery = kb.production_kb(p, tav, buildings.CATALOG["bakery"])
    cbs = " ".join(_callbacks(bakery))
    for key in production.EXCLUSIVE:                      # ни один эксклюзив-рецепт не в кнопках
        assert key not in cbs, f"пекарня показала {key}"
    assert "mason_loaf" not in cbs and "bread" in cbs    # обычный хлеб остался

    forge = kb.forge_kb(p)
    fcbs = " ".join(_callbacks(forge))
    for gid in items.WONDER_GEAR:
        assert gid not in fcbs, f"кузница показала {gid}"
    assert "kovsh" in fcbs                               # обычная снаряга куётся
