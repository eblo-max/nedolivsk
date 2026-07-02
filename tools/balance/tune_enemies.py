"""Авто-тюнер зверей: подбирает (hp, attack) каждого под целевой винрейт
билда-владельца. Печатает готовые статы для вставки в combat.py."""
import os
import random
import pathlib
import sys
from dataclasses import replace

os.environ.setdefault("BOT_TOKEN", "test:test")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from sim_matrix import BUILDS, build_player  # noqa: E402
from bot.game import combat  # noqa: E402

# зверь → (индекс билда-владельца, целевой винрейт владельца)
TARGETS = {
    "zayac": (0, 96), "lisa": (0, 85), "gadyuka": (0, 55),
    "olen": (1, 75), "volk": (1, 68), "kaban": (1, 60),
    "lynx": (2, 70), "tusker": (2, 66), "scorpion": (2, 62), "vozhak": (2, 72),
    "razboy": (3, 72), "medved": (3, 62),
    "ataman": (4, 65),
    "ogr": (4, 58), "wyvern": (5, 70), "lich": (5, 45),
}

STATS = {}
for b in BUILDS:
    p = build_player(b[1], b[2])
    STATS[b[0]] = (combat.player_stats(p), combat.max_hp(p))


def win(build_idx, enemy):
    st, hp = STATS[BUILDS[build_idx][0]]
    return combat.forecast(st, enemy, hp, n=500, rng=random.Random(7))[0]


def tune(e, owner, target):
    cur = e
    for _ in range(40):
        w = win(owner, cur)
        if abs(w - target) <= 4:
            return cur, w
        # мимо цели: крутим hp и attack небольшими шагами
        if w > target:   # слишком легко — усиливаем
            cur = replace(cur, hp=int(cur.hp * 1.12) + 1,
                          attack=round(cur.attack * 1.08 + 0.4, 1))
        else:            # слишком тяжело — ослабляем
            cur = replace(cur, hp=max(6, int(cur.hp * 0.92)),
                          attack=max(1, round(cur.attack * 0.94, 1)))
    return cur, win(owner, cur)


print(f"{'зверь':<10} {'hp':>4}→{'hp2':>4} {'atk':>5}→{'atk2':>5}  win_владельца")
for e in combat.ENEMIES:
    if e.id not in TARGETS:
        continue
    owner, target = TARGETS[e.id]
    tuned, w = tune(e, owner, target)
    print(f"{e.id:<10} {e.hp:>4}→{tuned.hp:>4} {e.attack:>5}→{tuned.attack:>5}  "
          f"{w} (цель {target}, билд «{BUILDS[owner][0]}»)")
