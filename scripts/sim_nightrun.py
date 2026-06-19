"""Баланс «Ночной ходки»: кривая EV / бюста и оптимальная остановка по снаряге.

Гоняет РЕАЛЬНЫЙ движок (bot.game.nightrun) стратегией «банк на этапе N»: на
развилке берём лучший по шансу тип (отдыхаем лишь при низком HP), считаем
забанканную ценность (0 при бюсте). По каждому уровню снаряги — таблица
этап→EV/бюст и найденный оптимум. Цель: пик EV в середине, глубже у сильных,
бюст при разумной игре ~20–30%.

Запуск:  python scripts/sim_nightrun.py
"""

import random
import statistics
from types import SimpleNamespace

from bot.game import combat, nightrun

# Уровень снаряги -> (броня, удача). Грубо: сток / частичное / полное.
TIERS = {"сток (a6 l0)": (6, 0), "частичн (a20 l6)": (20, 6), "полное (a45 l12)": (45, 12)}
TRIALS = 4000


def _patch(armor, luck):
    combat.player_stats = lambda p=None: {
        "armor": armor, "luck": luck, "damage": 0, "crit": 0, "dmg_taken_mult": 1.0}


def run_once(stop_leg: int, rng: random.Random):
    player = SimpleNamespace(id=1, gold=0, inventory={})
    run = nightrun.start(player, "green_valleys", None, seed=rng.randint(1, 10**9))
    while True:
        leg = run["leg"]
        a, b = nightrun.fork(run)
        cand = [k for k in (a, b) if k != "rest"] or [a, b]
        kind = max(cand, key=lambda k: nightrun.success_p(run, player, k))
        if "rest" in (a, b) and run["hp"] < 15:          # отдышаться, если плохо
            kind = "rest"
        out = nightrun.attempt(run, player, kind, rng)
        if run.get("state") == "meet":                   # встреча — берём первую опцию
            nightrun.meet_resolve(run, player, nightrun.meet_options(run)[0][0], rng)
            out = {"busted": False}
        if run.get("state") == "quiz":                   # загадка — угадываем с p≈0.6
            nightrun.quiz_resolve(run, player, rng.random() < 0.6, rng)
            out = {"busted": False}
        if out["busted"]:
            return 0.0, leg, True
        if leg >= stop_leg or not nightrun.can_push(run):
            val = nightrun.satchel_value(run["satchel"])
            nightrun.bank(run, player)
            return float(val), leg, False
        nightrun.push(run)


def main():
    rng = random.Random(20260619)
    from bot.game import balance
    print(f"\n=== НОЧНАЯ ХОДКА · {TRIALS} забегов/ячейка · этапов {balance.NIGHTRUN_LEGS} "
          f"· P0 {balance.NIGHTRUN_P0} decay {balance.NIGHTRUN_P_DECAY} ===\n")
    for tname, (armor, luck) in TIERS.items():
        _patch(armor, luck)
        print(f"{tname}:")
        print(f"  {'стоп@этап':>10} {'EV банк':>9} {'бюст%':>7} {'медиана(успех)':>15}")
        best = (None, -1)
        for stop in range(1, balance.NIGHTRUN_LEGS + 1):
            res = [run_once(stop, rng) for _ in range(TRIALS)]
            banked = [v for v, _, busted in res if not busted]
            ev = statistics.mean(v for v, _, _ in res)        # с учётом нулей за бюст
            bust = 100 * sum(1 for *_, busted in res if busted) / TRIALS
            med = statistics.median(banked) if banked else 0
            star = " ←" if ev > best[1] else ""
            if ev > best[1]:
                best = (stop, ev)
            print(f"  {stop:>10} {ev:>9.0f} {bust:>6.0f}% {med:>15.0f}{star}")
        print(f"  → оптимальная остановка: этап {best[0]} (EV {best[1]:.0f}🪙-экв)\n")


if __name__ == "__main__":
    main()
