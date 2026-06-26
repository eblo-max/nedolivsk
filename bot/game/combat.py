"""Охота и бой: снаряга наконец работает. Модель — как в Monster Hunter:

выбираешь зверя → видишь бриф (HP + ТВОЙ расклад по статам: шанс победы,
сколько HP останется) и таблицу добычи (что выпадет точно + редкое с %),
потом идёшь в бой. Бой мгновенный по статам (items.combat_stats): урон×(крит
×2) против HP зверя, его атака против брони. Победа — добыча; поражение — раны.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, buff, economy, inventory, items


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
    region: str = ""             # "" — везде; иначе эксклюзив региона (Фаза 4)
    traits: tuple = ()           # черты-слабости (Фаза 5): "venom" | "evasive"


# Бестиарий: от мелочи (голыми руками) до атамана (только топ-снаряга).
# game=дичь(кухня), honey(медоварня), herbs(сбитень/кухня), berries(вино),
# ore(кузня/стройка), clay(стройка) — добыча кормит производство.
ENEMIES = [
    Enemy("zayac", "👁", "Летучий Глаз", 8, 2, 0, (3, 12),
          (Drop("game", 2, 4),),
          blurb="Мелкая летучая нечисть. Прихлопнёшь и голыми руками.", video=""),
    Enemy("lisa", "🗿", "Горгулья", 18, 4, 0, (10, 22),
          (Drop("game", 2, 4), Drop("herbs", 2, 3, 22)),
          blurb="Каменная пакость с погоста. Юркая, да хрупкая.", video=""),
    Enemy("gadyuka", "🐍", "Медуза", 28, 9, 0, (15, 30),
          (Drop("herbs", 3, 6), Drop("game", 2, 3, 12)),
          blurb="Ядовита — броня не спасёт, только уворот (удача). Яд идёт в зелья.",
          video="", traits=("venom",)),
    Enemy("olen", "🐎", "Кентавр", 54, 7, 1, (18, 34),
          (Drop("game", 6, 10), Drop("herbs", 3, 5, 25),
           Drop("hide", 1, 2, 35), Drop("sinew", 1, 2, 20)),
          blurb="Силён телом, да отпор слабоват. Шкура и жилы идут в дело.", video=""),
    Enemy("volk", "🐺", "Цербер", 40, 7, 2, (16, 32),
          (Drop("game", 4, 7), Drop("herbs", 2, 4, 15),
           Drop("fang", 1, 2, 30), Drop("sinew", 1, 2, 25)),
          blurb="Адский пёс — кусает всерьёз и юлит. Броня не добьёт, нужен урон.",
          video="", traits=("evasive",)),
    Enemy("kaban", "🐂", "Минотавр", 66, 9, 6, (25, 50),
          (Drop("game", 7, 12), Drop("herbs", 3, 5, 20),
           Drop("hide", 1, 2, 30), Drop("fang", 1, 1, 20)),
          blurb="Рога и толстая шкура. Крит пробивает, топор рубит.", video=""),
    Enemy("vozhak", "💀", "Скелет-латник", 88, 12, 4, (45, 85),
          (Drop("game", 8, 14), Drop("ore", 3, 5, 18),
           Drop("fang", 1, 2, 60), Drop("hide", 1, 2, 25)),
          rep=1, video="", blurb="Восставший вояка в ржавой броне. Клыки знатные."),
    Enemy("medved", "🪨", "Каменный Голем", 90, 12, 8, (45, 95),
          (Drop("game", 10, 16), Drop("honey", 3, 6),
           Drop("hide", 2, 3, 60), Drop("fang", 1, 1, 20)),
          rep=1, blurb="Глыба на ножках. Задавит неподготовленного.",
          video=""),
    Enemy("razboy", "👺", "Гоблин-головорез", 94, 13, 6, (90, 170),
          (Drop("ore", 4, 8), Drop("herbs", 4, 8),
           Drop("fang", 1, 2, 40)),
          rep=2, video="", blurb="С дубьём и злой. Только для крепкого бойца."),
    Enemy("ataman", "🐉", "Дракон", 215, 30, 13, (190, 360),
          (Drop("ore", 8, 14), Drop("clay", 6, 10, 40),
           Drop("ring", 1, 1, 25)),
          rep=4, blurb="Гроза тракта. С него — перстень-диковина.",
          video=""),
    # ═══ РЕГИОНАЛЬНЫЕ МОНСТРЫ (Фаза 4): эксклюзив региона, каждый — свой архетип
    # и свой компонент (мех/клык/хитин) для регионального пояса. Сложность
    # паритетная (см. шлюз в симуляторе). Видео нет → фолбэк на картинку охоты.
    Enemy("lynx", "🦅", "Гарпия", 58, 12, 1, (40, 80),
          (Drop("game", 4, 7), Drop("fang", 1, 2, 30), Drop("pelt", 1, 2, 40)),
          rep=1, region="north_wilds", traits=("evasive",), video="",
          blurb="Тайга. Стремительна — уводит удары; нужен высокий урон/крит."),
    Enemy("tusker", "🐐", "Сатир-лучник", 88, 9, 8, (45, 90),
          (Drop("game", 8, 12), Drop("hide", 1, 2, 35), Drop("tusk", 1, 2, 40)),
          rep=1, region="green_valleys", video="",
          blurb="Долины. Бронированный лесовик — сырой урон вязнет, крит пробивает."),
    Enemy("scorpion", "🧙", "Ведьма Пустошей", 66, 8, 7, (40, 85),
          (Drop("herbs", 3, 6), Drop("fang", 1, 1, 25), Drop("chitin", 1, 2, 45)),
          rep=1, region="red_wastes", traits=("venom",), video="",
          blurb="Пустоши. Зелья ядовиты (броня не спасёт — нужна удача), "
                "а защиту пробивает крит."),
]
ENEMY = {e.id: e for e in ENEMIES}


def huntable(region: str | None) -> list[Enemy]:
    """Звери, доступные игроку: общие (region='') + эксклюзив его региона."""
    return [e for e in ENEMIES if not e.region or e.region == region]


# ── Редкие элиты (Фаза 3): жирнее HP/золота, гарант-компоненты + шанс на перстень.
# Появляются вместо обычного зверя с шансом HUNT_ELITE_CHANCE при охоте на него.
# Бьются той же снарягой, что и базовый (просто дольше) — приятный джекпот, не
# ловушка. ring@15% — альтернативный (редкий) источник престиж-компонента.
# Элиты — жирная, но СМИРНАЯ добыча: много HP (бой дольше/эпичнее), но атака
# НИЖЕ базового → винрейт ≈ как у обычного зверя (джекпот, а не ловушка-сюрприз).
# Бьются той же снарягой; награда — ×3 золота, гарант-компоненты, перстень@15%.
ELITES: dict[str, Enemy] = {
    "olen": Enemy("olen_gold", "✨", "✨ Золотой Кентавр", 72, 5, 1, (60, 110),
                  (Drop("hide", 2, 3), Drop("sinew", 2, 3), Drop("ring", 1, 1, 15)),
                  rep=2, blurb="Шкура отливает золотом, а сам смирный — добыча "
                               "на зависть всему тракту."),
    "volk": Enemy("volk_white", "🌙", "🌙 Лунный Цербер", 62, 6, 2, (55, 100),
                  (Drop("fang", 2, 3), Drop("sinew", 2, 2), Drop("ring", 1, 1, 15)),
                  rep=2, blurb="Седой адский пёс-одиночка, матёрый и грузный. "
                               "Клыки — на загляденье."),
    "kaban": Enemy("kaban_rabid", "💢", "💢 Бешеный Минотавр", 88, 7, 5, (75, 140),
                   (Drop("hide", 2, 3), Drop("fang", 2, 2), Drop("ring", 1, 1, 15)),
                   rep=2, blurb="Разъелся на убоине до туши — неповоротлив, "
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


def resolve(stats: dict, enemy: Enemy, start_hp: int | None = None,
            rng: random.Random | None = None) -> Fight:
    """Честный пораундовый бой (как в рогаликах/авто-баттлерах): ИСХОД рождается
    из самих раундов, лог — то, что реально произошло (без подгонки). Игрок и
    зверь бьют по очереди (игрок первым — инициатива); каждый удар:
    крит (×2, пробивает броню) / промах об увёртливого / уворот по удаче /
    яд сквозь броню / разброс ±variance. Кто пал первым — тот и проиграл."""
    rng = rng or random
    php = balance.BASE_HP if start_hp is None else start_hp
    dmg, crit_pct, _ = _player_offense(stats)
    dodge_pct = _dodge_pct(stats)
    v = balance.HUNT_DMG_VARIANCE
    traits = getattr(enemy, "traits", ())
    parmor = stats.get("armor", 0)
    # твоя броня смягчает урон зверя (убыв. отдача); ЯДОВИТЫЙ бьёт сквозь броню
    mit = 1.0 if "venom" in traits else balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + parmor)
    tmult = stats.get("dmg_taken_mult", 1.0)
    ehp = enemy.hp
    rounds = crits = dealt = 0
    log: list = []
    while ehp > 0 and php > 0 and rounds < balance.HUNT_MAX_ROUNDS:
        rounds += 1
        # — твой удар —
        crit = rng.randint(1, 100) <= crit_pct
        miss = "evasive" in traits and rng.random() < balance.HUNT_EVASION   # увёртливый ушёл
        if miss:
            hit, crit = 0, False
        else:
            base = dmg if crit else max(1, dmg - enemy.armor)   # КРИТ пробивает броню зверя
            hit = max(1, round(base * rng.uniform(1 - v, 1 + v)))
            if crit:
                hit *= 2
                crits += 1
        ehp -= hit
        dealt += hit
        # — ответ зверя (только если жив: добил — он уже не бьёт) —
        ed = 0
        if ehp > 0:
            if rng.randint(1, 100) > dodge_pct:                 # удача → уворот, иначе бьёт
                ed = max(1, round(enemy.attack * mit * tmult * rng.uniform(1 - v, 1 + v)))
            php -= ed
        log.append({"pd": hit, "crit": crit, "miss": miss, "ed": ed,
                    "php": max(0, php), "ehp": max(0, ehp)})
    won = ehp <= 0                          # добил зверя (бьёшь первым → при равной гонке твой)
    overwhelmed = (not won) and php > 0     # выжил, но не успел добить за лимит раундов
    hp_left = max(1, php) if won else 0
    return Fight(won, rounds, crits, dealt, hp_left, overwhelmed, log)


def forecast(stats: dict, enemy: Enemy, start_hp: int | None = None,
             n: int = 0, rng: random.Random | None = None) -> tuple[int, int]:
    """Прогноз = Монте-Карло ЧЕСТНОЙ симуляции: (% побед, средний остаток HP при
    победе). Гоняем тот же resolve N раз → показанный шанс СОВПАДАЕТ с реальным
    боем (никакого «театра»: что в прогнозе — то и в бою)."""
    hp = balance.BASE_HP if start_hp is None else start_hp
    samples = max(300, n)                   # стабильная оценка процента
    rng = rng or random
    wins = 0
    hp_sum = 0
    for _ in range(samples):
        f = resolve(stats, enemy, hp, rng)
        if f.win:
            wins += 1
            hp_sum += f.hp_left
    return round(100 * wins / samples), (round(hp_sum / wins) if wins else 0)


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
        economy.record(player, "hunt", loot["gold"])
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
    economy.record(player, "hunt", -lost)
    player.hp = balance.HP_LOSS_FLOOR
    _mark_recovery(player, now)
    return HuntResult(ok=True, enemy=enemy, fight=fight, gold_lost=lost,
                      elite=elite is not None,
                      hp_now=player.hp)
