"""«Тайные рецепты» — сквозная интеграция БЕЗ БД (фейки игрока/таверны).

Доказываем: сваренное блюдо реально пьётся как фляга (combat.flask_apply), списывается
из своего склада, а урон в рейде == его склад-числам через ту же flask_mods (показ=
действие). Плюс: чужой/неизвестный ключ не срабатывает, слоты фляги соблюдаются.
"""
import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, combat, raid, recipes  # noqa: E402


def _fresh(recipe: dict, qty: int = 3):
    """Игрок с таверной, у которого на складе `qty` порций блюда (и оно в кэше)."""
    recipes.note_recipe(recipe)
    t = NS(products={}, recipes_stock={recipe["key"]: qty})
    p = NS(tavern=t, level=5)
    return p, t


def test_cooked_dish_drinks_and_consumes_from_stock():
    rec = recipes.build_recipe(["game", "herbs", "honey", "salt"])   # hp+dmg+crit
    p, t = _fresh(rec, qty=2)
    stats: dict = {}
    chp, used, labels = combat.flask_apply(p, [rec["key"]], stats, 0)
    assert used == [rec["key"]]                                      # блюдо применилось
    assert recipes.stock_get(t, rec["key"]) == 1                    # порция списана
    # эффекты влиты в stats/chp ровно как в рецепте
    eff = rec["effects"]
    assert chp == eff.get("hp", 0)
    assert stats.get("damage", 0) == eff.get("dmg", 0)
    assert stats.get("crit", 0) == eff.get("crit", 0)
    assert labels and labels[0] == recipes.cellar_label(eff)


def test_raid_damage_matches_stock_numbers_show_equals_apply():
    """Показ=действие: урон блюда в рейде == его склад-числа через конверсию hp/dodge."""
    rec = recipes.build_recipe(["grain", "game", "milk", "honey"])   # тяжёлый hp
    p, t = _fresh(rec)
    eff = rec["effects"]
    expect = (eff.get("dmg", 0) + eff.get("hp", 0) // raid.RAID_HP_TO_DMG
              + eff.get("dodge", 0) // raid.RAID_DODGE_TO_DMG)
    assert raid.flask_mods([rec["key"]])["dmg"] == expect           # метка==бой
    # и flask_label (то, что видит игрок в рейде) — из той же flask_mods
    assert raid.flask_label(rec["key"]) != "—"


def test_unowned_or_empty_stock_does_not_apply():
    rec = recipes.build_recipe(["fish", "salt"])
    recipes.note_recipe(rec)
    t = NS(products={}, recipes_stock={})                            # склад пуст
    p = NS(tavern=t, level=3)
    _chp, used, _l = combat.flask_apply(p, [rec["key"]], {}, 0)
    assert used == []                                               # нечего пить
    assert recipes.stock_get(t, rec["key"]) == 0


def test_unknown_recipe_key_is_ignored():
    t = NS(products={}, recipes_stock={"tr_ghost": 5})              # ключа нет в кэше
    p = NS(tavern=t, level=3)
    _chp, used, _l = combat.flask_apply(p, ["tr_ghost"], {}, 0)
    assert used == []                                               # эффектов нет → пропуск


def test_mixed_static_and_secret_flask_respects_slots():
    """Слоты фляги (FLASK_SLOTS): статик-эль + тайное блюдо, но не больше лимита."""
    rec = recipes.build_recipe(["hops", "malt"])
    recipes.note_recipe(rec)
    t = NS(products={"ale1": 3}, recipes_stock={rec["key"]: 3})
    p = NS(tavern=t, level=4)
    keys = ["ale1", rec["key"], rec["key"]]                         # 3 запрошено
    _chp, used, _l = combat.flask_apply(p, keys, {}, 0)
    assert len(used) <= balance.FLASK_SLOTS
    assert t.products["ale1"] == 2                                  # эль списан из погреба


def test_cellar_label_reads_effects_faithfully():
    assert recipes.cellar_label({"dmg": 6, "crit": 3, "hp": 28}) == "+6 урона, +3% крита, +28 ❤"
    assert recipes.cellar_label({"antidote": True}) == "снимает яд"
    assert recipes.cellar_label({}) == "—"
