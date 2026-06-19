"""Ночная ходка — соло push-your-luck вылазка трактирщика по ночному тракту.

Чистая игровая логика (без БД/Telegram): машина забега + математика риска.
Ходка идёт этапами; на каждом — развилка из 2 испытаний (играй от своих статов).
Резолв даёт добычу в котомку, но может «обчистить» (БЮСТ = потеря незабанканного).
Перекрёсток: ⬇️ глубже (опаснее и жирнее) или 🏠 свернуть в таверну (банк).

Кривая риска: p(этап) = P0 − DECAY·(этап−1) + статы − штраф_ситуации (см.
balance.NIGHTRUN_*). Прокачка двигает порог рациональной остановки глубже —
скилл, а не казино (баланс EV/бюста — scripts/sim_nightrun.py).

Движок детерминирован по seed и принимает ГОТОВЫЙ бросок кубика (sendDice) /
решение игрока — Telegram-слой, кулдаун и фракционный хук живут в хендлерах.
"""

import random
from datetime import datetime, timezone

from bot.game import balance, combat, inventory

UTC = timezone.utc
BASE_HP = balance.BASE_HP

# Типы испытаний: id -> (эмодзи, имя, рискованный?). Развилка предлагает 2 из них.
KINDS = {
    "fight":  ("⚔️", "Засада", True),    # сила/броня; даже победа стоит здоровья
    "gamble": ("🎲", "Лихо", True),      # бросок кубика; высокая дисперсия
    "sneak":  ("🌒", "Тишком", True),    # удача; проскользнуть мимо беды
    "meet":   ("🗣", "Встреча", False),  # НПС-выбор: добыча + сдвиг фракций, без бюста
    "rest":   ("🔥", "Привал", False),   # безопасно: лечит, добычи нет
    "find":   ("💰", "Схрон", False),    # безопасно: малая добыча, без бюста
}

RISKY = [k for k, v in KINDS.items() if v[2]]

# Встречи на тракте (нода «meet»): живой НПС + выбор, двигающий силу фракций
# города (хук в общий мир). Опция: (id, кнопка, множитель добычи, [(фракция, знак)]).
MEET_ENCOUNTERS = {
    "smuggler": {
        "npc": "🥷 Контрабандист Тихушкин",
        "scene": "из темноты шипят: «Эй, хозяин… товар не нужен? Дёшево, мимо застав».",
        "options": [
            ("buy",  "🤝 Взять товар", 1.6, [("thieves", +1)]),
            ("turn", "🛡 Сдать страже", 1.0, [("watch", +1), ("thieves", -1)]),
        ],
    },
    "taxman": {
        "npc": "👑 Сборщик податей",
        "scene": "верхом, при бумагах: «Ночной промысел? С него — пошлина короне».",
        "options": [
            ("pay",  "💰 Заплатить пошлину", 0.6, [("crown", +1)]),
            ("slip", "🌒 Ускользнуть в темень", 1.2, [("crown", -1)]),
        ],
    },
    "monk": {
        "npc": "⛪ Брат Постник",
        "scene": "тощий монах с факелом грозит геенной за ночные шатания.",
        "options": [
            ("alms",   "🙏 Подать на храм", 0.7, [("church", +1)]),
            ("ignore", "🍺 Отмахнуться", 1.1, [("church", -1)]),
        ],
    },
}


def leg_value(leg: int) -> float:
    """Ценность добычи этапа в золото-эквиваленте (растёт с глубиной)."""
    return balance.NIGHTRUN_REWARD0 * (balance.NIGHTRUN_REWARD_GROWTH ** (leg - 1))


def success_p(run: dict, player, kind: str) -> float:
    """Шанс пройти испытание: база падает с этапом, статы и тип поднимают.
    Засада любит броню, Тишком — удачу, Лихо рискованнее (но видит кубик)."""
    s = combat.player_stats(player)
    armor, luck = s.get("armor", 0), s.get("luck", 0)
    pen = balance.NIGHTRUN_SITUATION_PENALTY.get(run.get("situation"), 0.0)
    p = (balance.NIGHTRUN_P0 - balance.NIGHTRUN_P_DECAY * (run["leg"] - 1)
         + armor * balance.NIGHTRUN_ARMOR_W + luck * balance.NIGHTRUN_LUCK_W - pen)
    if kind == "fight":
        p += armor * balance.NIGHTRUN_ARMOR_W + 0.03      # броня решает в драке
    elif kind == "sneak":
        p += luck * balance.NIGHTRUN_LUCK_W               # удача — проскользнуть
    elif kind == "gamble":
        p -= 0.05                                         # азарт рискованнее
    return max(balance.NIGHTRUN_P_FLOOR, min(balance.NIGHTRUN_P_CAP, p))


def _bundle(value: float, region: str, situation: str | None, rng: random.Random) -> dict:
    """Добыча на value золото-эквивалента: доля золотом + 1–2 ресурса региона."""
    value *= balance.NIGHTRUN_SITUATION_LOOT.get(situation, 1.0)
    out: dict = {}
    gold = int(value * balance.NIGHTRUN_GOLD_SHARE)
    if gold:
        out["gold"] = gold
    res_val = value - gold
    pool = list(balance.REGION_BONUS.get(region, ("wood", "grain"))) or ["wood"]
    rng.shuffle(pool)
    picks = pool[:2]
    for r in picks:
        qty = max(1, round((res_val / len(picks)) / balance.RESOURCE_PRICE.get(r, 3.0)))
        out[r] = out.get(r, 0) + qty
    return out


def _merge(satchel: dict, loot: dict) -> None:
    for k, v in loot.items():
        satchel[k] = satchel.get(k, 0) + v


def satchel_value(satchel: dict) -> int:
    """Золото-эквивалент содержимого котомки (для отображения/симулятора)."""
    return int(sum(v if k == "gold" else v * balance.RESOURCE_PRICE.get(k, 3.0)
                   for k, v in (satchel or {}).items()))


def start(player, region: str, situation: str | None = None,
          seed: int | None = None, now: datetime | None = None) -> dict:
    """Завести ходку: этап 1, полное здоровье, пустая котомка."""
    return {
        "leg": 1, "state": "fork", "hp": BASE_HP, "satchel": {},
        "region": region or "", "situation": situation,
        "seed": seed if seed is not None else random.randint(1, 10**9),
        "started_at": (now or datetime.now(UTC)).isoformat(),
    }


def fork(run: dict) -> tuple[str, str]:
    """Две развилки текущего этапа (детерминировано по seed+этап). Ранний этап
    может предложить безопасный «Схрон», глубокий — спасительный «Привал»."""
    rng = random.Random(run["seed"] * 1000 + run["leg"])
    pool = list(RISKY)
    if run["leg"] <= 2:
        pool.append("find")
    if 2 <= run["leg"] <= 4:
        pool.append("meet")           # встречи на тракте — в середине пути
    if run["leg"] >= 4:
        pool.append("rest")
    a = rng.choice(pool)
    b = rng.choice([k for k in pool if k != a])
    return (a, b)


def can_push(run: dict) -> bool:
    """Есть ли куда углубляться (последний этап выводит к рассвету — только банк)."""
    return run["leg"] < balance.NIGHTRUN_LEGS


def attempt(run: dict, player, kind: str, rng: random.Random | None = None,
            roll: int | None = None) -> dict:
    """Резолв выбранного испытания. Мутирует run (котомка/HP/состояние).
    Для «Лихо» roll — бросок кубика 1–6 (из sendDice; в тестах задаём явно).
    Возвращает исход для тоста: {kind, busted, loot, hp_cost, healed, roll, ...}."""
    rng = rng or random.Random()
    leg = run["leg"]
    val = leg_value(leg)
    out = {"kind": kind, "busted": False, "loot": {}, "hp_cost": 0,
           "healed": 0, "roll": roll}

    if kind == "meet":                                   # НПС-выбор на под-экране
        run["meet"] = _pick_meet(run)
        run["state"] = "meet"
        out["encounter"] = run["meet"]
        return out

    if kind == "rest":                                   # безопасно: лечит
        heal = max(0, min(balance.NIGHTRUN_REST_HEAL, BASE_HP - run["hp"]))
        run["hp"] += heal
        out["healed"] = heal
        run["state"] = "crossroad"
        return out

    if kind == "find":                                   # безопасно: малая добыча
        loot = _bundle(val * 0.6, run["region"], run["situation"], rng)
        _merge(run["satchel"], loot)
        out["loot"] = loot
        run["state"] = "crossroad"
        return out

    if kind == "gamble":                                 # честный кубик 1–6
        d = 1 - success_p(run, player, "gamble")
        faces = max(1, min(4, round(6 * d)))             # проигрышных граней
        roll = rng.randint(1, 6) if roll is None else roll
        out["roll"] = roll
        out["lose_faces"] = faces
        if roll <= faces:                                # БЮСТ
            return _bust(run, out)
        mult = 1.0 + (roll - faces) * 0.35               # чем выше бросок — тем куш
        loot = _bundle(val * mult, run["region"], run["situation"], rng)
        _merge(run["satchel"], loot)
        out["loot"] = loot
        run["state"] = "crossroad"
        return out

    # fight / sneak — вероятностный исход
    if rng.random() > success_p(run, player, kind):      # провал = одолели/попался
        return _bust(run, out)
    loot = _bundle(val, run["region"], run["situation"], rng)
    if kind == "fight":                                  # победа стоит здоровья
        lo, hi = balance.NIGHTRUN_FIGHT_HP
        cost = rng.randint(lo, hi) + leg
        run["hp"] -= cost
        out["hp_cost"] = cost
        if run["hp"] <= 0:                               # победил, но рухнул
            out["collapsed"] = True
            return _bust(run, out)
    _merge(run["satchel"], loot)
    out["loot"] = loot
    run["state"] = "crossroad"
    return out


def _bust(run: dict, out: dict) -> dict:
    """Провал: теряешь незабанканную котомку, ходка кончена."""
    out["busted"] = True
    out["lost"] = dict(run.get("satchel") or {})
    run["satchel"] = {}
    run["state"] = "busted"
    return out


def push(run: dict) -> None:
    """Углубиться: следующий этап, новая развилка (опаснее и жирнее)."""
    if can_push(run):
        run["leg"] += 1
        run["state"] = "fork"


def bank(run: dict, player) -> dict:
    """Свернуть в таверну: вся котомка — в инвентарь/золото. Возвращает добычу."""
    sat = dict(run.get("satchel") or {})
    for k, v in sat.items():
        if k == "gold":
            player.gold += v
        else:
            inventory.add(player, k, v)
    run["banked"] = sat
    run["satchel"] = {}
    run["state"] = "done"
    return sat


def _pick_meet(run: dict) -> str:
    """Детерминированный выбор встречи на этапе (по seed)."""
    rng = random.Random(run["seed"] * 1000 + run["leg"] + 777)
    return rng.choice(list(MEET_ENCOUNTERS))


def meet_options(run: dict) -> list:
    """Опции текущей встречи: [(id, кнопка, множитель, [(фракция, знак)]), ...]."""
    return MEET_ENCOUNTERS[run["meet"]]["options"]


def meet_resolve(run: dict, player, opt_id: str, rng: random.Random | None = None) -> dict:
    """Применить выбор во встрече: добыча + ИНТЕНТ сдвига фракций (его применяет
    хендлер к городу — движок чист). Переводит забег на перекрёсток."""
    rng = rng or random.Random()
    enc = MEET_ENCOUNTERS[run["meet"]]
    opt = next((o for o in enc["options"] if o[0] == opt_id), enc["options"][0])
    _id, _label, mult, facs = opt
    loot = _bundle(leg_value(run["leg"]) * mult, run["region"], run["situation"], rng)
    _merge(run["satchel"], loot)
    run.pop("meet", None)
    run["state"] = "crossroad"
    factions = [(f, sign * balance.NIGHTRUN_FACTION_NUDGE) for f, sign in facs]
    return {"kind": "meet", "busted": False, "loot": loot, "factions": factions,
            "opt": opt_id, "npc": enc["npc"]}


def is_active(run: dict | None) -> bool:
    """Есть ли незавершённый забег (ждёт решения игрока)."""
    return bool(run) and run.get("state") in ("fork", "crossroad", "meet")


def cooldown_left(player, now: datetime | None = None) -> int:
    """Секунд до следующей ходки (0 — можно идти). От player.night_run_at."""
    at = getattr(player, "night_run_at", None)
    if at is None:
        return 0
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    left = balance.NIGHTRUN_COOLDOWN_H * 3600 - ((now or datetime.now(UTC)) - at).total_seconds()
    return max(0, int(left))
