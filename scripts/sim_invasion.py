"""Тюнинг боя «Орда орков»: прогон композиций → винрейт/раунды/исход.

Проверяем дизайн-инварианты:
  - сбалансированная композиция (микс ролей) ПОБЕЖДАЕТ;
  - всё-стрелки (нет танков) — ПРОВАЛ (армию выкашивают);
  - всё-танки (нет урона) — ПРОВАЛ (не успевают продавить, орда уходит);
  - слабая/малая явка — ПРОВАЛ; сильная малая явка — победа.
Запуск: python scripts/sim_invasion.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.game import invasion as inv

# Архетипы снаряги (gear stats) + типичная мощь таверны.
GEAR = {
    "tank":   {"damage": 4,  "crit": 5,  "armor": 13, "luck": 4},
    "archer": {"damage": 17, "crit": 28, "armor": 2,  "luck": 4},
    "scout":  {"damage": 6,  "crit": 8,  "armor": 3,  "luck": 15},
    "ratnik": {"damage": 8,  "crit": 9,  "armor": 6,  "luck": 6},
    "noob":   {"damage": 1,  "crit": 2,  "armor": 1,  "luck": 2},
}


def unit(kind, might, pid):
    p = inv.battle_profile(GEAR[kind], might)
    p["pid"] = pid
    return p


def town(comp, might=30):
    """comp: {kind: count}."""
    out, pid = [], 1
    for kind, cnt in comp.items():
        for _ in range(cnt):
            out.append(unit(kind, might, pid)); pid += 1
    return out


def run(name, parts, seed=42):
    r = inv.simulate(parts, seed)
    roles = {}
    for p in parts:
        roles[p["role"]] = roles.get(p["role"], 0) + 1
    rolestr = " ".join(f"{inv.ROLES[k][0]}{v}" for k, v in roles.items())
    verdict = "✅ ПОБЕДА" if r["won"] else "💀 провал"
    print(f"{name:<34} N={r['n']:<3} {rolestr:<22} → {verdict}  "
          f"раунды={r['rounds']:<3} HP орды={r['orc_hp_left']}/{r['orc_hp_max']}")
    return r


print("=== Композиции (might≈30) ===")
run("Баланс (2тнк/4стр/2рзв/2рат)", town({"tank":2,"archer":4,"scout":2,"ratnik":2}))
run("Всё стрелки (8)",              town({"archer":8}))
run("Всё танки (8)",                town({"tank":8}))
run("Танки+стрелки (3/5)",          town({"tank":3,"archer":5}))
run("Ратники-середняки (8)",        town({"ratnik":8}))

print("\n=== Явка (баланс 25% танк / 50% стрелки / 25% разведка) ===")
def bal(n, might=30):
    out, pid = [], 1
    for i in range(n):
        kind = "tank" if i % 4 == 0 else ("scout" if i % 4 == 3 else "archer")
        out.append(unit(kind, might, pid)); pid += 1
    return out
for n in (3, 5, 8, 12, 20, 40):
    run(f"Явка {n} (баланс)", bal(n))

print("\n=== Слабый город (might 12, плохая снаряга) ===")
run("12 нубов",                    town({"noob":12}, might=12))
run("Слабый баланс 8 (might12)",   bal(8, might=12))

print("\n=== Сильная малая явка ===")
run("4 топ-стрелка + 2 танка (might50)", town({"tank":2,"archer":4}, might=50))
