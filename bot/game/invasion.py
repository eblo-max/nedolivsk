"""Ивент «Орда орков»: кооперативная town-defense на весь мир.

Жанр — глобальный таймер-босс с авто-резолвом (как «осада» в idle/MMO-чат-играх).
Идея: орда встаёт лагерем на карте; за окно СБОРА таверны «поднимают войско»
(регистрируются); затем войска идут и бьются авто; исход решает суммарная МОЩЬ
записавшихся против ПОРОГА орды. Победа — награды по вкладу; провал — штраф
записавшимся (поход не задался). Один ивент на мир за раз.

Фазы (для бэкенда — по меткам времени):
  gathering : now < gather_until        — идёт регистрация, обратный отсчёт;
  battle    : gather_until ≤ now < resolve_at — войска идут/бьются (визуал на карте);
  won/lost  : now ≥ resolve_at           — терминально, резолв посчитан раз и атомарно.

Здесь — ЧИСТЫЕ помощники (без БД/IO/рассылки): конфиг, мощь, порог, таймлайн,
исход, план раздачи. Всё остальное (запись, тики, награды, анонсы) — снаружи
(repo, notifier, handlers), как у рейдов. Тестируется без БД.
"""

import random
from datetime import datetime, timedelta, timezone

from bot.game import balance

# ── Тайминги ─────────────────────────────────────────────────────────────────
GATHER_MINUTES = 20          # окно регистрации (сбор войска)
MARCH_SECONDS = 35           # визуальный марш (часть фазы battle, для карты)
BATTLE_SECONDS = 300         # авто-бой ≥ 5 мин (требование дизайна)
COOLDOWN_HOURS = 6           # пауза до следующего ивента
# Быстрый тест-режим (/orc fast): полный цикл за ~1.5 мин для отладки.
FAST_GATHER_SECONDS = 60
FAST_MARCH_SECONDS = 10
FAST_BATTLE_SECONDS = 30
AUTO = False                 # авто-спавн по расписанию (старт — только вручную)
# ТЕСТ-режим: ивент закрыт для всех, кроме админа; БЕЗ анонсов в чаты и пуша в лички
# (резолв шлёт сводку/награды только записавшимся — т.е. только админу). Снять, когда
# механика готова к публике.
TEST_MODE = True

# ── Спрайт/тексты ивента ─────────────────────────────────────────────────────
SPRITE = 1                   # орк-модель (assets/boss/ork1_*)
NAME = "Орда орков"
POS = (0.62, 0.16)           # «логово» на карте (норм. координаты, север)

# ── Мощь войска таверны (прозрачно: чем развитее таверна, тем сильнее дружина) ─
MIGHT_BASE = 8
MIGHT_PER_LEVEL = 6
MIGHT_PER_BUILDING = 3

# ── Порог орды (снимок при спавне) = доля суммарной мощи ВСЕХ таверн мира ──────
# Нужно поднять ~COVERAGE долю «военного потенциала» города, иначе орки устоят.
# Авто-масштаб по размеру мира; пол MIN_THRESHOLD — анти-тривиал для малого мира.
COVERAGE = 0.40
MIN_THRESHOLD = 50

# ── Награды (победа) ─────────────────────────────────────────────────────────
# Ивент редкий (кулдаун 6ч), кооперативный и с риском провала → награда «вкусная»,
# это «получка». Личное, по вкладу (мощи приведённого войска): золото + репутация +
# трофейный хабар (ресурсы) каждому, и ОДИН редкий трофей случайному участнику.
WIN_GOLD_BASE = 120
WIN_GOLD_PER_MIGHT = 4.0
WIN_REP = 8
DAMAGE_POOL_PER_HEAD = 60    # доп. золото за бой, делится по ДОЛЕ нанесённого урона
# Хабар (разграбили лагерь орды) — каждому участнику, диапазоны на бойца.
HAUL_RES: dict[str, tuple[int, int]] = {"ore": (10, 20), "grain": (10, 18)}

# Редкий ТРОФЕЙ — одному случайному участнику (равный шанс, чистый кооп). Веса в
# промилле (сумма 1000). СЮДА позже сядут рецепты на уникальную сетовую снарягу
# (kind="recipe") — слот и rarity уже заложены, осталось добавить вариант в ROLL.
TROPHY_LOOT: tuple = (
    ("gold", 520, (350, 650)),          # 🪙 джекпот-золото
    ("res:ingot", 300, (20, 40)),       # слитки
    ("res:honey", 180, (30, 60)),       # мёд (редкий ресурс)
    # ("recipe", N, ("set_id", ...)),   # ← будущее: рецепт на сетовую шмотку
)

# ── Штраф (провал): записавшиеся понесли потери в неудачном походе ────────────
LOSS_GOLD = 40
LOSS_REP = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Мощь и порог ─────────────────────────────────────────────────────────────
def tavern_might(tavern) -> int:
    """Военная мощь дружины таверны: база + уровень + число пристроек."""
    lvl = max(1, int(getattr(tavern, "level", 1) or 1))
    blds = len(getattr(tavern, "buildings", None) or [])
    return MIGHT_BASE + lvl * MIGHT_PER_LEVEL + blds * MIGHT_PER_BUILDING


def horde_threshold(total_world_might: int) -> int:
    """Порог орды из суммарной мощи всех таверн мира (снимок при спавне).
    Используется как анти-тривиал/эталон сложности; реальный исход — в simulate()."""
    return max(MIN_THRESHOLD, round(COVERAGE * max(0, total_world_might)))


# ═══ ТАКТИЧЕСКАЯ БОЕВАЯ МОДЕЛЬ ═══════════════════════════════════════════════
# Орда — настоящий босс (HP/атака/броня + 4 способности по порогам HP). Армия —
# записавшиеся таверны; у каждой боевой профиль из СНАРЯГИ владельца (урон/крит/
# броня/уворот) + размер дружины из МОЩИ таверны (HP/база урона). Роль выводится
# из билда (броня→танк, урон→стрелок, удача→разведка). Бой — детерминированная
# пораундовая симуляция (сид = id ивента): и честно, и воспроизводимо, и даёт
# «боевую сводку» для чата. Исход решает КОМПОЗИЦИЯ, а не сумма.

ROLES: dict[str, tuple[str, str]] = {
    "tank":   ("🛡", "Авангард"),    # держит строй; контрит ярость; защищает тыл
    "archer": ("⚔️", "Рубаки"),      # бёрст-урон (ближний/дальний); контрит зов стаи/стену щитов
    "scout":  ("🔭", "Разведка"),    # уворот/чистка; контрит проклятье шамана
    "ratnik": ("🗡", "Ратники"),     # надёжная линия без спец-контры
}

# Дружина таверны: HP и база урона растут от МОЩИ (развития таверны).
WB_HP_BASE, WB_HP_PER_MIGHT = 80, 4.0
WB_DMG_BASE, WB_DMG_PER_MIGHT = 6.0, 0.45

# Орда. HP масштабируется СУБЛИНЕЙНО от боевой МОЩИ армии (сумма DPS-потенциала),
# а не от числа людей: слабый город валит слабую орду, сильный/многочисленный —
# толще, но БЫСТРЕЕ. Явка и прокачка решают. Атака орды фиксирована и делится на
# «линию фронта» (танки + ратники = массовая пехота); тыл (рубаки/разведка) прикрыт.
ORC_ARMOR = 4
ROUNDS_BUDGET = 45           # окно боя в «раундах» (≈ 5 мин на карте)
HP_PER_POWER = 42.0          # HP орды на единицу мощи (при опорной мощи)
HP_POWER_EXP = 0.82          # сублинейность: <1 → сильнее армия валит быстрее
MIN_ORC_HP = 300             # пол HP (анти-тривиал для крошечной явки)
ORC_ATK = 75                 # фикс. урон орды за раунд (делится на линию фронта)
NO_FRONT_MULT = 3.0          # нет линии фронта (одни рубаки/разведка) — орда прорывается

# Способности по порогам HP орды (срабатывают раз, когда HP падает до порога).
WARD_AT, WARD_ARMOR, WARD_ROUNDS = 0.90, 8, 4      # 🛡 стена щитов: броня ↑ (бьёт крит)
SUMMON_AT, SUMMON_HP_FRAC = 0.70, 0.16             # 🐺 зов стаи: HP-щит волков (бёрст/стрелки)
CURSE_AT, CURSE_FACTOR, CURSE_ROUNDS = 0.45, 0.62, 6   # 💀 проклятье: DPS армии ↓ (чистит разведка)
ENRAGE_AT, ENRAGE_MULT = 0.25, 1.6                 # 🗣 ярость: атака орды ↑ до конца (держат танки)
ARCHER_ADDS_BONUS = 1.7      # стрелки бьют волков-миньонов сильнее
SCOUT_CLEANSE = 0.6          # разведка ослабляет проклятье (по доле разведчиков)


def role_of(stats: dict) -> str:
    """Роль из доминирующего стата билда (нормировано). Слабый билд → ратник."""
    dps = (stats.get("damage", 0) + stats.get("crit", 0) * 0.4) / 12.0
    tank = stats.get("armor", 0) / 8.0
    scout = stats.get("luck", 0) / 8.0
    best = max(dps, tank, scout)
    if best < 0.6:            # снаряга слабая — обычная линия
        return "ratnik"
    if best == tank:
        return "tank"
    if best == scout:
        return "scout"
    return "archer"


def battle_profile(stats: dict, might: int) -> dict:
    """Боевой профиль войска: роль (билд) + урон/крит/броня/уворот (снаряга) +
    HP/база урона (мощь таверны = размер дружины)."""
    crit = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0)) / 100
    dodge = min(balance.HUNT_LUCK_DODGE_CAP,
                stats.get("luck", 0) * balance.HUNT_LUCK_DODGE_PER) / 100
    return {
        "role": role_of(stats),
        "dmg": round(WB_DMG_BASE + might * WB_DMG_PER_MIGHT + stats.get("damage", 0), 1),
        "crit": round(crit, 3),
        "armor": int(stats.get("armor", 0)),
        "dodge": round(dodge, 3),
        "hp": round(WB_HP_BASE + might * WB_HP_PER_MIGHT),
    }


def _unit_output(p: dict, orc_armor: int) -> float:
    """Урон дружины за раунд против текущей брони орды (крит ×2 и пробивает броню)."""
    return (1 - p["crit"]) * max(1.0, p["dmg"] - orc_armor) + p["crit"] * 2 * p["dmg"]


def simulate(participants: list[dict], seed: int = 0) -> dict:
    """Детерминированный бой армии против орды. participants — боевые профили с
    полем pid. Возвращает {won, rounds, orc_hp_max, orc_hp_left, dealt:{pid:int},
    fell:[pid], events:[(round, kind, payload)], n}. Чистая — без БД/IO."""
    n = len(participants)
    if n == 0:
        return {"won": False, "rounds": 0, "orc_hp_max": 0, "orc_hp_left": 0,
                "dealt": {}, "fell": [], "events": [], "n": 0}
    rng = random.Random(seed)
    power = sum(_unit_output(p, ORC_ARMOR) for p in participants) or 1.0
    orc_hp_max = max(MIN_ORC_HP, round(HP_PER_POWER * power ** HP_POWER_EXP))
    orc_hp = float(orc_hp_max)
    orc_atk = ORC_ATK
    units = [dict(p, hp_left=float(p["hp"]), alive=True, dealt=0.0, critdmg=0.0,
                  blocked=0.0) for p in participants]
    scout_frac = sum(1 for p in units if p["role"] == "scout") / n
    adds_hp = 0.0
    ward_until = curse_until = -1
    enraged = False
    done: set[str] = set()
    events: list = []
    armor_k = balance.HUNT_ARMOR_K
    rounds = 0
    while rounds < ROUNDS_BUDGET:
        rounds += 1
        pct = orc_hp / orc_hp_max
        for at, name in ((WARD_AT, "ward"), (SUMMON_AT, "summon"),
                         (CURSE_AT, "curse"), (ENRAGE_AT, "enrage")):
            if name not in done and pct <= at:
                done.add(name)
                if name == "ward":
                    ward_until = rounds + WARD_ROUNDS
                elif name == "summon":
                    adds_hp = orc_hp_max * SUMMON_HP_FRAC
                elif name == "curse":
                    curse_until = rounds + CURSE_ROUNDS
                else:
                    enraged = True
                events.append((rounds, name, None))
        alive = [p for p in units if p["alive"]]
        if not alive:
            break
        orc_armor = ORC_ARMOR + (WARD_ARMOR if rounds <= ward_until else 0)
        curse_mult = 1.0
        if rounds <= curse_until:        # проклятье режет DPS; разведка ослабляет
            relief = min(1.0, scout_frac * 2) * SCOUT_CLEANSE
            curse_mult = CURSE_FACTOR + (1 - CURSE_FACTOR) * relief
        # удар армии: если жив щит волков — бьём его (стрелки ×бонус), иначе орду
        hitting_adds = adds_hp > 0
        adds_dmg = orc_dmg = 0.0
        for p in alive:
            out = _unit_output(p, orc_armor) * curse_mult
            p["dealt"] += out
            p["critdmg"] += p["crit"] * 2 * p["dmg"] * curse_mult   # крит-доля урона
            if hitting_adds:
                adds_dmg += out * (ARCHER_ADDS_BONUS if p["role"] == "archer" else 1.0)
            else:
                orc_dmg += out
        if hitting_adds:
            adds_hp -= adds_dmg
            if adds_hp <= 0:
                orc_hp += adds_hp            # перелив добивает орду
                adds_hp = 0.0
                events.append((rounds, "adds_down", None))
        else:
            orc_hp -= orc_dmg
        if orc_hp <= 0:
            break
        # удар орды: линию фронта держат танки + ратники (массовая пехота), бьют их;
        # совсем нет фронта (одни рубаки/разведка) — орда прорывается и фокусит DPS.
        atk = orc_atk * (ENRAGE_MULT if enraged else 1.0)
        front = [p for p in alive if p["role"] in ("tank", "ratnik")]
        if front:
            share = atk / len(front)
            targets = [(p, share) for p in front]
        else:
            focus = max(alive, key=lambda p: _unit_output(p, orc_armor))
            targets = [(focus, atk * NO_FRONT_MULT)]
        for p, dmg in targets:
            taken = dmg * (armor_k / (armor_k + p["armor"])) * (1 - p["dodge"])
            p["hp_left"] -= taken
            p["blocked"] += max(0.0, dmg - taken)          # урон, погашенный бронёй/уворотом
            if p["hp_left"] <= 0:
                p["alive"] = False
                events.append((rounds, "fall", p["pid"]))
    won = orc_hp <= 0
    return {"won": won, "rounds": rounds, "orc_hp_max": orc_hp_max,
            "orc_hp_left": max(0, round(orc_hp)),
            "dealt": {p["pid"]: round(p["dealt"]) for p in units},
            "stats": {p["pid"]: {"dmg": round(p["dealt"]), "crit": round(p["critdmg"]),
                                 "blocked": round(p["blocked"]), "fell": not p["alive"]}
                      for p in units},
            "fell": [p["pid"] for p in units if not p["alive"]],
            "events": events, "n": n}


# ── Тайминги/фазы ────────────────────────────────────────────────────────────
def gather_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(minutes=GATHER_MINUTES)


def resolve_at(gather_end: datetime) -> datetime:
    """Когда считать исход: конец сбора + марш + бой."""
    return _aware(gather_end) + timedelta(seconds=MARCH_SECONDS + BATTLE_SECONDS)


def schedule(now: datetime | None = None, fast: bool = False) -> tuple[datetime, datetime]:
    """Тайминги ивента (gather_until, resolve_at). fast=True — быстрый тест-режим."""
    now = now or _now()
    g, m, b = ((FAST_GATHER_SECONDS, FAST_MARCH_SECONDS, FAST_BATTLE_SECONDS) if fast
               else (GATHER_MINUTES * 60, MARCH_SECONDS, BATTLE_SECONDS))
    gather_end = now + timedelta(seconds=g)
    return gather_end, gather_end + timedelta(seconds=m + b)


def cooldown_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(hours=COOLDOWN_HOURS)


def phase(inv, now: datetime | None = None) -> str:
    """Фаза по статусу/времени: gathering | battle | won | lost."""
    if inv.status in ("won", "lost"):
        return inv.status
    now = now or _now()
    if now < _aware(inv.gather_until):
        return "gathering"
    return "battle"


def elapsed_secs(inv, now: datetime | None = None) -> float:
    """Секунды с НАЧАЛА сбора (для синхронизации анимации на карте)."""
    now = now or _now()
    start = _aware(inv.started_at)
    return max(0.0, (now - start).total_seconds())


def gather_left(inv, now: datetime | None = None) -> int:
    now = now or _now()
    return max(0, int((_aware(inv.gather_until) - now).total_seconds()))


def is_registered(inv, player_id: int) -> bool:
    return str(player_id) in (inv.registered or {})


def registered_count(inv) -> int:
    return len(inv.registered or {})


def registered_might(inv) -> int:
    return sum(int((r or {}).get("might", 0)) for r in (inv.registered or {}).values())


def dummy_roster(n: int = 8) -> dict:
    """Болванка-армия для отладки (/orc fast army): сбалансированный микс ролей с
    отрицательными pid (не настоящие игроки → в наградах пропускаются). Чтобы видеть
    полноценный бой и победу, не собирая реальную толпу."""
    import random as _r
    rng = _r.Random(99)
    gears = {"tank": {"damage": 4, "crit": 5, "armor": 13, "luck": 4},
             "archer": {"damage": 17, "crit": 28, "armor": 2, "luck": 4},
             "scout": {"damage": 6, "crit": 8, "armor": 3, "luck": 15}}
    pattern = ["tank", "archer", "scout", "archer", "tank", "archer", "scout", "archer"]
    out = {}
    for i in range(n):
        kind = pattern[i % len(pattern)]
        prof = battle_profile(gears[kind], 30)
        out[str(-(i + 1))] = {"name": f"Дружина-{i + 1}", "might": 30,
                              "tx": round(0.2 + 0.6 * rng.random(), 4),
                              "ty": round(0.25 + 0.5 * rng.random(), 4), **prof}
    return out


def make_record(player, tavern, pos, stats: dict) -> dict:
    """Запись бойца в реестр: имя, позиция таверны, мощь дружины + боевой профиль
    (роль/урон/крит/броня/уворот/HP) — снимок на момент записи (фиксирован на бой).
    stats — combat.player_stats(player) (снаряга + бафы)."""
    might = tavern_might(tavern)
    return {"name": player.first_name or str(player.id),
            "tx": round(pos[0], 4), "ty": round(pos[1], 4),
            "might": might, **battle_profile(stats, might)}


# ── Исход и раздача ──────────────────────────────────────────────────────────
def is_won(inv) -> bool:
    """Победа, если суммарная мощь записавшихся ≥ порога орды."""
    return registered_might(inv) >= int(inv.threshold or 0)


def _roll_trophy(rng) -> dict:
    """Один редкий трофей: вид по весам TROPHY_LOOT. Расширяемо до рецептов."""
    tag, _w, payload = rng.choices(TROPHY_LOOT, weights=[w for _, w, _ in TROPHY_LOOT])[0]
    if tag == "gold":
        return {"kind": "gold", "qty": rng.randint(*payload), "rarity": "rare"}
    if tag.startswith("res:"):
        return {"kind": "res", "res": tag.split(":", 1)[1],
                "qty": rng.randint(*payload), "rarity": "rare"}
    # if tag == "recipe": ...  # ← будущее: рецепт на сетовую снарягу (legendary)
    return {"kind": "gold", "qty": rng.randint(100, 200), "rarity": "common"}


def res_label(res: str) -> str:
    """Эмодзи + русское имя ресурса/товара (сырьё RESOURCE_* ИЛИ товар GOODS_*).
    Иначе «ingot/honey» показывались бы английскими буквами."""
    emoji = (balance.RESOURCE_EMOJI.get(res) or getattr(balance, "GOODS_EMOJI", {}).get(res) or "")
    name = (balance.RESOURCE_NAMES.get(res) or getattr(balance, "GOODS_NAMES", {}).get(res) or res)
    return f"{emoji} {name}".strip()


def _trophy_text(drop: dict) -> str:
    if drop.get("kind") == "gold":
        return f"{drop['qty']} 🪙"
    if drop.get("kind") == "res":
        return f"{res_label(drop['res'])} ×{drop['qty']}"
    return "трофей"


def build_report(inv, result: dict, plan: dict) -> list:
    """Полная боевая сводка по каждому участнику для карты: имя, роль, урон,
    крит-урон, заблокировано, пал ли, и НАГРАДА (золото/молва/трофей). Сорт по
    урону. Хранится в inv.result['report']; pid нужен серверу для флага 'свой'."""
    stats = result.get("stats", {})
    trophy = plan.get("trophy") or {}
    mvp = int(trophy["pid"]) if trophy else None
    rows = []
    for pid_s, r in (inv.registered or {}).items():
        pid = int(pid_s)
        st = stats.get(pid, {})
        rows.append({
            "pid": pid, "name": (r or {}).get("name", ""), "role": (r or {}).get("role", "ratnik"),
            "dmg": int(st.get("dmg", 0)), "crit": int(st.get("crit", 0)),
            "blocked": int(st.get("blocked", 0)), "fell": bool(st.get("fell", False)),
            "gold": int(plan["gold"].get(pid, 0)), "rep": int(plan["rep"].get(pid, 0)),
            "trophy": (_trophy_text(trophy["drop"]) if (mvp == pid and trophy) else ""),
        })
    rows.sort(key=lambda x: x["dmg"], reverse=True)
    return rows


def top_contributors(inv, result: dict, k: int = 3) -> list:
    """Топ-бойцы по нанесённому урону: [(pid, name, role, dmg)] по убыванию."""
    dealt = result.get("dealt", {})
    rows = [(int(pid), (r or {}).get("name", ""), (r or {}).get("role", "ratnik"),
             int(dealt.get(int(pid), 0))) for pid, r in (inv.registered or {}).items()]
    rows.sort(key=lambda x: x[3], reverse=True)
    return rows[:k]


def settle(inv, result: dict, rng=None) -> dict:
    """План исхода по РЕЗУЛЬТАТУ симуляции (раздача/штраф). Чистый — применяет
    снаружи, с капами/полами. Победа: каждому золото (база + мощь×коэф + доля от
    пула по НАНЕСЁННОМУ УРОНУ) + репутация + хабар; редкий трофей — лучшему бойцу
    (MVP по урону). Провал: записавшиеся теряют немного золота и репутации.
    Возвращает {won, gold:{pid:Δ}, rep:{pid:Δ}, res:{pid:{res:qty}}, trophy:{pid,drop}|None}."""
    import random as _random
    rng = rng or _random
    won = bool(result.get("won"))
    dealt = result.get("dealt", {})
    total = sum(dealt.values()) or 1
    pool = DAMAGE_POOL_PER_HEAD * result.get("n", 0)
    gold: dict[int, int] = {}
    rep: dict[int, int] = {}
    res: dict[int, dict] = {}
    trophy = None
    for pid_s, r in (inv.registered or {}).items():
        pid = int(pid_s)
        might = int((r or {}).get("might", 0))
        if won:
            share = dealt.get(pid, 0) / total
            gold[pid] = (WIN_GOLD_BASE + round(might * WIN_GOLD_PER_MIGHT)
                         + round(share * pool))
            rep[pid] = WIN_REP
            res[pid] = {k: rng.randint(lo, hi) for k, (lo, hi) in HAUL_RES.items()}
        else:
            gold[pid] = -LOSS_GOLD
            rep[pid] = -LOSS_REP
    if won and dealt:
        mvp = max(dealt, key=dealt.get)                    # трофей — лучшему по урону
        trophy = {"pid": int(mvp), "drop": _roll_trophy(rng)}
    return {"won": won, "gold": gold, "rep": rep, "res": res, "trophy": trophy}
