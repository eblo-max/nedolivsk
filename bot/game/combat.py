"""Охота и бой: снаряга наконец работает. Модель — как в Monster Hunter:

выбираешь зверя → видишь бриф (HP + ТВОЙ расклад по статам: шанс победы,
сколько HP останется) и таблицу добычи (что выпадет точно + редкое с %),
потом идёшь в бой. Бой мгновенный по статам (items.combat_stats): урон×(крит
×2) против HP зверя, его атака против брони. Победа — добыча; поражение — раны.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, inventory, items


@dataclass(frozen=True)
class Drop:
    """Добыча. chance=100 — гарантированно; <100 — редкое. res='' — трофей
    (без инвентаря, чисто похвальба в чате/на экране)."""
    res: str
    lo: int = 1
    hi: int = 1
    chance: int = 100
    label: str = ""          # для трофея (res='')


@dataclass(frozen=True)
class Enemy:
    id: str
    emoji: str
    name: str
    hp: int
    attack: int
    armor: int
    gold: tuple                  # (мин, макс) золота — гарантированно
    drops: tuple = ()            # tuple[Drop]
    rep: int = 0
    blurb: str = ""              # чем грозит / на кого идти
    video: str = ""              # имя видео в assets/<video>.mp4 (бой и просмотр)


# Бестиарий: от мелочи (голыми руками) до атамана (только топ-снаряга).
# game=дичь(кухня), honey(медоварня), herbs(сбитень/кухня), berries(вино),
# ore(кузня/стройка), clay(стройка) — добыча кормит производство.
ENEMIES = [
    Enemy("zayac", "🐰", "Заяц", 10, 1, 0, (3, 12),
          (Drop("game", 2, 4),),
          blurb="Можно и голыми руками, если не жалко гордости.", video="zayc"),
    Enemy("lisa", "🦊", "Лиса", 18, 3, 0, (10, 22),
          (Drop("game", 2, 4), Drop("herbs", 2, 3, 22)),
          blurb="Юркая, но кусачая. Шкурка ценится."),
    Enemy("gadyuka", "🐍", "Гадюка", 24, 9, 0, (15, 30),
          (Drop("herbs", 3, 6), Drop("game", 2, 3, 12)),
          blurb="Бьёт больно и метко — броня спасает слабо. Яд идёт в зелья."),
    Enemy("olen", "🦌", "Олень", 38, 4, 0, (18, 34),
          (Drop("game", 6, 10), Drop("herbs", 3, 5, 25)),
          blurb="Мяса много, отпор слабый. Добрая дичь к столу."),
    Enemy("volk", "🐺", "Волк", 30, 6, 0, (12, 28),
          (Drop("game", 4, 7), Drop("herbs", 2, 4, 15)),
          blurb="Кусается. Без оружия лучше не лезть."),
    Enemy("vozhak", "🐺", "Вожак стаи", 72, 14, 3, (40, 75),
          (Drop("game", 8, 14), Drop("ore", 3, 5, 18),
           Drop("", chance=8, label="🦷 клык вожака на ремень")),
          rep=1, blurb="Матёрый, со стаей за спиной. Нужна снаряга."),
    Enemy("kaban", "🐗", "Кабан", 55, 10, 2, (25, 50),
          (Drop("game", 7, 12), Drop("herbs", 3, 5, 20)),
          blurb="Клыки. Нужен топор и хоть какая броня."),
    Enemy("medved", "🐻", "Медведь", 95, 17, 5, (45, 90),
          (Drop("game", 10, 16), Drop("honey", 3, 6),
           Drop("herbs", 4, 8, 25)),
          rep=1, blurb="Задерёт неподготовленного. Броня обязательна.",
          video="medved"),
    Enemy("razboy", "🗡", "Разбойник", 85, 22, 8, (90, 170),
          (Drop("ore", 4, 8), Drop("herbs", 4, 8),
           Drop("", chance=15, label="🗡 трофейный кинжал разбойника")),
          rep=2, blurb="С оружием и злой. Только для крепкого бойца."),
    Enemy("ataman", "👹", "Атаман", 160, 30, 12, (180, 340),
          (Drop("ore", 8, 14), Drop("clay", 6, 10, 40),
           Drop("", chance=12, label="👑 перстень атамана (хвастать в чате)")),
          rep=4, blurb="Гроза тракта. Идут только мастера в полном железе."),
]
ENEMY = {e.id: e for e in ENEMIES}


@dataclass
class Fight:
    win: bool
    rounds: int
    crits: int
    dealt: int
    hp_left: int
    overwhelmed: bool


def _player_offense(stats: dict) -> tuple[int, int, int]:
    dmg = balance.BASE_DAMAGE + stats.get("damage", 0)
    crit_pct = min(balance.HUNT_CRIT_CAP,
                   stats.get("crit", 0) + stats.get("luck", 0) // 2)
    return dmg, crit_pct, stats.get("armor", 0)


def resolve(stats: dict, enemy: Enemy, rng: random.Random | None = None) -> Fight:
    """Прогон боя по статам снаряги. stats — items.combat_stats(equipment)."""
    rng = rng or random
    dmg, crit_pct, parmor = _player_offense(stats)
    php = balance.BASE_HP
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
    return Fight(win, rounds, crits, dealt, max(0, php), overwhelmed)


def forecast(stats: dict, enemy: Enemy, n: int = 160,
             rng: random.Random | None = None) -> tuple[int, int]:
    """Прогноз исхода по статам: (шанс победы %, средне-остаточное HP при победе)."""
    rng = rng or random
    wins = hp_sum = 0
    for _ in range(n):
        f = resolve(stats, enemy, rng)
        if f.win:
            wins += 1
            hp_sum += f.hp_left
    return round(wins * 100 / n), (round(hp_sum / wins) if wins else 0)


def threat(win_pct: int) -> tuple[str, str]:
    """Цвет-метка угрозы по шансу победы (как threat level в hunt-играх)."""
    if win_pct >= 95:
        return "🟢", "лёгкая добыча"
    if win_pct >= 70:
        return "🟢", "уверенно"
    if win_pct >= 40:
        return "🟡", "рискованно"
    if win_pct >= 10:
        return "🟠", "опасно"
    return "🔴", "верная смерть"


def roll_loot(enemy: Enemy, luck: int, rng: random.Random | None = None) -> dict:
    """Добыча с победы: {gold, res{}, trophies[], rep}. Удача щедрит и редкое."""
    rng = rng or random
    bonus = 1.0 + min(0.3, luck / 100)
    gold = int(rng.randint(*enemy.gold) * bonus)
    res: dict[str, int] = {}
    trophies: list[str] = []
    for d in enemy.drops:
        chance = d.chance + (luck if d.chance < 100 else 0)
        if rng.randint(1, 100) > min(100, chance):
            continue
        if d.res:
            res[d.res] = res.get(d.res, 0) + max(1, int(rng.randint(d.lo, d.hi) * bonus))
        else:
            trophies.append(d.label)
    return {"gold": gold, "res": res, "trophies": trophies, "rep": enemy.rep}


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
