"""Фаза 0 — характеризационный эталон боя на охоте: фиксируем поведение «до»
перебалансировки Фазы 1. Инварианты (монотонность по снаряге, детерминизм,
ранний обрыв на Гадюке) должны пережить любые правки баланса; если тест падает
после Фазы 1 — это осознанное изменение, обновляем снимок вместе с правкой.
"""
import random

from bot.game import combat


def _wr(equip: dict, enemy_id: str, hp: int | None = None,
        n: int = 600, seed: int = 1, level: int = 1) -> int:
    """Винрейт ПЕРСОНАЖА (шмот + уровень + HP-каркас) — как в реальном бою."""
    from types import SimpleNamespace as NS
    p = NS(level=level, equipment=equip, buff_kind=None, buff_until=None,
           hp=None, hp_at=None)
    stats = combat.player_stats(p)
    enemy = combat.ENEMY[enemy_id]
    return combat.forecast(stats, enemy, hp or combat.max_hp(p),
                           n=n, rng=random.Random(seed))[0]


NAKED: dict = {}
AXE = {"right_hand": "master_axe:1"}
FULL = {"weapon": "kovsh:1", "chest": "fartuk:1",
        "left_hand": "oak_shield:1", "head": "leather_cap:1"}
MASTER = {slot: entry.split(":")[0] + ":3" for slot, entry in FULL.items()}


def test_naked_smooth_gradient_no_cliff():
    """Голыми руками: снимок ПОСЛЕ бестиария (звери → фэнтези-монстры) — первые
    две цели стали верняком, гадюка — стеной для голых рук. Глобальную плавность
    кривой (не-бинарность) сторожит test_winrate_is_smooth_not_binary."""
    z, lisa, g = _wr(NAKED, "zayac"), _wr(NAKED, "lisa"), _wr(NAKED, "gadyuka")
    assert z >= 90                 # первая цель — верняк для новичка
    assert 70 <= lisa <= 95        # вторая — уверенно, но не гарант
    assert 15 <= g <= 55           # медуза — первый настоящий вызов (не 0 и не 100)
    assert z >= lisa > g           # монотонно сложнее


def test_winrate_is_smooth_not_binary():
    """Ядро Фазы 1.5: на среднем ките много «середин» (1-99%), а не только 0/100."""
    kit = {"weapon": "fang_cleaver:1", "chest": "fur_coat:1", "head": "leather_cap:1",
           "left_hand": "oak_shield:1", "belt": "lynx_belt:1"}   # компонентка с охоты T1
    wrs = [_wr(kit, eid, level=3) for eid in combat.ENEMY]
    middles = sum(1 for w in wrs if 5 < w < 95)
    # переходный кит живёт ~день: одной честной цели-мостика (упырь) достаточно.
    # Строгие полосы ВСЕХ шести стадий сторожит tests/test_balance_matrix.py.
    assert middles >= 1, f"кривая снова бинарная: {wrs}"


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
