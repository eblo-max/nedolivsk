"""«Грамота новосёла» — мягкий онбординг, пока таверна <= NEWBIE_MAX_LEVEL.

Три механики против раннего оттока:
  1. Стартовый сундук — разовый щедрый набор при создании таверны.
  2. Поблажки — дешевле работники, больше добыча, быстрее ходки (авто, до ур.3).
  3. Задания-вехи — чеклист первых шагов с наградами (видимый прогресс).

Прогресс хранится во флагах player.story: '<key>' — веха выполнена,
'<key>_c' — награда забрана, 'nb_chest' — сундук выдан.
"""

from datetime import datetime, timedelta, timezone

from bot.game import inventory, story_state

NEWBIE_MAX_LEVEL = 2          # «новичок», пока уровень таверны <= этого
NEWBIE_GRACE_DAYS = 7        # поблажки — только первые N дней (анти-турель на ур.2)

# Поблажки (действуют, пока новичок И в грейс-окне)
NEWBIE_PAY_MULT = 0.5        # −50% платы работникам
NEWBIE_YIELD_MULT = 1.25     # +25% добычи бригад
NEWBIE_SPEED_MULT = 0.8      # −20% времени ходки

# Стартовый сундук — разово при создании таверны
STARTER_CHEST = {"gold": 200, "wood": 40, "grain": 40, "hops": 20}

# Задания: (флаг-выполнено, заголовок, награда). nb_build/nb_lvl2 — по состоянию.
TASKS = [
    ("nb_brigade", "Отправь первую бригаду за добром", {"gold": 50}),
    ("nb_build", "Построй первую пристройку", {"gold": 150, "wood": 30}),
    ("nb_craft", "Произведи первый товар", {"gold": 100}),
    ("nb_sale", "Продай товар — купцу или гостям", {"gold": 100}),
    ("nb_lvl2", "Дорасти до уровня 2",
     {"gold": 300, "wood": 80, "grain": 60, "hops": 40}),
]
_KEYS = {t[0] for t in TASKS}


def _level(tavern) -> int:
    return tavern.level if tavern else 1


def is_newbie(tavern) -> bool:
    """Новичок по уровню — для грамоты-чеклиста и сундука (разовые, не фармятся)."""
    return _level(tavern) <= NEWBIE_MAX_LEVEL


def _within_grace(player) -> bool:
    """В грейс-окне онбординга (первые NEWBIE_GRACE_DAYS дней с регистрации)."""
    created = getattr(player, "created_at", None)
    if created is None:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created < timedelta(days=NEWBIE_GRACE_DAYS)


def perks_active(player) -> bool:
    """Поблажки — пока новичок ПО УРОВНЮ и в грейс-окне (анти-абуз «турель»)."""
    return is_newbie(player.tavern) and _within_grace(player)


# ── Поблажки (на вход — игрок: нужен возраст аккаунта) ──────────────────────
def pay_mult(player) -> float:
    return NEWBIE_PAY_MULT if perks_active(player) else 1.0


def yield_mult(player) -> float:
    return NEWBIE_YIELD_MULT if perks_active(player) else 1.0


def speed_mult(player) -> float:
    return NEWBIE_SPEED_MULT if perks_active(player) else 1.0


# ── Задания ────────────────────────────────────────────────────────────────
def mark(player, key: str) -> None:
    """Отметить веху выполненной (вызывать в момент действия игрока)."""
    if key in _KEYS:
        story_state.add_flag(player, key)


def _done(player, tavern, key: str) -> bool:
    if key == "nb_lvl2":
        return _level(tavern) >= 2
    if key == "nb_build":
        return bool(tavern and tavern.buildings)
    return story_state.has_flag(player, key)


def _claimed(player, key: str) -> bool:
    return story_state.has_flag(player, key + "_c")


def states(player, tavern) -> list[tuple]:
    """[(key, label, reward, done, claimed)] по всем заданиям."""
    return [
        (key, label, reward, _done(player, tavern, key), _claimed(player, key))
        for key, label, reward in TASKS
    ]


def claimable(player, tavern) -> bool:
    return any(d and not c for _, _, _, d, c in states(player, tavern))


def visible(player, tavern) -> bool:
    """Грамота на экране только пока новичок (до ур.2 включительно) — чтобы
    ветераны не получали ретро-награды за вычисляемые вехи."""
    return is_newbie(tavern)


def claim_all(player, tavern) -> dict:
    """Забрать все готовые награды. Возвращает суммарно начисленное {res: amount}."""
    total: dict[str, int] = {}
    for key, _label, reward, done, claimed in states(player, tavern):
        if not (done and not claimed):
            continue
        for r, amt in reward.items():
            if r == "gold":
                player.gold += amt
            else:
                inventory.add(player, r, amt)
            total[r] = total.get(r, 0) + amt
        story_state.add_flag(player, key + "_c")
    return total


def grant_chest(player) -> dict | None:
    """Стартовый сундук — разово. None, если уже выдавался."""
    if story_state.has_flag(player, "nb_chest"):
        return None
    for r, amt in STARTER_CHEST.items():
        if r == "gold":
            player.gold += amt
        else:
            inventory.add(player, r, amt)
    story_state.add_flag(player, "nb_chest")
    return dict(STARTER_CHEST)
