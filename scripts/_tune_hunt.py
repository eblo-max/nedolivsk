"""Песочница тюнинга охоты (Фаза 1б): подменяет hp/attack/armor зверей в памяти
и печатает матрицу винрейтов + пробу статов. Числа НЕ трогают combat.py, пока не
выберем финал. Запуск: PYTHONPATH=. python scripts/_tune_hunt.py
"""
import random
from dataclasses import replace

from bot.game import balance, combat, items

STAGES = {
    "naked": {},
    "topor★": {"right_hand": "master_axe:1"},
    "top+fart★": {"right_hand": "master_axe:1", "chest": "fartuk:1"},
    "ковш★full": {"weapon": "kovsh:1", "chest": "fartuk:1",
                  "left_hand": "oak_shield:1", "head": "leather_cap:1"},
    "крит-кит": {"weapon": "kovsh:1", "chest": "fartuk:1", "head": "leather_cap:1"},
    "удача-кит": {"chest": "fartuk:1", "head": "leather_cap:1",
                  "amulet": "kruzhka:1", "talisman": "rooster_talisman:1"},
    "мастер★★★": {"weapon": "kovsh:3", "chest": "fartuk:3",
                  "left_hand": "oak_shield:3", "head": "leather_cap:3"},
    "дракон": {"weapon": "dragon_fang:3", "chest": "dragon_scale:3",
               "talisman": "dragon_heart:3"},
}


def matrix(enemies):
    rng = random.Random(42)
    print("зверь".ljust(13), " ".join(s.rjust(10) for s in STAGES))
    for e in enemies:
        cells = []
        for eq in STAGES.values():
            stats = dict(items.combat_stats(eq))
            wr, _ = combat.forecast(stats, e, balance.BASE_HP, n=300, rng=rng)
            cells.append(f"{wr}%".rjust(10))
        print(f"{e.name[:12]:13}", " ".join(cells))


def probe(enemies):
    base_eq = {"weapon": "kovsh:1", "chest": "fartuk:1"}

    def mean(extra):
        rng = random.Random(7)
        stats = dict(items.combat_stats(base_eq))
        for k, v in extra.items():
            stats[k] = stats.get(k, 0) + v
        return sum(combat.forecast(stats, e, balance.BASE_HP, n=400, rng=rng)[0]
                   for e in enemies) / len(enemies)
    b = mean({})
    print(f"\nпроба статов (база {b:.1f}%):")
    for label, ex in (("+8 урон", {"damage": 8}), ("+10 крит", {"crit": 10}),
                      ("+10 броня", {"armor": 10}), ("+10 удача", {"luck": 10})):
        print(f"  {label:10} Δ={mean(ex) - b:+.1f}")


# Кандидат-набор: (id) -> (hp, attack, armor). Цель — лесенка с серединами,
# армор у середняков (крит-пробой), высокая атака у глушек (уворот-удача).
CAND = {
    "zayac":   (8, 2, 0),
    "lisa":    (18, 4, 0),
    "gadyuka": (28, 9, 0),    # глушка: высокая атака, мало HP — уворот спасает
    "olen":    (54, 7, 1),
    "volk":    (46, 8, 2),    # середина на топор+фартук
    "kaban":   (66, 9, 6),    # бронированный середняк — крит-пробой
    "vozhak":  (88, 12, 4),   # плацдарм на ковш★, добивается компонент-снарягой (Ф2)
    "medved":  (90, 12, 8),   # середина на тесак★ (Ф2), танк — крит-пробой
    "razboy":  (94, 13, 6),   # середина на тесак★ (Ф2)
    "ataman":  (215, 30, 13),  # апекс — топ-снаряга/мастер
}


def apply(cand):
    out = []
    for e in combat.ENEMIES:
        hp, att, arm = cand[e.id]
        out.append(replace(e, hp=hp, attack=att, armor=arm))
    return out


if __name__ == "__main__":
    print("════ ТЕКУЩИЕ ════")
    matrix(combat.ENEMIES)
    probe(combat.ENEMIES)
    print("\n════ КАНДИДАТ ════")
    cand = apply(CAND)
    matrix(cand)
    probe(cand)
