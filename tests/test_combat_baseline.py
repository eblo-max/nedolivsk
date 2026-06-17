"""Фаза 0 — характеризационный эталон боя на охоте: фиксируем поведение «до»
перебалансировки Фазы 1. Инварианты (монотонность по снаряге, детерминизм,
ранний обрыв на Гадюке) должны пережить любые правки баланса; если тест падает
после Фазы 1 — это осознанное изменение, обновляем снимок вместе с правкой.
"""
import random

from bot.game import balance, combat, items


def _wr(equip: dict, enemy_id: str, hp: int | None = None,
        n: int = 600, seed: int = 1) -> int:
    stats = dict(items.combat_stats(equip))
    enemy = combat.ENEMY[enemy_id]
    return combat.forecast(stats, enemy, hp or balance.BASE_HP,
                           n=n, rng=random.Random(seed))[0]


NAKED: dict = {}
AXE = {"right_hand": "master_axe:1"}
FULL = {"weapon": "kovsh:1", "chest": "fartuk:1",
        "left_hand": "oak_shield:1", "head": "leather_cap:1"}
MASTER = {slot: entry.split(":")[0] + ":3" for slot, entry in FULL.items()}


def test_naked_does_starters_not_viper():
    """Голыми руками — мелочь берётся, а Гадюка (спайк-урон) нет: ранний обрыв."""
    assert _wr(NAKED, "zayac") >= 95
    assert _wr(NAKED, "lisa") >= 85
    assert _wr(NAKED, "gadyuka") <= 15


def test_gear_monotonic_per_enemy():
    """Полный мастер-кит не даёт меньший винрейт, чем голые руки, ни по кому."""
    for eid in combat.ENEMY:
        assert _wr(MASTER, eid) >= _wr(NAKED, eid) - 2


def test_master_kit_clears_early_midgame():
    for eid in ("zayac", "lisa", "gadyuka", "olen", "volk", "kaban"):
        assert _wr(MASTER, eid) >= 90


def test_forecast_deterministic_with_seed():
    assert _wr(AXE, "olen", seed=42) == _wr(AXE, "olen", seed=42)


def test_apex_needs_top_gear():
    """Атаман — стена для всего, кроме топ-снаряги (эталон верхней планки)."""
    assert _wr(NAKED, "ataman") == 0
    assert _wr(AXE, "ataman") <= 10
