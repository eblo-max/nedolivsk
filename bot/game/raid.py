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
    video: str = ""         # имя ролика в assets/<video>.mp4 (анонс-видео); "" = текст


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
        "rat_king", "🐀", "Крысиный Король", 80, 200, 300,
        "Жирная тварь из подвалов — соберитесь да прихлопните всем миром.",
        (("res:grain", 520, ("grain", 20, 40)), ("res:hops", 320, ("hops", 15, 30)),
         ("gold", 145, (60, 120)), ("gear", 15, None)),
        gear_pool=("rat_crown", "rat_pelt", "rat_tail"),
        gear_tier_weights=(82, 16, 2), cooldown_min=5, video="rat_king"),
    "bog_troll": Boss(
        "bog_troll", "👹", "Болотный Тролль", 180, 700, 900,
        "Воняет тиной и крушит всё подряд. В одиночку не взять — зовите всех.",
        (("res:ore", 480, ("ore", 25, 50)), ("ingot", 300, (10, 20)),
         ("gold", 185, (150, 300)), ("gear", 35, None)),
        gear_pool=("troll_club", "troll_hide", "troll_eye"),
        gear_tier_weights=(50, 42, 8), cooldown_min=6, video="bog_troll"),
    "dragon": Boss(
        "dragon", "🐲", "Древний Змей", 350, 1800, 2600,
        "Гроза Недоливска. Идёт весь мир — иначе спалит дотла.",
        (("ingot", 480, (25, 45)), ("res:honey", 300, ("honey", 30, 60)),
         ("gold", 150, (300, 600)), ("gear", 70, None)),
        gear_pool=("dragon_fang", "dragon_scale", "dragon_heart"),
        gear_tier_weights=(14, 50, 36), cooldown_min=7, video="dragon"),
}


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


def cooldown_left(boss, player_id: int, now: datetime | None = None) -> int:
    """Секунд до следующего удара игрока (0 — можно бить)."""
    rec = (boss.contributions or {}).get(str(player_id))
    if not rec or not rec.get("last"):
        return 0
    cd = BOSSES[boss.boss_key].cooldown_min * 60
    try:
        last = datetime.fromisoformat(rec["last"])
    except (ValueError, TypeError):
        return 0
    return max(0, int(cd - (now or _now()).timestamp() + last.timestamp()))


def apply_hit(boss, player, dmg: int, now: datetime | None = None) -> None:
    """Записать урон игрока и снять HP (мутирует boss; коммит снаружи)."""
    now = now or _now()
    c = dict(boss.contributions or {})
    pid = str(player.id)
    rec = c.get(pid) or {"dmg": 0, "hits": 0, "name": player.first_name or pid}
    rec["dmg"] = int(rec.get("dmg", 0)) + dmg
    rec["hits"] = int(rec.get("hits", 0)) + 1
    rec["last"] = now.isoformat()
    c[pid] = rec
    boss.contributions = c
    boss.hp = max(0, boss.hp - dmg)


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
