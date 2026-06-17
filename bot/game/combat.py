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
    Enemy("lisa", "🦊", "Лиса", 18, 4, 0, (10, 22),
          (Drop("game", 2, 4), Drop("herbs", 2, 3, 22)),
          blurb="Юркая, но кусачая. Шкурка ценится.", video="lisa"),
    Enemy("gadyuka", "🐍", "Гадюка", 28, 9, 0, (15, 30),
          (Drop("herbs", 3, 6), Drop("game", 2, 3, 12)),
          blurb="Бьёт больно и метко — броня тут не спасёт. Яд идёт в зелья.",
          video="zmeya"),
    Enemy("olen", "🦌", "Олень", 54, 7, 1, (18, 34),
          (Drop("game", 6, 10), Drop("herbs", 3, 5, 25),
           Drop("hide", 1, 2, 35), Drop("sinew", 1, 2, 20)),
          blurb="Мяса много, отпор слабый. Шкура и жилы идут в дело.", video="olen"),
    Enemy("volk", "🐺", "Волк", 46, 8, 2, (16, 32),
          (Drop("game", 4, 7), Drop("herbs", 2, 4, 15),
           Drop("fang", 1, 2, 30), Drop("sinew", 1, 2, 25)),
          blurb="Кусается всерьёз. Клык — на доброе оружие.", video="volk"),
    Enemy("kaban", "🐗", "Кабан", 66, 9, 6, (25, 50),
          (Drop("game", 7, 12), Drop("herbs", 3, 5, 20),
           Drop("hide", 1, 2, 30), Drop("fang", 1, 1, 20)),
          blurb="Клыки и толстая шкура. Крит пробивает, топор рубит.", video="kaban"),
    Enemy("vozhak", "🐺", "Вожак стаи", 88, 12, 4, (45, 85),
          (Drop("game", 8, 14), Drop("ore", 3, 5, 18),
           Drop("fang", 1, 2, 60), Drop("hide", 1, 2, 25)),
          rep=1, blurb="Матёрый, со стаей за спиной. Клыки знатные."),
    Enemy("medved", "🐻", "Медведь", 90, 12, 8, (45, 95),
          (Drop("game", 10, 16), Drop("honey", 3, 6),
           Drop("hide", 2, 3, 60), Drop("fang", 1, 1, 20)),
          rep=1, blurb="Задерёт неподготовленного. Шкура — лучшая на доху.",
          video="medved"),
    Enemy("razboy", "🗡", "Разбойник", 94, 13, 6, (90, 170),
          (Drop("ore", 4, 8), Drop("herbs", 4, 8),
           Drop("fang", 1, 2, 40)),
          rep=2, blurb="С оружием и злой. Только для крепкого бойца."),
    Enemy("ataman", "👹", "Атаман", 215, 30, 13, (190, 360),
          (Drop("ore", 8, 14), Drop("clay", 6, 10, 40),
           Drop("ring", 1, 1, 25)),
          rep=4, blurb="Гроза тракта. С него — перстень-диковина.",
          video="ataman"),
]
ENEMY = {e.id: e for e in ENEMIES}


# ── Редкие элиты (Фаза 3): жирнее HP/золота, гарант-компоненты + шанс на перстень.
# Появляются вместо обычного зверя с шансом HUNT_ELITE_CHANCE при охоте на него.
# Бьются той же снарягой, что и базовый (просто дольше) — приятный джекпот, не
# ловушка. ring@15% — альтернативный (редкий) источник престиж-компонента.
# Элиты — жирная, но СМИРНАЯ добыча: много HP (бой дольше/эпичнее), но атака
# НИЖЕ базового → винрейт ≈ как у обычного зверя (джекпот, а не ловушка-сюрприз).
# Бьются той же снарягой; награда — ×3 золота, гарант-компоненты, перстень@15%.
ELITES: dict[str, Enemy] = {
    "olen": Enemy("olen_gold", "🦌", "✨ Золотой Олень", 72, 5, 1, (60, 110),
                  (Drop("hide", 2, 3), Drop("sinew", 2, 3), Drop("ring", 1, 1, 15)),
                  rep=2, blurb="Шкура отливает золотом, а сам смирный — добыча "
                               "на зависть всему тракту."),
    "volk": Enemy("volk_white", "🐺", "⚪ Белый Волк", 62, 6, 2, (55, 100),
                  (Drop("fang", 2, 3), Drop("sinew", 2, 2), Drop("ring", 1, 1, 15)),
                  rep=2, blurb="Снежный вожак-одиночка, матёрый и грузный. Клыки — "
                               "на загляденье."),
    "kaban": Enemy("kaban_rabid", "🐗", "💢 Бурый Секач", 88, 7, 5, (75, 140),
                   (Drop("hide", 2, 3), Drop("fang", 2, 2), Drop("ring", 1, 1, 15)),
                   rep=2, blurb="Разъелся на желудях до борова — неповоротлив, "
                                "зато добра на нём прорва."),
}


def maybe_elite(enemy_id: str, rng: random.Random) -> Enemy | None:
    """Ролл редкой элиты вместо обычного зверя (Фаза 3). None — обычная охота."""
    elite = ELITES.get(enemy_id)
    if elite and rng.randint(1, 100) <= balance.HUNT_ELITE_CHANCE:
        return elite
    return None


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
    # Крит развязан с удачей (Фаза 1): крит-стат сам по себе, удача → уворот/добыча.
    dmg = balance.BASE_DAMAGE + stats.get("damage", 0)
    crit_pct = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0))
    return dmg, crit_pct, stats.get("armor", 0)


def _dodge_pct(stats: dict) -> int:
    """Шанс уворота от удара зверя (роль удачи): % = удача × коэф, до потолка."""
    return int(min(balance.HUNT_LUCK_DODGE_CAP,
                   stats.get("luck", 0) * balance.HUNT_LUCK_DODGE_PER))


def _combat_dps(stats: dict, enemy: Enemy, hp: int):
    """Ожидаемые урон/раунд игрока (pdps) и зверя по игроку (edps), и время-до-
    убийства обеих сторон — из ВСЕХ статов. Общий движок для шанса и прогноза."""
    dmg = balance.BASE_DAMAGE + stats.get("damage", 0)
    crit = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0)) / 100
    dodge = min(balance.HUNT_LUCK_DODGE_CAP,
                stats.get("luck", 0) * balance.HUNT_LUCK_DODGE_PER) / 100
    tmult = stats.get("dmg_taken_mult", 1.0)
    # крит ×2 И пробивает броню зверя; обычный удар — за вычетом брони
    pdps = (1 - crit) * max(1, dmg - enemy.armor) + crit * 2 * dmg
    mit = balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + stats.get("armor", 0))
    edps = max(0.1, enemy.attack * mit * tmult * (1 - dodge))
    t_kill = enemy.hp / max(0.1, pdps)      # раундов добить зверя
    t_die = hp / edps                       # раундов до своей смерти
    return pdps, edps, t_kill, t_die


def win_chance(stats: dict, enemy: Enemy, start_hp: int | None = None) -> float:
    """Гладкий шанс победы (0..1) — логистика от отношения времени-до-убийства,
    с учётом ВСЕХ статов обеих сторон и потолка раундов. Без жёстких 0/100."""
    hp = balance.BASE_HP if start_hp is None else start_hp
    _pdps, _edps, t_kill, t_die = _combat_dps(stats, enemy, hp)
    # не успел добить за HUNT_MAX_ROUNDS — поражение (overwhelmed): живучесть капается
    r = min(t_die, balance.HUNT_MAX_ROUNDS) / t_kill
    k = balance.HUNT_WINRATE_K
    return r ** k / (r ** k + 1)


def resolve(stats: dict, enemy: Enemy, start_hp: int | None = None,
            rng: random.Random | None = None) -> Fight:
    """Бой: ИСХОД — гладкая логистика win_chance (все статы); раунды — антураж
    (реальные числа ударов) для анимации, согласованный с исходом."""
    rng = rng or random
    php0 = balance.BASE_HP if start_hp is None else start_hp
    won = rng.random() < win_chance(stats, enemy, php0)
    dmg, crit_pct, parmor = _player_offense(stats)
    dodge_pct = _dodge_pct(stats)
    v = balance.HUNT_DMG_VARIANCE
    mit = balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + parmor)
    tmult = stats.get("dmg_taken_mult", 1.0)
    php, ehp = php0, enemy.hp
    rounds = crits = dealt = 0
    log = []
    while ehp > 0 and rounds < balance.HUNT_MAX_ROUNDS:
        rounds += 1
        crit = rng.randint(1, 100) <= crit_pct
        base = dmg if crit else max(1, dmg - enemy.armor)
        hit = max(1, round(base * rng.uniform(1 - v, 1 + v)))
        if crit:
            hit *= 2
            crits += 1
        ehp -= hit
        if not won:
            ehp = max(1, ehp)        # в проигрыше зверь не «умирает» в антураже
        dealt += hit
        ed = 0
        if ehp > 0:
            if rng.randint(1, 100) > dodge_pct:   # удача → уворот: иначе бьёт
                ed = max(1, round(enemy.attack * mit * tmult * rng.uniform(1 - v, 1 + v)))
            php -= ed
            if won:
                php = max(1, php)    # в победе не «умираешь» в антураже
        log.append({"pd": hit, "crit": crit, "ed": ed,
                    "php": max(0, php), "ehp": max(0, ehp)})
        if not won and php <= 0:
            break
    hp_left = max(1, php) if won else 0
    overwhelmed = (not won) and ehp > 0
    return Fight(won, rounds, crits, dealt, hp_left, overwhelmed, log)


def forecast(stats: dict, enemy: Enemy, start_hp: int | None = None,
             n: int = 0, rng: random.Random | None = None) -> tuple[int, int]:
    """Прогноз: (шанс победы %, оценка остаточного HP при победе). Гладкая
    логистика от всех статов — мгновенно, без Монте-Карло (n/rng не нужны,
    оставлены для совместимости вызовов)."""
    hp = balance.BASE_HP if start_hp is None else start_hp
    p = win_chance(stats, enemy, hp)
    _pdps, edps, t_kill, _t_die = _combat_dps(stats, enemy, hp)
    est_hp = max(1, round(hp - t_kill * edps)) if p > 0 else 0
    return round(p * 100), est_hp


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
    elite: bool = False        # попалась редкая элита (Фаза 3)


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

    elite = maybe_elite(enemy_id, rng)   # редкий джекпот вместо обычного зверя
    if elite is not None:
        enemy = elite

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
                          hp_now=player.hp, elite=elite is not None)

    lost = player.gold // balance.HUNT_LOSS_GOLD_DIV  # щепотка золота при поражении
    player.gold -= lost
    player.hp = balance.HP_LOSS_FLOOR
    _mark_recovery(player, now)
    return HuntResult(ok=True, enemy=enemy, fight=fight, gold_lost=lost,
                      elite=elite is not None,
                      hp_now=player.hp)
