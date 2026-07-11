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
    Enemy("lisa", "🗿", "Горгулья", 22, 8, 0, (10, 22),
          (Drop("game", 2, 4), Drop("herbs", 2, 3, 22)),
          blurb="Каменная пакость с погоста. Юркая, да хрупкая.", video=""),
    Enemy("gadyuka", "🐍", "Медуза", 22, 9, 0, (15, 30),
          (Drop("herbs", 3, 6), Drop("game", 2, 3, 12)),
          blurb="Ядовита — броня не спасёт, только уворот (удача). Яд идёт в зелья.",
          video="", traits=("venom",)),
    Enemy("olen", "🐎", "Кентавр", 75, 17, 1, (22, 40),
          (Drop("game", 6, 10), Drop("herbs", 3, 5, 25),
           Drop("hide", 1, 2, 35), Drop("sinew", 1, 2, 20)),
          blurb="Наскок: первые раунды бьёт вдвое злее — переживи разгон.",
          video="", traits=("charge",)),
    Enemy("volk", "🐺", "Цербер", 75, 13, 2, (20, 38),
          (Drop("game", 4, 7), Drop("herbs", 2, 4, 15),
           Drop("fang", 1, 2, 30), Drop("sinew", 1, 2, 25)),
          blurb="Адский пёс — кусает всерьёз и юлит. Броня не добьёт, нужен урон.",
          video="", traits=("evasive",)),
    Enemy("kaban", "🐂", "Минотавр", 82, 14, 6, (30, 60),
          (Drop("game", 7, 12), Drop("herbs", 3, 5, 20),
           Drop("hide", 1, 2, 30), Drop("fang", 1, 1, 20)),
          blurb="Ярость: при последней трети здоровья звереет — добивай быстро.",
          video="", traits=("enrage",)),
    Enemy("upyr", "🧟", "Кладбищенский Упырь", 135, 20, 3, (32, 62),
          (Drop("game", 6, 10), Drop("hide", 1, 2, 30), Drop("sinew", 1, 2, 25)),
          rep=1, video="", traits=("lifesteal",),
          blurb="Кровосос: лечится твоей кровью — уворачивайся и бей на убой."),
    Enemy("vozhak", "💀", "Скелет-латник", 254, 31, 4, (60, 115),
          (Drop("game", 8, 14), Drop("ore", 3, 5, 18),
           Drop("fang", 1, 2, 60), Drop("hide", 1, 2, 25)),
          rep=1, video="", traits=("plated",),
          blurb="Латы: криты о него гаснут — тут решает чистый урон."),
    Enemy("medved", "🪨", "Каменный Голем", 368, 39, 8, (70, 140),
          (Drop("game", 10, 16), Drop("honey", 3, 6),
           Drop("hide", 2, 3, 60), Drop("fang", 1, 1, 20)),
          rep=1, traits=("stoneskin",),
          blurb="Каменная кожа: криты не множатся — стакай сырой урон.",
          video=""),
    Enemy("razboy", "👺", "Гоблин-головорез", 402, 42, 6, (120, 220),
          (Drop("ore", 4, 8), Drop("herbs", 4, 8),
           Drop("fang", 1, 2, 40)),
          rep=2, video="", traits=("pickpocket",),
          blurb="Карманник: проиграешь — обчистит вдвое; побьёшь — заберёшь с наваром."),
    Enemy("ataman", "🐉", "Дракон", 780, 78, 13, (280, 520),
          (Drop("ore", 8, 14), Drop("clay", 6, 10, 40),
           Drop("ring", 1, 1, 25)),
          rep=4, traits=("burn",),
          blurb="Жар: каждый твой удар обжигает сквозь броню — кончай бой быстро.",
          video=""),
    # ═══ РЕГИОНАЛЬНЫЕ МОНСТРЫ (Фаза 4): эксклюзив региона, каждый — свой архетип
    # и свой компонент (мех/клык/хитин) для регионального пояса. Сложность
    # паритетная (см. шлюз в симуляторе). Видео нет → фолбэк на картинку охоты.
    Enemy("lynx", "🦅", "Гарпия", 192, 33, 1, (55, 110),
          (Drop("game", 4, 7), Drop("fang", 1, 2, 30), Drop("pelt", 1, 2, 40)),
          rep=1, region="north_wilds", traits=("evasive",), video="",
          blurb="Тайга. Стремительна — уводит удары; нужен высокий урон/крит."),
    Enemy("tusker", "🐐", "Сатир-лучник", 273, 25, 8, (60, 120),
          (Drop("game", 8, 12), Drop("hide", 1, 2, 35), Drop("tusk", 1, 2, 40)),
          rep=1, region="green_valleys", video="", traits=("volley",),
          blurb="Долины. Дуплет: каждый третий раунд стреляет дважды — держи броню."),
    # ═══ ВЕРХНИЙ ЯРУС (боевой пересмотр): контент для орочьего сета и рейд-BiS.
    # Раньше после атамана игра «заканчивалась» — топ-билды имели 100% везде.
    Enemy("ogr", "🗿", "Каменный Огр", 963, 73, 10, (240, 430),
          (Drop("stone", 6, 10), Drop("ore", 5, 9), Drop("ring", 1, 1, 12)),
          rep=3, video="", traits=("stun",),
          blurb="Сотрясение: четвёртый удар оглушает — уворот спасает от гула в голове."),
    Enemy("wyvern", "🐲", "Виверна", 1131, 87, 8, (340, 620),
          (Drop("fang", 2, 3, 80), Drop("herbs", 6, 10), Drop("ring", 1, 1, 18)),
          rep=4, traits=("evasive",), video="",
          blurb="Крылатая бестия — юлит в небе, рвёт когтями. Гроза ветеранов."),
    Enemy("lich", "💀", "Костяной Лич", 888, 58, 14, (420, 760),
          (Drop("ingot", 2, 3, 60), Drop("herbs", 8, 12), Drop("ring", 1, 1, 22)),
          rep=5, traits=("venom", "chill"), video="",
          blurb="Яд сквозь броню и стужа, вымораживающая руки. Вершина охоты."),
    Enemy("scorpion", "🧙", "Ведьма Пустошей", 194, 21, 7, (55, 110),
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
    stats["level"] = int(getattr(player, "level", 1) or 1)
    stats["armor"] = min(balance.ARMOR_CAP, stats.get("armor", 0))  # бюджет живучести
    return stats


def _player_offense(stats: dict) -> tuple[int, int, int]:
    # Крит развязан с удачей (Фаза 1): крит-стат сам по себе, удача → уворот/добыча.
    dmg = (balance.BASE_DAMAGE + stats.get("damage", 0)
           + balance.LEVEL_DAMAGE * stats.get("level", 0))
    crit_pct = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0))
    return dmg, crit_pct, stats.get("armor", 0)


def _dodge_pct(stats: dict) -> int:
    """Шанс уворота от удара зверя (роль удачи): % = удача × коэф, до потолка.
    Плюс плоский бонус фляги (мёд) — поверх, общий потолок чуть выше."""
    base = min(balance.HUNT_LUCK_DODGE_CAP,
               stats.get("luck", 0) * balance.HUNT_LUCK_DODGE_PER)
    return int(min(balance.HUNT_LUCK_DODGE_CAP + 15, base + stats.get("dodge_flat", 0)))


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
    # твоя броня смягчает урон зверя (убыв. отдача); ЯДОВИТЫЙ бьёт сквозь броню,
    # если не выпит сбитень-антидот (фляга) — контрпик из производства таверны
    venom_active = "venom" in traits and not stats.get("antidote")
    mit = 1.0 if venom_active else balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + parmor)
    tmult = stats.get("dmg_taken_mult", 1.0)
    ehp = enemy.hp
    rounds = crits = dealt = 0
    log: list = []
    # ── состояние черт (фаза C): каждая читается, контрится и видна в логе ──
    stunned = False          # 🌀 сотрясение: пропускаешь СВОЙ следующий удар
    chill_stacks = 0         # 🥶 стужа: −1 урона за её укус (пол — доля от базы)
    enemy_hits = 0           # счётчик УСПЕШНЫХ ударов зверя (для сотрясения)
    enraged = False          # 💢 ярость включилась (для лога-вспышки)
    while ehp > 0 and php > 0 and rounds < balance.HUNT_MAX_ROUNDS:
        rounds += 1
        ev: dict = {}                                     # события раунда для анимации
        # — твой удар —
        cur_dmg = dmg
        if chill_stacks:                                  # стужа копится, но есть пол
            cur_dmg = max(int(dmg * balance.TRAIT_CHILL_MAX_FRAC), dmg - chill_stacks)
        crit = rng.randint(1, 100) <= crit_pct
        if crit and "plated" in traits:                   # 🛡 латы: крит гаснет целиком
            crit = False
            ev["plated"] = True
        miss = "evasive" in traits and rng.random() < balance.HUNT_EVASION   # увёртливый ушёл
        if stunned:                                       # оглушён — удар пропал
            hit, crit, miss = 0, False, False
            ev["stunned"] = True
            stunned = False
        elif miss:
            hit, crit = 0, False
        else:
            base = cur_dmg if crit else max(1, cur_dmg - enemy.armor)  # КРИТ пробивает броню
            hit = max(1, round(base * rng.uniform(1 - v, 1 + v)))
            if crit:
                if "stoneskin" in traits:                 # 🗿 каменная кожа: крит не ×2
                    ev["stoneskin"] = True
                else:
                    hit *= 2
                crits += 1
            if "burn" in traits:                          # 🔥 жар: ожог за каждый твой удар
                php -= balance.TRAIT_BURN
                ev["burn"] = balance.TRAIT_BURN
        ehp -= hit
        dealt += hit
        # — ответ зверя (только если жив: добил — он уже не бьёт) —
        ed = 0
        if ehp > 0 and php > 0:
            atk = enemy.attack
            if "charge" in traits and rounds <= balance.TRAIT_CHARGE_ROUNDS:   # 📯 наскок
                atk *= balance.TRAIT_CHARGE_MULT
                ev["charge"] = True
            if "enrage" in traits and ehp <= enemy.hp * balance.TRAIT_ENRAGE_PCT:  # 💢 ярость
                atk *= balance.TRAIT_ENRAGE_MULT
                if not enraged:
                    enraged = ev["enrage"] = True
            strikes = 1
            if "volley" in traits and rounds % balance.TRAIT_VOLLEY_EVERY == 0:    # 🏹 дуплет
                strikes = 2
                ev["volley"] = True
            for _ in range(strikes):
                if rng.randint(1, 100) > dodge_pct:       # удача → уворот, иначе бьёт
                    one = max(1, round(atk * mit * tmult * rng.uniform(1 - v, 1 + v)))
                    ed += one
                    enemy_hits += 1
                    if "lifesteal" in traits:             # 🧛 кровосос: лечится от укуса
                        heal = int(one * balance.TRAIT_LIFESTEAL)
                        if heal:
                            ehp = min(enemy.hp, ehp + heal)
                            ev["lifesteal"] = ev.get("lifesteal", 0) + heal
                    if "chill" in traits:                 # 🥶 стужа: укус морозит руки
                        chill_stacks += 1
                        ev["chill"] = chill_stacks
                    if "stun" in traits and enemy_hits % balance.TRAIT_STUN_EVERY == 0:
                        stunned = True                    # 🌀 следующий твой удар пропадёт
                        ev["stun_next"] = True
            php -= ed
        log.append({"pd": hit, "crit": crit, "miss": miss, "ed": ed,
                    "php": max(0, php), "ehp": max(0, ehp), **ev})
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
    samples = max(400, n)                   # стабильная оценка процента
    # фикс. сид → один и тот же расклад всегда показывает один % (без дрожания в
    # меню). Сам бой (hunt→resolve) использует НАСТОЯЩИЙ random, исход случайный.
    rng = rng or random.Random(0)
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
    flask: list | None = None  # подписи эффектов выпитого перед боем (фаза B)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def max_hp(player=None) -> int:
    """Максимум HP: база + уровень + vitality со шмота (единый каркас персонажа).
    Без игрока (легаси-вызовы) — прежние 35, чтобы ничего не сломать."""
    if player is None:
        return balance.BASE_HP
    lvl = int(getattr(player, "level", 1) or 1)
    vit = items.combat_stats(getattr(player, "equipment", None)).get("vitality", 0)
    return balance.HP_BASE + balance.HP_PER_LEVEL * lvl + vit


def _regen_hours(player) -> float:
    """Часы до полного восстановления HP с учётом бафа «Заживление» (×0.5)."""
    return balance.HP_REGEN_FULL_HOURS * buff.regen_mult(player)


def heal_amount(player, key: str) -> int:
    """Сколько HP вернёт порция: процент от максимума (не обесценивается с ростом)."""
    return max(1, int(round(max_hp(player) * balance.HEAL_PCT.get(key, 0))))


def current_hp(player, now: datetime | None = None) -> int:
    """Текущее здоровье с регенерацией от hp_at к максимуму (max_hp игрока)."""
    mx = max_hp(player)
    cur = player.hp if player.hp is not None else mx
    if cur >= mx or player.hp_at is None:
        return min(mx, cur)
    now = now or _now()
    t = player.hp_at
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    elapsed_h = max(0.0, (now - t).total_seconds() / 3600)
    regen = elapsed_h * mx / _regen_hours(player)
    return int(min(mx, cur + regen))


def _min_hp(player=None) -> int:
    return max(1, int(max_hp(player) * balance.HUNT_MIN_HP_PCT))


def regen_full_minutes(player, now: datetime | None = None) -> int:
    """Минут до полного восстановления HP (0 — уже полное)."""
    mx = max_hp(player)
    chp = current_hp(player, now)
    if chp >= mx:
        return 0
    rate_per_min = (mx / _regen_hours(player)) / 60
    return int((mx - chp) / rate_per_min) + 1


def _mark_recovery(player, now: datetime) -> None:
    """Если ушёл ниже боевого порога — записать время восстановления (для пинга),
    иначе сбросить. Колонка hunt_ready_at используется только для уведомления."""
    need = _min_hp(player)
    if player.hp < need:
        rate = max_hp(player) / _regen_hours(player)
        player.hunt_ready_at = now + timedelta(hours=(need - player.hp) / rate)
    else:
        player.hunt_ready_at = None


def hunt_ready(player, now: datetime | None = None) -> tuple[bool, int]:
    """(в строю?, минут до восстановления до порога). Гейт — по HP, не по таймеру."""
    chp = current_hp(player, now)
    need = _min_hp(player)
    if chp >= need:
        return True, 0
    rate_per_min = (max_hp(player) / _regen_hours(player)) / 60
    return False, int((need - chp) / rate_per_min) + 1


def can_heal(player, now: datetime | None = None) -> bool:
    """Есть ли чем подлечиться (товар в погребе) и не полон ли уже."""
    if current_hp(player, now) >= max_hp(player):
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
    mx = max_hp(player)
    chp = current_hp(player, now)
    if chp >= mx:
        return None
    prods[key] -= 1
    player.tavern.products = prods
    new = min(mx, chp + heal_amount(player, key))
    player.hp = new
    player.hp_at = now
    _mark_recovery(player, now)
    return {"key": key, "healed": new - chp, "hp": new}


def flask_apply(player, keys: list[str] | None,
                stats: dict, chp: int,
                consume: bool = True) -> tuple[int, list[str], list[str]]:
    """Выпить/съесть до FLASK_SLOTS порций ИЗ ПОГРЕБА перед боем: списывает
    продукты, мутирует stats (dmg/crit/dodge/antidote), возвращает
    (hp_на_бой, применённые_ключи, подписи_эффектов). Нет в погребе — порция
    просто пропускается (фронт шлёт актуальное, гонка не валит бой)."""
    if not keys or player.tavern is None:
        return chp, [], []
    from bot.game import recipes as rec        # тайные ИИ-блюда: свой склад + эффекты
    prods = dict(player.tavern.products or {})
    used: list[str] = []
    labels: list[str] = []
    prods_dirty = False
    for key in list(keys)[:balance.FLASK_SLOTS]:
        eff = balance.FLASK_EFFECTS.get(key)
        if eff is not None:                    # статическое благо — из погреба products
            if prods.get(key, 0) <= 0:
                continue
            prods[key] -= 1
            prods_dirty = True
            labels.append(eff["label"])
        else:                                  # тайный рецепт — из своего склада
            reff = rec.effects_for_key(key)
            if reff is None or rec.stock_get(player.tavern, key) <= 0:
                continue
            if consume and not rec.stock_spend(player.tavern, key, 1):
                continue
            eff = reff
            labels.append(rec.cellar_label(eff))
        used.append(key)
        stats["damage"] = stats.get("damage", 0) + eff.get("dmg", 0)
        stats["crit"] = stats.get("crit", 0) + eff.get("crit", 0)
        stats["dodge_flat"] = stats.get("dodge_flat", 0) + eff.get("dodge", 0)
        if eff.get("antidote"):
            stats["antidote"] = True
        chp += eff.get("hp", 0)
    if consume and prods_dirty:
        player.tavern.products = prods
    return chp, used, labels


def hunt(player, enemy_id: str, rng: random.Random | None = None,
         flask: list[str] | None = None) -> HuntResult:
    """Сходить на охоту: гейт по HP, фляга (порции из погреба на бой), бой от
    текущего HP, добыча/утомление/раны."""
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
    chp, _used, flask_labels = flask_apply(player, flask, stats, chp)  # фляга (фаза B)
    fight = resolve(stats, enemy, chp, rng)
    player.hp_at = now
    if fight.win:
        from bot.game import fgoal
        fgoal.note("hunt", 1)                       # облава Стражи: −1 тварь
        loot = roll_loot(enemy, stats.get("luck", 0), rng)
        loot["gold"] = int(loot["gold"] * buff.hunt_gold_mult(player))  # «Звериный нюх»
        if "pickpocket" in getattr(enemy, "traits", ()):   # 💰 обчистил карманника — навар
            loot["gold"] = int(loot["gold"] * (1 + balance.TRAIT_PICKPOCKET_WIN_BONUS))
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
                          hp_now=player.hp, elite=elite is not None,
                          flask=flask_labels)

    lost = player.gold // balance.HUNT_LOSS_GOLD_DIV  # щепотка золота при поражении
    if "pickpocket" in getattr(enemy, "traits", ()):       # 💰 карманник обчистил тебя
        from bot.game import factions, rumors
        lost = int(lost * balance.TRAIT_PICKPOCKET_LOSE_MULT
                   * factions.watch_pickpocket_mult(player))  # друзей стражи щиплют меньше
        rumors.note("pickpocket", player, lost)               # позор — пища для сплетен
    player.gold -= lost
    economy.record(player, "hunt", -lost)
    player.hp = balance.HP_LOSS_FLOOR
    _mark_recovery(player, now)
    return HuntResult(ok=True, enemy=enemy, fight=fight, gold_lost=lost,
                      elite=elite is not None,
                      hp_now=player.hp, flask=flask_labels)
