"""Охота и бой: снаряга наконец работает. Модель — как в Monster Hunter:

выбираешь зверя → видишь бриф (HP + ТВОЙ расклад по статам: шанс победы,
сколько HP останется) и таблицу добычи (что выпадет точно + редкое с %),
потом идёшь в бой. Бой мгновенный по статам (items.combat_stats): урон×(крит
×2) против HP зверя, его атака против брони. Победа — добыча; поражение — раны.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, buff, inventory, items


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
    Enemy("zayac", "🐰", "Заяц", 8, 2, 0, (3, 12),
          (Drop("game", 2, 4),),
          blurb="Можно и голыми руками, если не жалко гордости.", video="zayc"),
    Enemy("lisa", "🦊", "Лиса", 18, 5, 0, (10, 22),
          (Drop("game", 2, 4), Drop("herbs", 2, 3, 22)),
          blurb="Юркая, но кусачая. Шкурка ценится.", video="lisa"),
    Enemy("gadyuka", "🐍", "Гадюка", 30, 10, 0, (15, 30),
          (Drop("herbs", 3, 6), Drop("game", 2, 3, 12)),
          blurb="Бьёт больно и метко — броня тут не спасёт. Яд идёт в зелья.",
          video="zmeya"),
    Enemy("olen", "🦌", "Олень", 52, 7, 0, (18, 34),
          (Drop("game", 6, 10), Drop("herbs", 3, 5, 25)),
          blurb="Мяса много, отпор слабый. Добрая дичь к столу.", video="olen"),
    Enemy("volk", "🐺", "Волк", 48, 11, 0, (16, 32),
          (Drop("game", 4, 7), Drop("herbs", 2, 4, 15)),
          blurb="Кусается всерьёз. Без оружия лучше не лезть.", video="volk"),
    Enemy("kaban", "🐗", "Кабан", 60, 13, 2, (25, 50),
          (Drop("game", 7, 12), Drop("herbs", 3, 5, 20)),
          blurb="Клыки. Нужен топор и хоть какая броня.", video="kaban"),
    Enemy("vozhak", "🐺", "Вожак стаи", 88, 18, 3, (45, 85),
          (Drop("game", 8, 14), Drop("ore", 3, 5, 18),
           Drop("", chance=8, label="🦷 клык вожака на ремень")),
          rep=1, blurb="Матёрый, со стаей за спиной. Нужна снаряга."),
    Enemy("medved", "🐻", "Медведь", 104, 21, 5, (45, 95),
          (Drop("game", 10, 16), Drop("honey", 3, 6),
           Drop("herbs", 4, 8, 25)),
          rep=1, blurb="Задерёт неподготовленного. Броня обязательна.",
          video="medved"),
    Enemy("razboy", "🗡", "Разбойник", 118, 28, 8, (90, 170),
          (Drop("ore", 4, 8), Drop("herbs", 4, 8),
           Drop("", chance=15, label="🗡 трофейный кинжал разбойника")),
          rep=2, blurb="С оружием и злой. Только для крепкого бойца."),
    Enemy("ataman", "👹", "Атаман", 210, 42, 12, (190, 360),
          (Drop("ore", 8, 14), Drop("clay", 6, 10, 40),
           Drop("", chance=12, label="👑 перстень атамана (хвастать в чате)")),
          rep=4, blurb="Гроза тракта. Идут только мастера в полном железе.",
          video="ataman"),
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
    log: list = None             # [{pd, crit, ed, php, ehp}] — для анимации боя


def player_stats(player) -> dict:
    """Боевые статы игрока со снаряги ПЛЮС временные бафы («опохмел»):
    удача (крит/добыча) и множитель урона по игроку («Толстая шкура»).
    Использовать и для боя, и для прогноза — чтобы бриф не врал."""
    stats = dict(items.combat_stats(getattr(player, "equipment", None)))
    stats["luck"] = stats.get("luck", 0) + buff.luck_bonus(player)
    stats["dmg_taken_mult"] = buff.tough_mult(player)
    return stats


def _player_offense(stats: dict) -> tuple[int, int, int]:
    dmg = balance.BASE_DAMAGE + stats.get("damage", 0)
    crit_pct = min(balance.HUNT_CRIT_CAP,
                   stats.get("crit", 0) + stats.get("luck", 0) // 2)
    return dmg, crit_pct, stats.get("armor", 0)


def resolve(stats: dict, enemy: Enemy, start_hp: int | None = None,
            rng: random.Random | None = None) -> Fight:
    """Прогон боя по статам снаряги от заданного HP (по умолч. полный BASE_HP)."""
    rng = rng or random
    dmg, crit_pct, parmor = _player_offense(stats)
    php = balance.BASE_HP if start_hp is None else start_hp
    ehp = enemy.hp
    v = balance.HUNT_DMG_VARIANCE
    mit = balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + parmor)  # убывающая броня
    tmult = stats.get("dmg_taken_mult", 1.0)  # баф «Толстая шкура» (<1 — крепче)
    rounds = crits = dealt = 0
    log = []
    while ehp > 0 and php > 0 and rounds < balance.HUNT_MAX_ROUNDS:
        rounds += 1
        hit = max(1, round(max(1, dmg - enemy.armor) * rng.uniform(1 - v, 1 + v)))
        crit = rng.randint(1, 100) <= crit_pct
        if crit:
            hit *= 2
            crits += 1
        ehp -= hit
        dealt += hit
        ed = 0
        if ehp > 0:
            ed = max(1, round(enemy.attack * mit * tmult * rng.uniform(1 - v, 1 + v)))
            php -= ed
        log.append({"pd": hit, "crit": crit, "ed": ed,
                    "php": max(0, php), "ehp": max(0, ehp)})
    win = ehp <= 0 and php > 0
    overwhelmed = ehp > 0 and rounds >= balance.HUNT_MAX_ROUNDS
    return Fight(win, rounds, crits, dealt, max(0, php), overwhelmed, log)


def forecast(stats: dict, enemy: Enemy, start_hp: int | None = None,
             n: int = 160, rng: random.Random | None = None) -> tuple[int, int]:
    """Прогноз исхода от текущего HP: (шанс победы %, средне-остаточное HP)."""
    rng = rng or random
    wins = hp_sum = 0
    for _ in range(n):
        f = resolve(stats, enemy, start_hp, rng)
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
    reason: str = ""           # unknown | lowhp
    minutes_left: int = 0
    enemy: Enemy | None = None
    fight: Fight | None = None
    loot: dict | None = None
    gold_lost: int = 0
    hp_now: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def max_hp(player=None) -> int:
    return balance.BASE_HP


def _regen_hours(player) -> float:
    """Часы до полного восстановления HP с учётом бафа «Заживление» (×0.5)."""
    return balance.HP_REGEN_FULL_HOURS * buff.regen_mult(player)


def current_hp(player, now: datetime | None = None) -> int:
    """Текущее здоровье с регенерацией от hp_at к максимуму."""
    cur = player.hp if player.hp is not None else balance.BASE_HP
    if cur >= balance.BASE_HP or player.hp_at is None:
        return min(balance.BASE_HP, cur)
    now = now or _now()
    t = player.hp_at
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    elapsed_h = max(0.0, (now - t).total_seconds() / 3600)
    regen = elapsed_h * balance.BASE_HP / _regen_hours(player)
    return int(min(balance.BASE_HP, cur + regen))


def _min_hp() -> int:
    return max(1, int(balance.BASE_HP * balance.HUNT_MIN_HP_PCT))


def regen_full_minutes(player, now: datetime | None = None) -> int:
    """Минут до полного восстановления HP (0 — уже полное)."""
    chp = current_hp(player, now)
    if chp >= balance.BASE_HP:
        return 0
    rate_per_min = (balance.BASE_HP / _regen_hours(player)) / 60
    return int((balance.BASE_HP - chp) / rate_per_min) + 1


def _mark_recovery(player, now: datetime) -> None:
    """Если ушёл ниже боевого порога — записать время восстановления (для пинга),
    иначе сбросить. Колонка hunt_ready_at используется только для уведомления."""
    need = _min_hp()
    if player.hp < need:
        rate = balance.BASE_HP / _regen_hours(player)
        player.hunt_ready_at = now + timedelta(hours=(need - player.hp) / rate)
    else:
        player.hunt_ready_at = None


def hunt_ready(player, now: datetime | None = None) -> tuple[bool, int]:
    """(в строю?, минут до восстановления до порога). Гейт — по HP, не по таймеру."""
    chp = current_hp(player, now)
    need = _min_hp()
    if chp >= need:
        return True, 0
    rate_per_min = (balance.BASE_HP / _regen_hours(player)) / 60
    return False, int((need - chp) / rate_per_min) + 1


def can_heal(player, now: datetime | None = None) -> bool:
    """Есть ли чем подлечиться (товар в погребе) и не полон ли уже."""
    if current_hp(player, now) >= balance.BASE_HP:
        return False
    prods = (player.tavern.products if player.tavern else None) or {}
    return any(prods.get(k, 0) > 0 for k in balance.HEAL_VALUES)


def heal(player, key: str, now: datetime | None = None) -> dict | None:
    """Съесть/выпить 1 порцию из погреба → восстановить HP. None — нельзя."""
    if key not in balance.HEAL_VALUES or player.tavern is None:
        return None
    now = now or _now()
    prods = dict(player.tavern.products or {})
    if prods.get(key, 0) <= 0:
        return None
    chp = current_hp(player, now)
    if chp >= balance.BASE_HP:
        return None
    prods[key] -= 1
    player.tavern.products = prods
    new = min(balance.BASE_HP, chp + balance.HEAL_VALUES[key])
    player.hp = new
    player.hp_at = now
    _mark_recovery(player, now)
    return {"key": key, "healed": new - chp, "hp": new}


def hunt(player, enemy_id: str, rng: random.Random | None = None) -> HuntResult:
    """Сходить на охоту: гейт по HP, бой от текущего HP, добыча/утомление/раны."""
    rng = rng or random
    enemy = ENEMY.get(enemy_id)
    if enemy is None:
        return HuntResult(ok=False, reason="unknown")
    now = _now()
    chp = current_hp(player, now)
    ready, mins = hunt_ready(player, now)
    if not ready:
        return HuntResult(ok=False, reason="lowhp", minutes_left=mins)

    stats = player_stats(player)  # снаряга + бафы (удача, толстая шкура)
    fight = resolve(stats, enemy, chp, rng)
    player.hp_at = now
    if fight.win:
        loot = roll_loot(enemy, stats.get("luck", 0), rng)
        loot["gold"] = int(loot["gold"] * buff.hunt_gold_mult(player))  # «Звериный нюх»
        player.gold += loot["gold"]
        for r, q in loot["res"].items():
            inventory.add(player, r, q)
        if loot["rep"]:
            player.reputation = (player.reputation or 0) + loot["rep"]
            if player.tavern is not None:
                player.tavern.reputation = (player.tavern.reputation or 0) + loot["rep"]
        # утомление: бой стоит минимум HUNT_EXERTION, а тяжёлый — по факту урона
        player.hp = max(1, min(fight.hp_left, chp - balance.HUNT_EXERTION))
        _mark_recovery(player, now)
        return HuntResult(ok=True, enemy=enemy, fight=fight, loot=loot,
                          hp_now=player.hp)

    lost = player.gold // balance.HUNT_LOSS_GOLD_DIV  # щепотка золота при поражении
    player.gold -= lost
    player.hp = balance.HP_LOSS_FLOOR
    _mark_recovery(player, now)
    return HuntResult(ok=True, enemy=enemy, fight=fight, gold_lost=lost,
                      hp_now=player.hp)
