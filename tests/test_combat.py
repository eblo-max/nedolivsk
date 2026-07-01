"""Охота: снаряга реально усиливает (выше шанс победы), броня снижает урон."""

import random

from bot.game import combat
from bot.game.items import make_entry
from conftest import make_player


def test_gear_increases_win_chance():
    enemy = combat.ENEMY["volk"]
    weak = combat.player_stats(make_player(level=3, equipment={}))
    strong = combat.player_stats(make_player(
        level=3, equipment={"weapon": make_entry("kovsh", 2)}))
    wp_weak, _ = combat.forecast(weak, enemy, n=300, rng=random.Random(1))
    wp_strong, _ = combat.forecast(strong, enemy, n=300, rng=random.Random(1))
    assert wp_strong >= wp_weak                    # снаряга не вредит, обычно сильно лучше


def test_armor_reduces_damage_taken():
    enemy = combat.ENEMY["medved"]
    no_armor = {"damage": 10, "crit": 0, "armor": 0, "luck": 0, "dmg_taken_mult": 1.0}
    armored = {"damage": 10, "crit": 0, "armor": 60, "luck": 0, "dmg_taken_mult": 1.0}
    _, hp_no = combat.forecast(no_armor, enemy, n=300, rng=random.Random(2))
    _, hp_arm = combat.forecast(armored, enemy, n=300, rng=random.Random(2))
    assert hp_arm >= hp_no                          # в броне остаётся больше HP


def test_gear_progression_vs_toughest():
    """Атаман — стена: голый 0, куётся еле-еле, боссовый шмот открывает его."""
    at = combat.ENEMY["ataman"]
    nogear = combat.player_stats(make_player(level=10, equipment={}))
    craft = combat.player_stats(make_player(level=10, equipment={
        "weapon": make_entry("kovsh", 3), "right_hand": make_entry("master_axe", 3),
        "left_hand": make_entry("oak_shield", 3), "chest": make_entry("fartuk", 3)}))
    boss = combat.player_stats(make_player(level=10, equipment={
        "weapon": make_entry("dragon_fang", 3), "chest": make_entry("dragon_scale", 3),
        "right_hand": make_entry("rat_tail", 3), "left_hand": make_entry("oak_shield", 3)}))
    # бой — от РЕАЛЬНОГО максимума HP персонажа (уровень+vitality), не от базы
    hp_n = combat.max_hp(make_player(level=10, equipment={}))
    hp_c = combat.max_hp(make_player(level=10, equipment={
        "weapon": make_entry("kovsh", 3), "right_hand": make_entry("master_axe", 3),
        "left_hand": make_entry("oak_shield", 3), "chest": make_entry("fartuk", 3)}))
    hp_b = combat.max_hp(make_player(level=10, equipment={
        "weapon": make_entry("dragon_fang", 3), "chest": make_entry("dragon_scale", 3),
        "right_hand": make_entry("rat_tail", 3), "left_hand": make_entry("oak_shield", 3)}))
    rz = combat.ENEMY["razboy"]
    wn, _ = combat.forecast(nogear, rz, hp_n, n=400, rng=random.Random(5))
    wc, _ = combat.forecast(craft, rz, hp_c, n=400, rng=random.Random(5))
    wb, _ = combat.forecast(boss, rz, hp_b, n=400, rng=random.Random(5))
    assert wn < wc < wb                    # прогрессия снаряги (по Т3-разбойнику)
    assert wb >= 90                        # боссовый шмот делает Т3 фармом
    # атаман (Т4): кузня — стена, боссовый шмот открывает
    wca, _ = combat.forecast(craft, at, hp_c, n=400, rng=random.Random(5))
    wba, _ = combat.forecast(boss, at, hp_b, n=400, rng=random.Random(5))
    assert wca <= 15 < wba
