"""Анализ НАГРАДЫ рейд-боссов под новую систему (power-scaled HP).

Награда не зависит от HP-модели напрямую (пул золота делится на бивших + один
бонус-дроп победителю), но ВРЕМЯ боя и ШАНС убийства изменились — поэтому
пересчитываем доходность под новые тайминги. Чистая аналитика по коду (без БД):
EV дропа в золоте (ресурсы — по RESOURCE_PRICE), золото/мин, поправка на уход,
сравнение с пассивным доходом, кран золота/материалов и проблема фри-райдеров.

Запуск:  python scripts/sim_raid_reward.py
"""

from bot.game import balance, items, raid

# Представительное «честное» время убийства (идеал, тима ~6, из прод-сим), мин.
IDEAL_MIN = {"rat_king": 7.7, "bog_troll": 9.8, "dragon": 12.3}
# Реалистичный шанс убийства тимой-6 (с отвалом), из прод-сим.
REAL_KILL = {"rat_king": 0.85, "bog_troll": 0.47, "dragon": 0.11}
PRICE = {"gold": 1.0, **balance.RESOURCE_PRICE}


def _mid(lo, hi):
    return (lo + hi) / 2


def drop_breakdown(spec):
    """EV одного бонус-дропа в золоте (без снаряги) + шанс снаряги (‰→доля)."""
    total = sum(w for _, w, _ in spec.loot)
    gold_ev, gear_w = 0.0, 0
    for tag, w, payload in spec.loot:
        if tag == "gear":
            gear_w += w
            continue
        if tag == "gold":
            val = _mid(*payload)
        elif tag == "ingot":
            val = _mid(*payload) * PRICE["ingot"]
        else:  # res:<name>
            res, lo, hi = payload
            val = _mid(lo, hi) * PRICE.get(res, 0)
        gold_ev += (w / total) * val
    return gold_ev, gear_w / total


def gear_value(spec):
    """Грубая золото-оценка выпавшей снаряги = ср. вложение по ярусам (craft-цена)."""
    tw = spec.gear_tier_weights
    tot = sum(tw)
    val = 0.0
    for iid in spec.gear_pool:
        it = items.CATALOG.get(iid)
        if it is None:
            continue
        for tier, w in zip((1, 2, 3), tw):
            val += (w / tot) * sum(items.tier_cost(it, tier).values())
    return val / max(1, len(spec.gear_pool))


def main():
    print("\n" + "=" * 74)
    print("АНАЛИЗ НАГРАДЫ РЕЙД-БОССОВ (под новую power-scaled систему)")
    print("=" * 74)

    for key, spec in raid.BOSSES.items():
        gold_ev, gear_p = drop_breakdown(spec)
        gval = gear_value(spec)
        pool = spec.gold_pool
        print(f"\n{spec.emoji} {spec.name}  · пул {pool}🪙 · бонус-дроп EV ≈ {gold_ev:.0f}🪙 "
              f"+ снаряга {gear_p*100:.1f}% (≈{gval:.0f}🪙 крафт-цены)")
        print(f"  {'бивших':>7} {'золото/чел':>11} {'+бонус EV/чел':>14} "
              f"{'итого/чел':>10} {'золото/мин':>11}")
        for n in (1, 2, 3, 6, 10):
            base = pool // n
            bonus_per = (gold_ev + gear_p * gval) / n      # шанс стать победителем 1/n
            tot = base + bonus_per
            per_min = tot / IDEAL_MIN[key]
            print(f"  {n:>7} {base:>11} {bonus_per:>14.0f} {tot:>10.0f} {per_min:>11.1f}")

    # ── Доходность vs пассив и vs друг друга ─────────────────────────────────
    print("\n" + "-" * 74)
    print("ДОХОДНОСТЬ (тима 6) — золото/мин активного боя vs пассивный доход:")
    for L in (1, 3, 5, 10):
        rate = balance.stats_for_level(L)["income_rate"] / 60
        print(f"  пассив ур.{L}: {rate:.2f}🪙/мин")
    for key, spec in raid.BOSSES.items():
        gold_ev, gear_p = drop_breakdown(spec)
        per = (spec.gold_pool + gold_ev + gear_p * gear_value(spec)) / 6
        print(f"  {spec.emoji} {spec.name:<16} {per/IDEAL_MIN[key]:>5.1f}🪙/мин "
              f"(итого {per:.0f}🪙/чел за ~{IDEAL_MIN[key]:.0f} мин)")

    # ── Поправка на реальный уход (нынешняя слабая база) ─────────────────────
    print("\n" + "-" * 74)
    print("EV С УЧЁТОМ УХОДА (тима 6, реалистичная явка) — что реально капает:")
    for key, spec in raid.BOSSES.items():
        gold_ev, gear_p = drop_breakdown(spec)
        per = (spec.gold_pool + gold_ev + gear_p * gear_value(spec)) / 6
        ev = per * REAL_KILL[key]
        print(f"  {spec.emoji} {spec.name:<16} убийств {REAL_KILL[key]*100:>3.0f}% → "
              f"ожидаемо {ev:>5.0f}🪙/чел за попытку (номинал {per:.0f})")

    # ── Кран в экономику за одно убийство ────────────────────────────────────
    print("\n" + "-" * 74)
    print("КРАН ЗА 1 УБИЙСТВО (вброс в экономику):")
    for key, spec in raid.BOSSES.items():
        gold_ev, _ = drop_breakdown(spec)
        print(f"  {spec.emoji} {spec.name:<16} золото ~{spec.gold_pool + gold_ev*0.3:.0f}🪙 "
              f"(пул + золотая часть дропа) + ресурсы/снаряга. Спавн — только админом.")
    print()


if __name__ == "__main__":
    main()
