"""Глобальный рейд-босс: кооп на весь мир, две фазы.

ФАЗА 1 «Сбор» (GATHER_MINUTES): анонс во все чаты, игроки жмут «Присоединиться»,
текст с обратным отсчётом обновляется. ФАЗА 2 «Битва» (FIGHT_HOURS): босс «дошёл»,
HP подбирается под число записавшихся, бьют ТОЛЬКО записавшиеся. Повержен —
золото из пула делится ПОРОВНУ на всех, кто реально бил; одному случайному из
них с РАВНЫМ шансом падает редкий дроп, редчайшее — снаряга.

Здесь — чистые помощники. DB/IO/рассылка — снаружи (handlers, notifier).
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, combat

GATHER_MINUTES = 20      # сбор перед битвой
FIGHT_HOURS = 1          # окно на добивание

# Self-баффы/дебаффы босса в бою.
STALL_REGEN_MINUTES = 5      # E2: нет ударов столько минут → босс лечится (анти-АФК,
                             # а не наказание за норм. ритм; 5 мин = реально забросили)
STALL_REGEN_PCT = 0.02       # E2: сколько max_hp реген за тик простоя
ROAR_EVERY_MINUTES = 8       # D2: как часто босс ревёт (оглушает всех бьющих)
ROAR_STUN_SECONDS = 120      # D2/S8: на сколько оглушает (доп. задержка удара)
SECOND_WIND_AT = 0.30        # S8: порог HP, на котором срабатывает «второе дыхание»
SECOND_WIND_HEAL_PCT = 0.20  # S8: на сколько max_hp лечится (один раз)

# ── Фазы боя по доле HP: чем ниже здоровье — тем злее тварь ──────────────────
PHASE2_AT = 0.66             # ниже этой доли HP — фаза 2 (разъярён)
PHASE3_AT = 0.33            # ниже этой доли HP — фаза 3 (бешенство)
# Ярость (🔥): с фазой растёт реген и учащаются все касты (множитель интервала <1).
ENRAGE_REGEN_MULT = {1: 1.0, 2: 1.4, 3: 1.8}
ENRAGE_CADENCE_MULT = {1: 1.0, 2: 0.7, 3: 0.5}

# Спеллбук — заклинания, что босс кастует по тику нотифаера (раз в минуту).
# 🛡 Щит/Ward: на время режет входящий урон.
WARD_EVERY_MIN = 7
WARD_DURATION_SEC = 90
WARD_MITIGATE = 0.30         # урон под щитом × 0.30
# 💀 Проклятье/дебафф: на время слабит удары ВСЕХ бьющих.
CURSE_EVERY_MIN = 9
CURSE_DURATION_SEC = 90
CURSE_FACTOR = 0.55          # удар проклятых × 0.55
# 👹 Призыв миньонов: вешает «щит» из HP миньонов — бить сперва их, иначе вольются.
SUMMON_EVERY_MIN = 11
SUMMON_HP_PCT = 0.07         # щит миньонов = 7% max_hp
SUMMON_TTL_SEC = 240         # не счистили за 4 мин → миньоны вливаются (хил боссу)
SUMMON_MERGE_FRAC = 0.5      # вольются — лечат лишь на половину остатка щита


@dataclass(frozen=True)
class Boss:
    key: str
    emoji: str
    name: str
    hp_per_fighter: int     # HP за каждого записавшегося (масштаб под явку)
    min_hp: int             # пол HP (чтобы малой толпой не было тривиально)
    gold_pool: int          # делится поровну между всеми, кто бил (краник)
    blurb: str
    # Лут: один бонус-дроп победителю. Веса в промилле (сумма 1000) —
    # чтобы точно держать малые шансы на снарягу. Вид: res:<r>/ingot/gold/gear.
    loot: tuple             # ((вид, вес‰, payload), ...)
    gear_pool: tuple        # из каких предметов может выпасть снаряга с этого босса
    gear_tier_weights: tuple = (80, 18, 2)   # веса ярусов ★/★★/★★★ выпавшей снаряги
    cooldown_min: int = 6   # пауза между ударами одного игрока
    armor: int = 0          # «толща» босса: гасит часть урона за удар (max(1, dmg-armor))
    video: str = ""         # имя ролика в assets/<video>.mp4 (анонс-видео); "" = текст
    spellbook: tuple = ()   # заклинания босса: "ward"/"curse"/"summon" (ярость — всегда)


# Ярусы редкости бонус-дропа (для подписи в сообщениях).
RARITY = {"common": "обычный", "rare": "🔶 РЕДКИЙ", "legendary": "💎 ЛЕГЕНДАРНЫЙ"}


def _rarity_of(kind: str) -> str:
    """Снаряга — легендарное (редчайшее), золото-джекпот — редкое, прочее — обычное."""
    if kind == "gear":
        return "legendary"
    if kind == "gold":
        return "rare"
    return "common"


# Уровни: от слабого к грозному. Шанс и качество снаряги растут с тиром босса.
# Снаряга — редчайшее: 1.5% / 3.5% / 7% за убийство. Топ-вещи ★★★ — только с Дракона.
BOSSES: dict[str, Boss] = {
    "rat_king": Boss(
        "rat_king", "🐀", "Крысиный Король", 520, 1600, 800,
        "Размером с борова, наглый как сборщик податей. Вылез из-под пола и жрёт "
        "всё, до чего дотянется. Прихлопнуть можно — но всем миром, по одному только "
        "лапу отгрызёт.",
        (("res:grain", 455, ("grain", 20, 40)), ("res:hops", 320, ("hops", 15, 30)),
         ("gold", 145, (60, 120)), ("gear", 80, None)),   # 8% — лёгкий босс, щедр на (слабую) снарягу
        gear_pool=("rat_crown", "rat_pelt", "rat_tail"),
        gear_tier_weights=(82, 16, 2), cooldown_min=1, armor=3, video="rat_king",
        spellbook=("summon", "curse")),    # крысиный рой + чумная зараза
    "bog_troll": Boss(
        "bog_troll", "👹", "Болотный Тролль", 440, 1800, 2400,
        "Гора смрадного мяса по пояс в тине. Каждый шаг — как телега с навозом, "
        "каждый замах — как падающий дуб. Сунешься один — раскатает в блин.",
        (("res:ore", 465, ("ore", 25, 50)), ("ingot", 300, (10, 20)),
         ("gold", 185, (150, 300)), ("gear", 50, None)),   # 5% — середняк
        gear_pool=("troll_club", "troll_hide", "troll_eye"),
        gear_tier_weights=(50, 42, 8), cooldown_min=1, armor=8, video="bog_troll",
        spellbook=("ward", "summon")),     # дублёная шкура + болотный выводок
    "dragon": Boss(
        "dragon", "🐲", "Древний Змей", 400, 1700, 6000,
        "Древний, злой и голодный до золота. Накроет тенью пол-Недоливска, дохнёт "
        "огнём — и от кабака одни головешки. Идёт весь мир разом, иначе всем крышка.",
        (("ingot", 520, (25, 45)), ("res:honey", 300, ("honey", 30, 60)),
         ("gold", 150, (300, 600)), ("gear", 30, None)),   # 3% — сильный босс, снаряга редкая (престиж, она же 2× мощнее)
        gear_pool=("dragon_fang", "dragon_scale", "dragon_heart"),
        gear_tier_weights=(14, 50, 36), cooldown_min=1, armor=15, video="dragon",
        spellbook=("ward", "curse", "summon")),   # всё: чешуя-щит, ужас, выводок
}


def gear_drop_pct(boss_key: str) -> float:
    """Шанс (%), что бонус-дроп победителю окажется ЭКСКЛЮЗИВНОЙ снарягой.
    Считается из весов лута (промилле, сумма 1000) — для анонса/прозрачности."""
    spec = BOSSES.get(boss_key)
    if spec is None:
        return 0.0
    total = sum(w for _, w, _ in spec.loot)
    gear = sum(w for tag, w, _ in spec.loot if tag == "gear")
    return round(100 * gear / total, 1) if total else 0.0


# Лёгкий кэш «есть ли живой рейд» — чтобы меню таверны рисовало кнопку без
# запроса к БД на каждый рендер. Ставит спавн (сразу) и нотифаер (раз в тик).
_active_raid_id: int | None = None


def set_active(raid_id: int | None) -> None:
    global _active_raid_id
    _active_raid_id = raid_id


def active_id() -> int | None:
    return _active_raid_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def gather_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(minutes=GATHER_MINUTES)


def fight_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(hours=FIGHT_HOURS)


def hp_for(boss_key: str, fighters: int) -> int:
    """HP босса под число записавшихся (с полом)."""
    spec = BOSSES[boss_key]
    return max(spec.min_hp, fighters * spec.hp_per_fighter)


def registered_count(boss) -> int:
    return len(boss.contributions or {})


def is_registered(boss, player_id: int) -> bool:
    return str(player_id) in (boss.contributions or {})


def register(boss, player) -> bool:
    """Записать игрока в рейд (фаза сбора). False — уже записан."""
    c = dict(boss.contributions or {})
    pid = str(player.id)
    if pid in c:
        return False
    c[pid] = {"dmg": 0, "hits": 0, "name": player.first_name or pid}
    boss.contributions = c
    return True


def hp_bar(hp: int, max_hp: int, width: int = 12) -> str:
    hp = max(0, hp)
    filled = round(width * hp / max_hp) if max_hp else 0
    return "🟥" * filled + "⬛" * (width - filled)


def player_damage(player, rng: random.Random | None = None) -> tuple[int, bool]:
    """Урон игрока по боссу за удар: снаряга + уровень, крит ×2, разброс ±20%."""
    rng = rng or random
    stats = combat.player_stats(player)
    base = balance.BASE_DAMAGE + stats.get("damage", 0) + (player.level or 1) * 2
    crit_pct = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0) + stats.get("luck", 0) // 2)
    crit = rng.randint(1, 100) <= crit_pct
    dmg = base * (2 if crit else 1) * rng.uniform(0.8, 1.2)
    return max(1, int(dmg)), crit


def _iso_left(iso: str | None, now: datetime) -> int:
    """Секунд до момента iso (0 если прошёл/нет)."""
    if not iso:
        return 0
    try:
        return max(0, int(datetime.fromisoformat(iso).timestamp() - now.timestamp()))
    except (ValueError, TypeError):
        return 0


def stun_left(boss, now: datetime | None = None) -> int:
    """Секунд оглушения босса (рык D2 / второе дыхание S8) — общий на всех."""
    return _iso_left((boss.state or {}).get("stun_until"), now or _now())


def cooldown_left(boss, player_id: int, now: datetime | None = None) -> int:
    """Секунд до следующего удара: max(личный кулдаун, общее оглушение босса)."""
    now = now or _now()
    rec = (boss.contributions or {}).get(str(player_id))
    personal = 0
    if rec and isinstance(rec.get("last"), str):
        cd = BOSSES[boss.boss_key].cooldown_min * 60
        last_dt = datetime.fromisoformat(rec["last"]) + timedelta(seconds=cd)
        personal = _iso_left(last_dt.isoformat(), now)
    return max(personal, stun_left(boss, now))


def stunned(boss, player_id: int, now: datetime | None = None) -> bool:
    """Оглушение — главная причина ждать (рык/второе дыхание сильнее личного кд)."""
    now = now or _now()
    return stun_left(boss, now) >= cooldown_left(boss, player_id, now) > 0


def _fight_start(boss) -> datetime:
    if boss.ends_at is not None:
        e = boss.ends_at
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        return e - timedelta(hours=FIGHT_HOURS)
    return _now()


def last_hit_at(boss) -> datetime:
    """Когда по боссу били в последний раз (для E2). Нет ударов — старт боя."""
    times = [datetime.fromisoformat(r["last"]) for r in (boss.contributions or {}).values()
             if isinstance(r.get("last"), str)]
    return max(times) if times else _fight_start(boss)


def phase(boss) -> int:
    """Фаза боя по доле HP: 1 (>66%), 2 (33–66%, разъярён), 3 (<33%, бешенство).
    Чем ниже — тем сильнее реген и тем чаще касты (см. ENRAGE_*)."""
    if not boss.max_hp or boss.max_hp <= 0:
        return 1
    frac = max(0, boss.hp) / boss.max_hp
    if frac > PHASE2_AT:
        return 1
    if frac > PHASE3_AT:
        return 2
    return 3


def regen_if_stalled(boss, now: datetime | None = None) -> int:
    """E2: если по боссу не били STALL_REGEN_MINUTES — лечит часть HP. С фазой
    ярости лечит сильнее (ENRAGE_REGEN_MULT). Вернёт сколько подлечил."""
    now = now or _now()
    if boss.max_hp <= 0 or boss.hp >= boss.max_hp:
        return 0
    if (now - last_hit_at(boss)).total_seconds() < STALL_REGEN_MINUTES * 60:
        return 0
    mult = ENRAGE_REGEN_MULT.get(phase(boss), 1.0)
    heal = max(1, int(boss.max_hp * STALL_REGEN_PCT * mult))
    boss.hp = min(boss.max_hp, boss.hp + heal)
    return heal


def roar_if_due(boss, now: datetime | None = None) -> bool:
    """D2: раз в ROAR_EVERY_MINUTES (в ярости — чаще) босс ревёт, оглушая всех
    бьющих. True — взревел."""
    now = now or _now()
    last = (boss.state or {}).get("last_roar")
    base = datetime.fromisoformat(last) if isinstance(last, str) else _fight_start(boss)
    every = ROAR_EVERY_MINUTES * ENRAGE_CADENCE_MULT.get(phase(boss), 1.0)
    if (now - base).total_seconds() < every * 60:
        return False
    st = dict(boss.state or {})
    st["stun_until"] = (now + timedelta(seconds=ROAR_STUN_SECONDS)).isoformat()
    st["last_roar"] = now.isoformat()
    boss.state = st
    return True


def maybe_second_wind(boss, now: datetime | None = None) -> bool:
    """S8: один раз на ≤30% HP — хил + рык (оглушение всех). True — сработало."""
    now = now or _now()
    st = boss.state or {}
    if st.get("second_wind") or boss.max_hp <= 0:
        return False
    if not (0 < boss.hp <= boss.max_hp * SECOND_WIND_AT):
        return False
    boss.hp = min(boss.max_hp, boss.hp + int(boss.max_hp * SECOND_WIND_HEAL_PCT))
    st = dict(boss.state or {})
    st["second_wind"] = True
    st["stun_until"] = (now + timedelta(seconds=ROAR_STUN_SECONDS)).isoformat()
    boss.state = st
    return True


# ── Спеллбук: щит / проклятье / призыв миньонов ─────────────────────────────

def ward_left(boss, now: datetime | None = None) -> int:
    """Секунд активного щита (🛡): пока тикает — входящий урон режется."""
    return _iso_left((boss.state or {}).get("ward_until"), now or _now())


def curse_left(boss, now: datetime | None = None) -> int:
    """Секунд активного проклятья (💀): пока тикает — удары всех ослаблены."""
    return _iso_left((boss.state or {}).get("curse_until"), now or _now())


def adds_hp(boss) -> int:
    """HP-щит призванных миньонов (👹): бьётся первым, пока > 0."""
    return int((boss.state or {}).get("adds_hp", 0) or 0)


def _due(st: dict, key: str, every_min: float, boss, now: datetime) -> bool:
    """Пора ли каст «key»: прошло ≥ every_min (с учётом ярости) c прошлого раза.
    Базовая точка — старт боя (чтобы не пальнуть всем сразу на 0-й минуте)."""
    last = st.get(key)
    base = datetime.fromisoformat(last) if isinstance(last, str) else _fight_start(boss)
    every = every_min * ENRAGE_CADENCE_MULT.get(phase(boss), 1.0)
    return (now - base).total_seconds() >= every * 60


def cast_tick(boss, now: datetime | None = None) -> list[str]:
    """Ход босса (зовётся нотифаером раз в минуту): фазы ярости, реген простоя,
    рык и заклинания из spellbook. Мутирует boss (hp/state); коммит — снаружи.
    Возвращает список «громких» событий (ключи) для пуша бойцам и лога."""
    now = now or _now()
    spec = BOSSES.get(boss.boss_key)
    if spec is None or boss.status != "active":
        return []
    events: list[str] = []
    st = dict(boss.state or {})
    ph = phase(boss)

    # Объявление новой фазы ярости (один раз на фазу).
    if ph >= 2 and int(st.get("phase", 1)) < ph:
        st["phase"] = ph
        events.append("enrage2" if ph == 2 else "enrage3")

    # Миньоны истекли и не счищены → вливаются в босса (хил на половину остатка).
    adds_until = st.get("adds_until")
    if st.get("adds_hp") and adds_until and _iso_left(adds_until, now) == 0:
        boss.hp = min(boss.max_hp, boss.hp + int(st.get("adds_hp", 0) * SUMMON_MERGE_FRAC))
        st["adds_hp"] = 0
        st.pop("adds_until", None)
        events.append("adds_merge")

    boss.state = st  # зафиксировать до спелл-кастов (они снова возьмут свежую копию)

    # 🛡 Щит
    if "ward" in spec.spellbook and not ward_left(boss, now) and \
            _due(boss.state or {}, "last_ward", WARD_EVERY_MIN, boss, now):
        st = dict(boss.state or {})
        st["ward_until"] = (now + timedelta(seconds=WARD_DURATION_SEC)).isoformat()
        st["last_ward"] = now.isoformat()
        boss.state = st
        events.append("ward")

    # 💀 Проклятье
    if "curse" in spec.spellbook and not curse_left(boss, now) and \
            _due(boss.state or {}, "last_curse", CURSE_EVERY_MIN, boss, now):
        st = dict(boss.state or {})
        st["curse_until"] = (now + timedelta(seconds=CURSE_DURATION_SEC)).isoformat()
        st["last_curse"] = now.isoformat()
        boss.state = st
        events.append("curse")

    # 👹 Призыв миньонов (только если прошлый выводок уже счищен)
    if "summon" in spec.spellbook and adds_hp(boss) <= 0 and \
            _due(boss.state or {}, "last_summon", SUMMON_EVERY_MIN, boss, now):
        st = dict(boss.state or {})
        st["adds_hp"] = max(1, int(boss.max_hp * SUMMON_HP_PCT))
        st["adds_until"] = (now + timedelta(seconds=SUMMON_TTL_SEC)).isoformat()
        st["last_summon"] = now.isoformat()
        boss.state = st
        events.append("summon")

    # Рык (оглушение) и реген простоя — общие для всех боссов.
    if roar_if_due(boss, now):
        events.append("roar")
    if regen_if_stalled(boss, now) > 0:
        events.append("regen")
    return events


def mitigate(boss_key: str, raw: int) -> int:
    """Срезать «толщей» босса ПРОЦЕНТНО (как на охоте): урон × K/(K+броня).
    Плоское вычитание топило слабых наглухо в 1 — а так слабый хоть царапает,
    снаряга/уровень усиливают, толстый босс (выше броня) режет процент сильнее.
    Урон всегда ≥1."""
    armor = BOSSES[boss_key].armor
    return max(1, round(raw * balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + armor)))


def apply_hit(boss, player, dmg: int, now: datetime | None = None,
              credit: int | None = None) -> None:
    """Снять HP боссу на dmg и записать вклад игрока. credit — сколько засчитать
    в лидерборд (по умолчанию = dmg; при бое по миньонам туда идёт и урон по
    щиту, а боссу — только остаток). Мутирует boss; коммит снаружи."""
    now = now or _now()
    c = dict(boss.contributions or {})
    pid = str(player.id)
    # ВАЖНО: rec — СВЕЖАЯ копия (dict(...)), а не общий вложенный объект. Если
    # менять вложенный словарь «на месте», он же сидит в снимке SQLAlchemy для
    # сравнения — снимок «портится», новое значение кажется равным старому, и
    # колонка contributions НЕ пишется (урон теряется, хотя hp снимается). Копия
    # рвёт эту связь: новое значение реально отличается от снимка → запись идёт.
    rec = dict(c.get(pid) or {"dmg": 0, "hits": 0, "name": player.first_name or pid})
    rec["dmg"] = int(rec.get("dmg", 0)) + (dmg if credit is None else credit)
    rec["hits"] = int(rec.get("hits", 0)) + 1
    rec["last"] = now.isoformat()
    c[pid] = rec
    boss.contributions = c
    boss.hp = max(0, boss.hp - dmg)


def resolve_hit(boss, player, now: datetime | None = None,
                rng: random.Random | None = None) -> dict:
    """Единый расчёт удара по боссу со всеми механиками и запись результата.
    Порядок: урон игрока → 💀 проклятье (×CURSE) → 🛡 щит (×WARD) → толща-броня
    → 👹 миньоны (сперва их щит, остаток — боссу). Мутирует boss; коммит снаружи.
    Возвращает флаги для тоста: dmg (по боссу), crit, soaked (съедено бронёй),
    curse/ward (активны ли), adds_dmg, adds_left, adds_cleared."""
    now = now or _now()
    raw, crit = player_damage(player, rng)

    curse = curse_left(boss, now) > 0
    if curse:
        raw = max(1, round(raw * CURSE_FACTOR))

    ward = ward_left(boss, now) > 0
    after_armor = mitigate(boss.boss_key, raw)        # толща-броня (процентом)
    dmg = max(1, round(after_armor * WARD_MITIGATE)) if ward else after_armor
    soaked = max(0, raw - dmg)

    # Сперва бьём щит миньонов; остаток уходит в HP босса.
    adds = adds_hp(boss)
    adds_dmg = min(adds, dmg) if adds > 0 else 0
    boss_dmg = dmg - adds_dmg
    adds_cleared = False
    if adds_dmg:
        st = dict(boss.state or {})
        st["adds_hp"] = adds - adds_dmg
        if st["adds_hp"] <= 0:
            st["adds_hp"] = 0
            st.pop("adds_until", None)
            adds_cleared = True
        boss.state = st

    apply_hit(boss, player, boss_dmg, now, credit=dmg)
    return {"dmg": boss_dmg, "crit": crit, "soaked": soaked,
            "curse": curse, "ward": ward, "adds_dmg": adds_dmg,
            "adds_left": adds_hp(boss), "adds_cleared": adds_cleared}


def is_dead(boss) -> bool:
    return boss.status == "active" and boss.hp <= 0


def settle(boss, rng: random.Random | None = None) -> dict:
    """План раздачи: {gold: {pid:int}, winner: pid|None, drop: dict|None}.
    Золото — пул ПОРОВНУ на всех, кто реально бил; редкий дроп — одному
    случайному из них с РАВНЫМ шансом (не по вкладу — чистый кооп)."""
    rng = rng or random
    contrib = {int(p): r for p, r in (boss.contributions or {}).items()
               if r.get("dmg", 0) > 0}                     # только реально бившие
    spec = BOSSES[boss.boss_key]
    n = len(contrib)
    # Строго ≤ пула: доля = пол(пул/бойцов). При толпе больше пула доля=0
    # (золото не «печатается» сверх пула — целостность глобальной экономики).
    per = spec.gold_pool // n if n else 0
    gold = {pid: per for pid in contrib} if per else {}
    winner, drop = None, None
    if contrib:
        pids = list(contrib)
        winner = rng.choice(pids)                          # равный шанс каждому
        tag, _w, payload = rng.choices(spec.loot, weights=[w for _, w, _ in spec.loot])[0]
        if tag == "gear":
            tier = rng.choices((1, 2, 3), weights=spec.gear_tier_weights)[0]
            drop = {"kind": "gear", "item_id": rng.choice(spec.gear_pool), "tier": tier}
        elif tag == "ingot":
            drop = {"kind": "res", "res": "ingot", "qty": rng.randint(*payload)}
        elif tag == "gold":
            drop = {"kind": "gold", "qty": rng.randint(*payload)}
        else:  # res:<name>
            res, lo, hi = payload
            drop = {"kind": "res", "res": res, "qty": rng.randint(lo, hi)}
        drop["rarity"] = _rarity_of(tag)
    return {"gold": gold, "winner": winner, "drop": drop}
