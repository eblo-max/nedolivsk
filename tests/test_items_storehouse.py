"""Снаряга боссов — эксклюзив (не куётся); складская сетка покрывает все ресурсы."""

from bot.game import balance, items, raid, storehouse


def test_boss_gear_is_exclusive_noncraftable():
    boss_gear = {iid for b in raid.BOSSES.values() for iid in b.gear_pool}
    assert boss_gear, "у боссов должен быть лут"
    for iid in boss_gear:
        assert iid in items.CATALOG, iid
        assert items.CATALOG[iid].craftable is False, f"{iid} должен быть не-куётся"


def test_forge_items_are_craftable():
    craftable = [i for i in items.CATALOG.values() if i.craftable]
    assert len(craftable) >= 5
    # эксклюзив боссов в куётся-список не попадает
    boss_gear = {iid for b in raid.BOSSES.values() for iid in b.gear_pool}
    assert not (boss_gear & {i.id for i in craftable})


def test_storehouse_covers_all_resources():
    assert len(storehouse.CELLS) >= len(balance.RESOURCES)        # ячеек хватает
    assert not storehouse.OVERFLOW_RESOURCES                       # ничего не в overflow
    for r in balance.RESOURCES:
        assert r in storehouse.SPRITES, f"нет маппинга иконки для {r}"


def test_storehouse_sprite_files_exist():
    # иконки должны быть в репозитории (а не только локально — урок прошлого)
    for r in balance.RESOURCES:
        name = storehouse.SPRITES[r]
        assert (storehouse.RESURS_DIR / f"{name}.png").is_file(), f"нет файла {name}.png"
