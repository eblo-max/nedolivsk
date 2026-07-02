"""Матрица винрейтов: эталонные билды × все звери. Запускать до/после ребаланса."""
import os
import random
import pathlib
import sys

os.environ.setdefault("BOT_TOKEN", "test:test")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace as NS

from bot.game import combat

BUILDS = [
    ("голый ур.1",      1, {}),
    ("старт ★ ур.2",    2, {"weapon": "kovsh:1", "chest": "fartuk:1", "head": "leather_cap:1",
                            "left_hand": "oak_shield:1"}),
    ("охотник ★★ ур.4", 4, {"weapon": "fang_cleaver:2", "chest": "fur_coat:2", "boots": "swift_boots:2",
                            "head": "leather_cap:2", "belt": "lynx_belt:2", "left_hand": "oak_shield:2"}),
    ("кузня ★★★ ур.6",  6, {"weapon": "kovsh:3", "chest": "fur_coat:3", "head": "leather_cap:3",
                            "left_hand": "oak_shield:3", "boots": "sapogi:3", "belt": "lynx_belt:3",
                            "talisman": "prestige_ring:3", "legs": "strong_pants:3"}),
    ("орк-сет ★★★ ур.8", 8, {"weapon": "orc_axe:3", "chest": "orc_plate:3", "head": "orc_helm:3",
                             "left_hand": "oak_shield:3", "boots": "swift_boots:3", "belt": "lynx_belt:3",
                             "talisman": "prestige_ring:3", "legs": "strong_pants:3"}),
    ("рейд-BiS ★★★ ур.10", 10, {"weapon": "dragon_fang:3", "chest": "dragon_scale:3", "head": "rat_crown:3",
                                "left_hand": "oak_shield:3", "boots": "swift_boots:3", "belt": "lynx_belt:3",
                                "talisman": "dragon_heart:3", "amulet": "troll_eye:3", "legs": "strong_pants:3",
                                "right_hand": "rat_tail:3", "bag": "sumka:3"}),
]


def build_player(level, eq):
    return NS(level=level, equipment=eq, buff_kind=None, buff_until=None,
              hp=None, hp_at=None)


def main():
    enemies = list(combat.ENEMIES)
    name_w = max(len(b[0]) for b in BUILDS)
    header = " " * (name_w + 22) + " ".join(f"{e.id[:6]:>6}" for e in enemies)
    print(header)
    for bname, lvl, eq in BUILDS:
        p = build_player(lvl, eq)
        stats = combat.player_stats(p)
        hp = combat.max_hp(p)
        row = []
        for e in enemies:
            w, _ = combat.forecast(stats, e, hp, n=600, rng=random.Random(1))
            row.append(f"{w:>6}")
        meta = f"hp={hp:<4} d={stats.get('damage',0):<3} a={stats.get('armor',0):<3}"
        print(f"{bname:<{name_w}} {meta} " + " ".join(row))


if __name__ == "__main__":
    main()
