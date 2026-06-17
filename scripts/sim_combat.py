"""Полная боевая симуляция: перебор значимых билдов снаряжения против всех зверей.

Считает на реальном движке (combat.win_chance — логистика от всех статов) + Монте-
Карло реализацию критов/уворотов. Помогает после правок баланса увидеть кривую,
оптимум, лучший-билд-под-зверя (идентичность статов) и что ковать дальше.

    python scripts/sim_combat.py                 # синтетические билды (без БД)
    python scripts/sim_combat.py --region north_wilds
    PROD_URL=... python scripts/sim_combat.py --prod 5731136459   # реальный аккаунт

Прод-режим только читает (id игрока) и требует переменную PROD_URL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics

from bot.game import balance, combat, items


def stats_of(eq):
    return dict(items.combat_stats(eq))


def wr(eq, enemy, hp=balance.BASE_HP):
    return round(combat.win_chance(stats_of(eq), enemy, hp) * 100)


def mean_wr(eq, beasts):
    return statistics.mean(combat.win_chance(stats_of(eq), e) * 100 for e in beasts)


def fmt_stats(eq):
    s = stats_of(eq)
    dmg = balance.BASE_DAMAGE + s.get("damage", 0)
    crit = min(balance.HUNT_CRIT_CAP, s.get("crit", 0))
    dodge = int(min(balance.HUNT_LUCK_DODGE_CAP, s.get("luck", 0) * balance.HUNT_LUCK_DODGE_PER))
    return f"урон{dmg} крит{crit}% броня{s.get('armor',0)} уворот{dodge}%"


def montecarlo(eq, enemy, n=8000, seed=1):
    rng = random.Random(seed)
    st = stats_of(eq)
    wins = crits = rounds = with_crit = 0
    hp_left = []
    for _ in range(n):
        f = combat.resolve(st, enemy, balance.BASE_HP, rng)
        wins += f.win
        crits += f.crits
        rounds += f.rounds
        with_crit += 1 if f.crits else 0
        if f.win:
            hp_left.append(f.hp_left)
    return {"win": round(wins * 100 / n), "avg_crits": round(crits / n, 2),
            "avg_rounds": round(rounds / n, 1), "crit_fights": round(with_crit * 100 / n),
            "hp_med": (round(statistics.median(hp_left)) if hp_left else 0)}


# Значимое пространство билдов (архетипы × ярус 1/3) + пошаговое оружие
def loadouts(base: dict):
    L = {"голый": {}, "база (как есть)": dict(base)} if base else {"голый": {}}
    for w in ("master_axe:1", "kovsh:1", "fang_cleaver:1", "kovsh:3", "dragon_fang:3"):
        it = items.CATALOG[w.split(":")[0]]
        L[f"+{it.name} {'★' * int(w.split(':')[1])}"] = {**base, it.slot: w}
    arch = {
        "УРОН": {"weapon": "kovsh", "right_hand": "master_axe", "chest": "fartuk",
                 "head": "leather_cap", "left_hand": "oak_shield"},
        "КРИТ": {"weapon": "kovsh", "right_hand": "rat_tail", "chest": "fartuk",
                 "head": "leather_cap", "belt": "lynx_belt"},
        "УДАЧА-уворот": {"weapon": "fang_cleaver", "chest": "fur_coat", "boots": "swift_boots",
                         "amulet": "kruzhka", "talisman": "rooster_talisman", "bag": "sumka"},
        "ТЕСАК-сет": {"weapon": "fang_cleaver", "chest": "fur_coat", "left_hand": "oak_shield",
                      "head": "leather_cap", "boots": "swift_boots", "belt": "tusk_belt"},
        "БОСС": {"weapon": "dragon_fang", "chest": "dragon_scale", "talisman": "dragon_heart",
                 "left_hand": "troll_hide", "head": "rat_crown"},
    }
    for name, b in arch.items():
        for t in (1, 3):
            L[f"{name} ★{'★★' if t == 3 else ''}"] = {s: f"{i}:{t}" for s, i in b.items()}
    return L


def report(base: dict, beasts, label: str):
    print(f"\n════ БОЕВАЯ СИМУЛЯЦИЯ — {label} ════")
    if base:
        print(f"База: {base} → {fmt_stats(base)}")
    L = loadouts(base)

    print("\n── ВИНРЕЙТ ПО БИЛДАМ (полный HP) ──")
    print("билд".ljust(26) + "".join(e.name[:6].rjust(7) for e in beasts) + "   ср.")
    for name, eq in sorted(L.items(), key=lambda kv: -mean_wr(kv[1], beasts)):
        print(f"{name[:25]:26}" + "".join(f"{wr(eq,e):>6}%" for e in beasts)
              + f"{mean_wr(eq, beasts):6.0f}")

    print("\n── ЛУЧШИЙ КРАФТ-БИЛД ★ ПОД ЗВЕРЯ (идентичность статов, равный ярус) ──")
    id_names = ("УРОН ★", "КРИТ ★", "УДАЧА-уворот ★", "ТЕСАК-сет ★")
    t1 = {k: L[k] for k in id_names if k in L}
    for e in beasts:
        ranked = sorted(t1.items(), key=lambda kv: -combat.win_chance(stats_of(kv[1]), e))
        best, second = ranked[0], ranked[1]
        print(f"  {e.name:16} → {best[0][:14]:15} {wr(best[1], e):3}%  "
              f"(2-й: {second[0][:14]} {wr(second[1], e)}%)")

    print("\n── МОНТЕ-КАРЛО (реальные криты/увороты, vs средний зверь) ──")
    mid = beasts[len(beasts) // 2]
    for name in ("ТЕСАК-сет ★", "КРИТ ★★★", "УДАЧА-уворот ★★★"):
        if name in L:
            m = montecarlo(L[name], mid)
            print(f"  {name[:18]:19} vs {mid.name}: факт={m['win']}% критов/бой~{m['avg_crits']}"
                  f" (в {m['crit_fights']}%) раундов~{m['avg_rounds']} hp-ост~{m['hp_med']}")

    if base:
        print("\n── ЧТО КОВАТЬ ДАЛЬШЕ (1 предмет к базе) ──")
        b0 = mean_wr(base, beasts)
        cand = []
        for it in items.CATALOG.values():
            if it.craftable:
                cand.append((it.name, it.slot, mean_wr({**base, it.slot: f"{it.id}:1"}, beasts) - b0))
        for nm, slot, g in sorted(cand, key=lambda x: -x[2])[:6]:
            print(f"  +{nm[:24]:25} ({slot:10}) +{g:.0f}")


async def from_prod(pid: int) -> tuple[dict, str]:
    import asyncpg
    c = await asyncpg.connect(os.environ["PROD_URL"])
    r = await c.fetchrow("SELECT first_name, level, region, equipment FROM players WHERE id=$1", pid)
    await c.close()
    eq = r["equipment"]
    eq = json.loads(eq) if isinstance(eq, str) else (eq or {})
    return eq, f"{r['first_name']} (ур{r['level']}, {r['region']})", r["region"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", type=int, help="id игрока из прод-БД (нужен PROD_URL)")
    ap.add_argument("--region", default=None, help="регион для набора зверей")
    a = ap.parse_args()
    base, label, region = {}, "синтетические билды", a.region
    if a.prod:
        base, label, region = asyncio.run(from_prod(a.prod))
    beasts = combat.huntable(region) + list(combat.ELITES.values())
    report(base, beasts, label)


if __name__ == "__main__":
    main()
