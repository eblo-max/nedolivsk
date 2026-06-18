"""ПРОД-симуляция рейд-боссов на РЕАЛЬНЫХ аккаунтах (read-only, без записи в БД).

Тянет живых игроков из боевой БД, считает их урон по боссу НАСТОЯЩИМ движком
(raid.resolve_hit → combat.player_stats по реальной снаряге и уровню — никаких
заглушек), и гоняет бой минута-в-минуту до победы/ухода. Сценарии:

  1) СОЛО      — мой аккаунт как есть;
  2) ТИМА      — топ реальных активных аккаунтов вместе;
  3) ПОЛНОЕ    — мой уровень, ВСЕ слоты лучшим снаряжением ★★★;
  4) ЧАСТИЧНОЕ — мой уровень, неполный набор (оружие+грудь+пояс ★★).

Бьём без кулдауна (как в проде): тап-модель TAP_PROB/STEP_SEC, явка не отваливается
(меряем чистое «за сколько умрёт, если реально драться»). По каждому боссу —
медиана времени убийства и % убийств за окно боя.

Запуск (env из прода, но команда локальная — код локальный, БД прод):
    railway run --service worker python scripts/sim_raid_prod.py
БД не меняется: только SELECT.
"""

import argparse
import asyncio
import random
import statistics
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from bot.db.base import session_factory
from bot.db.models import Player
from bot.game import items, raid

UTC = timezone.utc
ADMIN_ID = 5731136459          # «мой аккаунт»
TAP_PROB, STEP_SEC = 0.70, 2
WINDOW_MIN = raid.FIGHT_HOURS * 60
TRIALS = 120


def raid_hit_ev(player) -> float:
    """Ожидаемый сырой урон игрока по боссу за удар = «сила» (движковый расчёт)."""
    return raid.player_power(player)


def boss_hp(boss_key: str, fighters: list) -> int:
    """HP босса под суммарную СИЛУ конкретной пачки (та же модель, что в проде)."""
    return raid.hp_for_power(boss_key, sum(raid.player_power(f) for f in fighters))


def best_full_equipment() -> dict:
    """Лучшее КУЕМОЕ снаряжение по слоту (макс. урон, потом крит), всё ★★★."""
    by_slot: dict[str, object] = {}
    for it in items.CATALOG.values():
        if not getattr(it, "craftable", True):
            continue
        key = (it.damage, it.crit, it.armor, it.luck)
        cur = by_slot.get(it.slot)
        if cur is None or key > (cur.damage, cur.crit, cur.armor, cur.luck):
            by_slot[it.slot] = it
    return {slot: items.make_entry(it.id, items.TIER_MAX) for slot, it in by_slot.items()}


def partial_equipment() -> dict:
    """Неполный набор: лучшее оружие/грудь/пояс на ★★ (середина прогрессии)."""
    full = best_full_equipment()
    eq = {}
    for slot in ("weapon", "chest", "belt"):
        if slot in full:
            iid, _ = items.parse_entry(full[slot])
            eq[slot] = items.make_entry(iid, 2)
    return eq


def variant(base_player, equipment: dict, name: str):
    """Клон-болванка для боя: реальный уровень, заданная снаряга, без бафов."""
    return SimpleNamespace(id=base_player.id, first_name=name, level=base_player.level,
                           equipment=equipment, inventory={},
                           buff_kind=None, buff_until=None, hp=35, hp_at=None)


def simulate(boss_key: str, fighters: list, rng: random.Random) -> dict:
    n = len(fighters)
    hp0 = boss_hp(boss_key, fighters)
    boss = SimpleNamespace(id=1, boss_key=boss_key, status="active", max_hp=hp0, hp=hp0,
                           contributions={}, messages={}, state={})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    boss.ends_at = start + timedelta(minutes=WINDOW_MIN)
    last_min, t = -1, 0
    while t <= WINDOW_MIN * 60:
        now = start + timedelta(seconds=t)
        if t // 60 != last_min:
            raid.cast_tick(boss, now); last_min = t // 60
        if raid.stun_left(boss, now) <= 0:
            for f in fighters:
                if rng.random() > TAP_PROB:
                    continue
                raid.resolve_hit(boss, f, now, rng)
                raid.maybe_second_wind(boss, now)
                if boss.hp <= 0:
                    return {"killed": True, "minutes": t / 60}
        t += STEP_SEC
    return {"killed": False, "minutes": WINDOW_MIN, "hp_left_pct": 100 * boss.hp / boss.max_hp}


def run_cell(boss_key: str, fighters: list) -> str:
    rng = random.Random(20260618)
    res = [simulate(boss_key, fighters, rng) for _ in range(TRIALS)]
    killed = [r for r in res if r["killed"]]
    kp = 100 * len(killed) / TRIALS
    med = statistics.median([r["minutes"] for r in killed]) if killed else float("nan")
    hp_left = statistics.mean([r["hp_left_pct"] for r in res if not r["killed"]]) \
        if kp < 100 else 0
    tail = f", уход с {hp_left:.0f}% HP" if kp < 100 else ""
    return (f"{kp:>3.0f}% убийств, медиана {med:>4.1f} мин"
            + (tail if kp < 100 else "")) if killed or kp == 0 else f"уход (с {hp_left:.0f}% HP)"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", type=int, default=ADMIN_ID)
    ap.add_argument("--team", type=int, default=6, help="размер тимы из топ-активных")
    args = ap.parse_args()

    async with session_factory() as s:
        me = await s.get(Player, args.admin)
        rows = (await s.execute(
            select(Player).where(Player.is_active.is_(True))
            .order_by(Player.level.desc()))).scalars().all()

    if me is None:
        print(f"⚠ Аккаунт {args.admin} не найден; беру самого прокачанного как «мой».")
        me = rows[0]
    team = rows[:args.team]

    def pdesc(p):
        return (f"{(p.first_name or '?')[:14]:<14} ур.{p.level:<3} "
                f"урон/удар≈{raid_hit_ev(p):>5.0f}  слотов:{len(p.equipment or {})}")

    print("\n" + "=" * 72)
    print("ПРОД-СИМУЛЯЦИЯ РЕЙД-БОССОВ НА РЕАЛЬНЫХ АККАУНТАХ (read-only)")
    print(f"всего активных в БД: {len(rows)} · окно боя {WINDOW_MIN} мин · "
          f"без кулдауна · {TRIALS} прогонов/ячейку")
    print("=" * 72)

    full = variant(me, best_full_equipment(), "Я · ПОЛНОЕ ★★★")
    part = variant(me, partial_equipment(), "Я · ЧАСТИЧНОЕ ★★")
    scenarios = [
        ("1) СОЛО — мой аккаунт как есть", [me]),
        (f"2) ТИМА — топ-{len(team)} реальных аккаунтов", team),
        ("3) ПОЛНОЕ снаряжение (мой ур., все слоты ★★★)", [full]),
        ("4) ЧАСТИЧНОЕ снаряжение (мой ур., оружие+грудь+пояс ★★)", [part]),
    ]

    print(f"\n— мой аккаунт: {pdesc(me)}")
    print(f"— полное ★★★:  урон/удар≈{raid_hit_ev(full):>5.0f}  ({len(full.equipment)} слотов)")
    print(f"— частичное:   урон/удар≈{raid_hit_ev(part):>5.0f}  ({len(part.equipment)} слота)")
    print(f"\n— состав тимы (топ-{len(team)} по уровню):")
    for p in team:
        print(f"    {pdesc(p)}")

    for title, fighters in scenarios:
        print(f"\n{title}  (бойцов: {len(fighters)})")
        for key in raid.BOSSES:
            spec = raid.BOSSES[key]
            hp = boss_hp(key, fighters)
            print(f"    {spec.emoji} {spec.name:<16} HP {hp:>6} · {run_cell(key, fighters)}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
