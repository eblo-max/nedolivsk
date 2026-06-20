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

from datetime import datetime, timedelta, timezone

# ── Тайминги ─────────────────────────────────────────────────────────────────
GATHER_MINUTES = 20          # окно регистрации (сбор войска)
MARCH_SECONDS = 35           # визуальный марш (часть фазы battle, для карты)
BATTLE_SECONDS = 300         # авто-бой ≥ 5 мин (требование дизайна)
COOLDOWN_HOURS = 6           # пауза до следующего ивента
AUTO = False                 # авто-спавн по расписанию (старт — только вручную)

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
    """Порог орды из суммарной мощи всех таверн мира (снимок при спавне)."""
    return max(MIN_THRESHOLD, round(COVERAGE * max(0, total_world_might)))


# ── Тайминги/фазы ────────────────────────────────────────────────────────────
def gather_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(minutes=GATHER_MINUTES)


def resolve_at(gather_end: datetime) -> datetime:
    """Когда считать исход: конец сбора + марш + бой."""
    return _aware(gather_end) + timedelta(seconds=MARCH_SECONDS + BATTLE_SECONDS)


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


def make_record(player, tavern, pos) -> dict:
    """Запись бойца в реестр: имя, позиция таверны на карте, мощь дружины."""
    return {"name": player.first_name or str(player.id),
            "tx": round(pos[0], 4), "ty": round(pos[1], 4),
            "might": tavern_might(tavern)}


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


def settle(inv, rng=None) -> dict:
    """План исхода (раздача/штраф). Чистый — применяет снаружи, с капами/полами.
    Победа: каждому участнику золото (база + мощь×коэф) + репутация + хабар-ресурсы;
    ОДНОМУ случайному — редкий трофей (равный шанс). Провал: записавшиеся теряют
    немного золота и репутации. Возвращает
    {won, gold:{pid:Δ}, rep:{pid:Δ}, res:{pid:{res:qty}}, trophy:{pid,drop}|None}."""
    import random as _random
    rng = rng or _random
    won = is_won(inv)
    gold: dict[int, int] = {}
    rep: dict[int, int] = {}
    res: dict[int, dict] = {}
    trophy = None
    reg = inv.registered or {}
    for pid_s, r in reg.items():
        pid = int(pid_s)
        might = int((r or {}).get("might", 0))
        if won:
            gold[pid] = WIN_GOLD_BASE + round(might * WIN_GOLD_PER_MIGHT)
            rep[pid] = WIN_REP
            res[pid] = {k: rng.randint(lo, hi) for k, (lo, hi) in HAUL_RES.items()}
        else:
            gold[pid] = -LOSS_GOLD
            rep[pid] = -LOSS_REP
    if won and reg:
        lucky = rng.choice([int(p) for p in reg])          # равный шанс каждому
        trophy = {"pid": lucky, "drop": _roll_trophy(rng)}
    return {"won": won, "gold": gold, "rep": rep, "res": res, "trophy": trophy}
