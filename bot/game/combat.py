"""Охота и бой: снаряга наконец работает.

Мгновенный бой по статам (items.combat_stats): урон×(крит ×2) против HP зверя,
его атака против твоей брони. Победа → добыча; поражение → раны (кулдаун).
Голыми руками одолеешь только мелочь; на атамана идёт только мастер в железе.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, inventory, items


@dataclass(frozen=True)
class Enemy:
    id: str
    emoji: str
    name: str
    hp: int
    attack: int
    armor: int
    gold: tuple                 # (мин, макс) золота
    loot: tuple = ()            # ((ресурс, мин, макс), ...)
    rep: int = 0                # +репутация за добычу
    rare: str = ""              # редкий трофей (флавор-строка) при удаче
    blurb: str = ""             # чем грозит / на кого идти


# От мелочи (голыми руками) до атамана (только топ-снаряга).
ENEMIES = [
    Enemy("zayac", "🐰", "Заяц", hp=10, attack=1, armor=0,
          gold=(3, 12), loot=(("game", 2, 4),),
          blurb="Можно и голыми руками, если не жалко гордости."),
    Enemy("volk", "🐺", "Волк", hp=30, attack=6, armor=0,
          gold=(12, 28), loot=(("game", 4, 7),),
          blurb="Кусается. Без оружия лучше не лезть."),
    Enemy("kaban", "🐗", "Кабан", hp=55, attack=10, armor=2,
          gold=(25, 50), loot=(("game", 7, 12),),
          blurb="Клыки. Нужен топор и хоть какая броня."),
    Enemy("medved", "🐻", "Медведь", hp=95, attack=17, armor=5,
          gold=(45, 90), loot=(("game", 10, 16), ("herbs", 3, 6)),
          rep=1, blurb="Задерёт неподготовленного. Броня обязательна."),
    Enemy("razboy", "🗡", "Разбойник", hp=85, attack=22, armor=8,
          gold=(90, 170), loot=(("ore", 4, 8), ("herbs", 4, 8)),
          rep=2, rare="🗡 трофейный кинжал разбойника",
          blurb="С оружием и злой. Только для крепкого бойца."),
    Enemy("ataman", "👹", "Атаман", hp=160, attack=30, armor=12,
          gold=(180, 340), loot=(("ore", 8, 14),),
          rep=4, rare="👑 перстень атамана (хвастать в чате)",
          blurb="Гроза тракта. Идут только мастера в полном железе."),
]
ENEMY = {e.id: e for e in ENEMIES}


@dataclass
class Fight:
    win: bool
    rounds: int
    crits: int
    dealt: int               # суммарно нанесено зверю
    hp_left: int             # сколько здоровья осталось у охотника
    overwhelmed: bool        # не уложился в раунды (зверь слишком толст)


def resolve(stats: dict, enemy: Enemy, rng: random.Random | None = None) -> Fight:
    """Прогон боя по статам снаряги. stats — items.combat_stats(equipment)."""
    rng = rng or random
    php = balance.BASE_HP
    dmg = balance.BASE_DAMAGE + stats.get("damage", 0)
    crit_pct = min(balance.HUNT_CRIT_CAP,
                   stats.get("crit", 0) + stats.get("luck", 0) // 2)
    parmor = stats.get("armor", 0)

    ehp = enemy.hp
    rounds = crits = dealt = 0
    while ehp > 0 and php > 0 and rounds < balance.HUNT_MAX_ROUNDS:
        rounds += 1
        hit = max(1, dmg - enemy.armor)
        if rng.randint(1, 100) <= crit_pct:
            hit *= 2
            crits += 1
        ehp -= hit
        dealt += hit
        if ehp <= 0:
            break
        php -= max(1, enemy.attack - parmor // balance.ARMOR_DR_DIV)

    win = ehp <= 0 and php > 0
    overwhelmed = ehp > 0 and rounds >= balance.HUNT_MAX_ROUNDS
    return Fight(win=win, rounds=rounds, crits=crits, dealt=dealt,
                 hp_left=max(0, php), overwhelmed=overwhelmed)


def roll_loot(enemy: Enemy, luck: int, rng: random.Random | None = None) -> dict:
    """Добыча с победы: {gold, res{}, rep, rare|None}. Удача чуть щедрит."""
    rng = rng or random
    bonus = 1.0 + min(0.3, luck / 100)  # удача до +30% к количеству
    gold = int(rng.randint(*enemy.gold) * bonus)
    res = {}
    for r, lo, hi in enemy.loot:
        res[r] = int(rng.randint(lo, hi) * bonus)
    rare = enemy.rare if (enemy.rare and rng.randint(1, 100) <= 10 + luck) else None
    return {"gold": gold, "res": res, "rep": enemy.rep, "rare": rare}


# ── Оркестрация охоты (кулдаун, добыча, раны) ──────────────────────────
@dataclass
class HuntResult:
    ok: bool
    reason: str = ""           # unknown | cooldown
    minutes_left: int = 0
    enemy: Enemy | None = None
    fight: Fight | None = None
    loot: dict | None = None
    gold_lost: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hunt_ready(player, now: datetime | None = None) -> tuple[bool, int]:
    """(готов?, минут до готовности). Кулдаун/ранение — в player.hunt_ready_at."""
    now = now or _now()
    t = player.hunt_ready_at
    if t is None:
        return True, 0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if t <= now:
        return True, 0
    return False, int((t - now).total_seconds() // 60) + 1


def hunt(player, enemy_id: str, rng: random.Random | None = None) -> HuntResult:
    """Сходить на охоту: проверка кулдауна, бой, добыча/раны. Мутирует игрока."""
    rng = rng or random
    enemy = ENEMY.get(enemy_id)
    if enemy is None:
        return HuntResult(ok=False, reason="unknown")
    ready, mins = hunt_ready(player)
    if not ready:
        return HuntResult(ok=False, reason="cooldown", minutes_left=mins)

    stats = items.combat_stats(getattr(player, "equipment", None))
    fight = resolve(stats, enemy, rng)
    now = _now()
    if fight.win:
        loot = roll_loot(enemy, stats.get("luck", 0), rng)
        player.gold += loot["gold"]
        for r, q in loot["res"].items():
            inventory.add(player, r, q)
        if loot["rep"]:
            player.reputation = (player.reputation or 0) + loot["rep"]
            if player.tavern is not None:
                player.tavern.reputation = (player.tavern.reputation or 0) + loot["rep"]
        player.hunt_ready_at = now + timedelta(minutes=balance.HUNT_COOLDOWN_MINUTES)
        return HuntResult(ok=True, enemy=enemy, fight=fight, loot=loot)

    lost = player.gold // balance.HUNT_LOSS_GOLD_DIV  # щепотка золота при поражении
    player.gold -= lost
    player.hunt_ready_at = now + timedelta(hours=balance.HUNT_WOUND_HOURS)
    return HuntResult(ok=True, enemy=enemy, fight=fight, gold_lost=lost)
