"""Симулятор рейд-боссов на РЕАЛЬНОМ движке (bot.game.raid).

Гоняет бой минута-в-минуту весь час окна: ход босса (cast_tick — фазы/щит/
проклятье/призыв/рык/реген), личные кулдауны и оглушение, второе дыхание,
миньоны. Урон игрока берём из распределения по «ступеням прокачки» (новичок →
кит) — это единственная синтетика; ВСЯ механика босса и балансовые константы
(HP, броня, кулдаун, спеллбук, тайминги) — из живого кода через resolve_hit.

Цель калибровки: «эпик-марафон на час, может уйти по таймеру».
  • нормальная явка (5–6)  → побеждается за ~30–50 мин, уход <15%;
  • малая явка (2)         → тяжко, заметный % ухода (но сильный дуэт может);
  • большая толпа (10+)    → быстрее (~15–25 мин), но не тривиально (<10 мин — плохо).

Запуск:  python scripts/sim_raid.py
"""

import random
import statistics
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot.game import raid

UTC = timezone.utc

# Ступени прокачки: (сырой_базовый_урон, шанс_крита_%). Базовый ≈ BASE_DAMAGE +
# урон_снаряги + уровень×2 (см. raid.player_damage); крит ×2, разброс ±20%.
TIERS = {
    "newbie": (21, 7),    # ур.5, слабое оружие
    "mid":    (55, 10),   # ур.12, оружие ★★
    "strong": (109, 17),  # ур.20, тесак ★★★
    "whale":  (137, 25),  # ур.25, топ-снаряга + крит-пояс
}
# Доля ступеней в населении чата (грубая оценка активного ростера).
POP = (("newbie", 0.35), ("mid", 0.35), ("strong", 0.22), ("whale", 0.08))

ENGAGE = 0.75           # вероятность, что боец реально жмёт «Бить», когда КД сошёл
STEP_SEC = 15           # шаг симуляции
WINDOW_MIN = raid.FIGHT_HOURS * 60


def _mk_fighter(pid: int, rng: random.Random):
    tier = rng.choices([t for t, _ in POP], weights=[w for _, w in POP])[0]
    base, crit = TIERS[tier]
    # presence: до какой минуты боец вообще в деле (кто-то отваливается раньше).
    leave_at = rng.uniform(20, WINDOW_MIN)
    return SimpleNamespace(id=pid, first_name=f"p{pid}", base=base, crit=crit,
                           leave_at=leave_at, last_hit=None)


def simulate(boss_key: str, fighters: int, rng: random.Random) -> dict:
    n = max(1, fighters)
    boss = SimpleNamespace(
        id=1, boss_key=boss_key, status="active",
        max_hp=raid.hp_for(boss_key, n), hp=raid.hp_for(boss_key, n),
        contributions={}, messages={}, state={},
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    boss.ends_at = start + timedelta(minutes=WINDOW_MIN)
    roster = [_mk_fighter(i, rng) for i in range(n)]
    cd = raid.BOSSES[boss_key].cooldown_min * 60

    # Патчим источник сырого урона — остальное (проклятье/щит/броня/миньоны) реально.
    cur = {"f": None}

    def _pd(_player, _rng=None):
        f = cur["f"]
        crit = rng.randint(1, 100) <= f.crit
        dmg = f.base * (2 if crit else 1) * rng.uniform(0.8, 1.2)
        return max(1, int(dmg)), crit

    raid.player_damage = _pd

    last_cast_min = -1
    t = 0
    while t <= WINDOW_MIN * 60:
        now = start + timedelta(seconds=t)
        cur_min = t // 60
        if cur_min != last_cast_min:        # ход босса — раз в минуту (как нотифаер)
            raid.cast_tick(boss, now)
            last_cast_min = cur_min
        for f in roster:
            if now > start + timedelta(minutes=f.leave_at):
                continue
            if raid.cooldown_left(boss, f.id, now) > 0:
                continue
            if rng.random() > ENGAGE:
                # «не сейчас» — но фиксируем как попытку, чтобы не лупил каждый шаг
                f.last_hit = now - timedelta(seconds=cd - STEP_SEC)
                # запишем «last» в contributions, чтобы cooldown_left увидел паузу
                rec = dict((boss.contributions or {}).get(str(f.id))
                           or {"dmg": 0, "hits": 0, "name": f.first_name})
                rec["last"] = (now - timedelta(seconds=cd - STEP_SEC)).isoformat()
                c = dict(boss.contributions); c[str(f.id)] = rec; boss.contributions = c
                continue
            cur["f"] = f
            raid.resolve_hit(boss, f, now)
            raid.maybe_second_wind(boss, now)
            if boss.hp <= 0:
                hitters = sum(1 for r in boss.contributions.values() if r.get("dmg", 0) > 0)
                hits = sum(r.get("hits", 0) for r in boss.contributions.values())
                return {"killed": True, "minutes": t / 60, "hitters": hitters,
                        "hits_per_fighter": hits / n,
                        "second_wind": bool((boss.state or {}).get("second_wind"))}
        t += STEP_SEC
    hits = sum(r.get("hits", 0) for r in boss.contributions.values())
    return {"killed": False, "minutes": WINDOW_MIN, "hits_per_fighter": hits / n,
            "hp_left_pct": 100 * boss.hp / boss.max_hp,
            "second_wind": bool((boss.state or {}).get("second_wind"))}


def run(trials: int = 400):
    rng = random.Random(20260618)
    turnouts = (2, 4, 6, 8, 12)
    print(f"\n=== РЕЙД-СИМУЛЯТОР · {trials} боёв/ячейка · окно {WINDOW_MIN} мин · "
          f"engage {ENGAGE:.0%} ===\n")
    for key in raid.BOSSES:
        spec = raid.BOSSES[key]
        print(f"{spec.emoji} {spec.name}  (HP/боец {spec.hp_per_fighter}, пол {spec.min_hp}, "
              f"КД {spec.cooldown_min} мин, броня {spec.armor}, спеллы {spec.spellbook})")
        print(f"  {'явка':>5} {'HP':>7} {'kill%':>6} {'медиана,мин':>12} "
              f"{'уход%':>6} {'2-е дых%':>8} {'ост.HP%(уход)':>13}")
        for nft in turnouts:
            res = [simulate(key, nft, rng) for _ in range(trials)]
            killed = [r for r in res if r["killed"]]
            escaped = [r for r in res if not r["killed"]]
            kill_pct = 100 * len(killed) / trials
            med = statistics.median([r["minutes"] for r in killed]) if killed else float("nan")
            sw = 100 * sum(r["second_wind"] for r in res) / trials
            esc_hp = statistics.mean([r["hp_left_pct"] for r in escaped]) if escaped else 0
            print(f"  {nft:>5} {raid.hp_for(key, nft):>7} {kill_pct:>5.0f}% "
                  f"{med:>12.1f} {100 - kill_pct:>5.0f}% {sw:>7.0f}% {esc_hp:>12.0f}%")
        print()


if __name__ == "__main__":
    run()
