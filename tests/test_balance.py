"""Баланс: полнота словарей ресурсов, добыча по зонам, стоимость апгрейда (камень)."""

from bot import texts
from bot.game import balance


def test_all_resources_present_in_every_dict():
    for r in balance.RESOURCES:
        assert r in balance.RESOURCE_NAMES, r
        assert r in balance.RESOURCE_EMOJI, r
        assert r in balance.RESOURCE_PRICE, r
        assert r in balance.EXPEDITION_YIELD, r
        assert r in texts.RESOURCE_INSTRUMENTAL, r       # тот, что ломал нотифаер


def test_expedition_yield_region_modifiers():
    base = balance.expedition_yield("wood", 1, "green_valleys")        # нейтрально
    bonus = balance.expedition_yield("wood", 1, "north_wilds")         # лес — бонус
    penalty = balance.expedition_yield("grain", 1, "north_wilds")      # мороз — штраф
    base_grain = balance.expedition_yield("grain", 1, "green_valleys")
    assert bonus > base
    assert penalty < base_grain
    assert balance.expedition_yield("stone", 1, "north_wilds") == \
        balance.expedition_yield("stone", 1, "red_wastes")             # камень нейтрален


def test_expedition_yield_grows_with_level():
    assert balance.expedition_yield("ore", 10, "green_valleys") > \
        balance.expedition_yield("ore", 1, "green_valleys")


def test_upgrade_cost_stone_from_level_5():
    assert "stone" not in balance.upgrade_cost(4)
    assert "stone" not in balance.upgrade_cost(1)
    assert balance.upgrade_cost(5)["stone"] > 0
    assert balance.upgrade_cost(6)["stone"] > balance.upgrade_cost(5)["stone"]
    for lvl in range(1, 11):
        c = balance.upgrade_cost(lvl)
        assert c["gold"] > 0 and c["wood"] > 0
