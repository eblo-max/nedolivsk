"""CI-матрица баланса: эталонные билды × бестиарий. Ловит развал полос сложности
при ЛЮБОМ ребалансе (статов, врагов, формул) — до пуша, а не на игроках.
"""

import os
import random
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import combat  # noqa: E402

BUILDS = {
    "naked":  (1, {}),
    "start":  (2, {"weapon": "kovsh:1", "chest": "fartuk:1", "head": "leather_cap:1",
                   "left_hand": "oak_shield:1"}),
    "hunter": (4, {"weapon": "fang_cleaver:2", "chest": "fur_coat:2", "boots": "swift_boots:2",
                   "head": "leather_cap:2", "belt": "lynx_belt:2", "left_hand": "oak_shield:2"}),
    "forge3": (6, {"weapon": "kovsh:3", "chest": "fur_coat:3", "head": "leather_cap:3",
                   "left_hand": "oak_shield:3", "boots": "sapogi:3", "belt": "lynx_belt:3",
                   "talisman": "prestige_ring:3", "legs": "strong_pants:3"}),
    "orcset": (8, {"weapon": "orc_axe:3", "chest": "orc_plate:3", "head": "orc_helm:3",
                   "left_hand": "oak_shield:3", "boots": "swift_boots:3", "belt": "lynx_belt:3",
                   "talisman": "prestige_ring:3", "legs": "strong_pants:3"}),
    "bis":    (10, {"weapon": "dragon_fang:3", "chest": "dragon_scale:3", "head": "rat_crown:3",
                    "left_hand": "oak_shield:3", "boots": "swift_boots:3", "belt": "lynx_belt:3",
                    "talisman": "dragon_heart:3", "amulet": "troll_eye:3", "legs": "strong_pants:3",
                    "right_hand": "rat_tail:3", "bag": "sumka:3"}),
}

# Полосы: (билд, зверь) → допустимый коридор винрейта. «Владельцы» яруса держат
# прогресс-полосу ~50-80; фарм ≥90; стены ≤15 (психология полос: 85/70/50/15).
BANDS = [
    ("naked", "zayac", 90, 100), ("naked", "lisa", 70, 95), ("naked", "gadyuka", 15, 55),
    ("naked", "olen", 0, 10),
    ("start", "olen", 50, 85), ("start", "volk", 55, 88), ("start", "kaban", 40, 78),
    ("start", "vozhak", 0, 12),
    ("hunter", "vozhak", 50, 82), ("hunter", "lynx", 55, 85), ("hunter", "tusker", 50, 82),
    ("hunter", "scorpion", 45, 78), ("hunter", "medved", 0, 15),
    ("forge3", "medved", 45, 80), ("forge3", "razboy", 55, 85), ("forge3", "ataman", 0, 15),
    ("orcset", "ataman", 50, 82), ("orcset", "ogr", 40, 75), ("orcset", "lich", 0, 15),
    ("bis", "wyvern", 55, 85), ("bis", "lich", 25, 60),
]


def _stats(name):
    lvl, eq = BUILDS[name]
    p = NS(level=lvl, equipment=eq, buff_kind=None, buff_until=None, hp=None, hp_at=None)
    return combat.player_stats(p), combat.max_hp(p)


def _win(build, enemy_id):
    st, hp = _stats(build)
    return combat.forecast(st, combat.ENEMY[enemy_id], hp, n=500, rng=random.Random(7))[0]


def test_difficulty_bands():
    bad = []
    for build, enemy, lo, hi in BANDS:
        w = _win(build, enemy)
        if not (lo <= w <= hi):
            bad.append(f"{build}×{enemy}: {w} вне [{lo},{hi}]")
    assert not bad, "полосы развалились: " + "; ".join(bad)


def test_progression_monotonic():
    """Более прокачанный билд не бьёт хуже ни по одному зверю (кривая мощности)."""
    order = ["naked", "start", "hunter", "forge3", "orcset", "bis"]
    for e in combat.ENEMIES:
        prev = -1
        for b in order:
            w = _win(b, e.id)
            assert w >= prev - 6, f"{b}×{e.id}: {w} < {prev} (регресс силы)"
            prev = max(prev, w)


def test_every_build_has_midband_content():
    """У каждой стадии есть ≥2 целей в «интересной середине» (25–85%) — игра не
    вырождается в «всё 0 или всё 100» ни на одном этапе прогрессии."""
    for b in BUILDS:
        mids = sum(1 for e in combat.ENEMIES if 25 <= _win(b, e.id) <= 85)
        assert mids >= 2, f"{b}: только {mids} целей в середине"


def test_hp_axis_works():
    _st_naked, hp_naked = _stats("naked")
    st_bis, hp_bis = _stats("bis")
    assert hp_naked == 35                      # новичок — как до пересмотра
    assert 140 <= hp_bis <= 190                # ветеран «мясной», но не бессмертный
    assert st_bis["armor"] <= 120              # кап брони держит
