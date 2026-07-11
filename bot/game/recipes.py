"""«Тайные рецепты» — детерминированное ЯДРО ИИ-блюд (без сети).

Дизайн-принцип: ИИ придумывает ФЛЕЙВОР (имя/лор) и ВЫБИРАЕТ эффекты, а ЧИСЛА
эффектов назначает КОД из бюджета — ровно как итемизация шмота (items.py). Так вкус
рождает модель, а баланс держит код: показ=действие и целостность экономики целы,
что бы ИИ ни навыдумывал.

Здесь нет ничего сетевого — только чистые функции: словарь съедобных ингредиентов
и их вкусовые теги, бюджет из ценности, `combo_hash`, кламп эффектов (единственный
источник чисел) и детерминированный ПРОЦЕДУРНЫЙ фолбэк. Фолбэк даёт полноценный
рецепт БЕЗ `ANTHROPIC_API_KEY` — игра работает всегда; ИИ (bot/game/ai_recipe.py)
лишь заменяет процедурные имя/лор/выбор-эффектов на свои, числа те же.

Шкала бюджета — «урон-эквивалент» боёвки: 1 очко = +1 урона. hp и уворот стоят
дешевле по конверсии рейда (raid.RAID_HP_TO_DMG=3, RAID_DODGE_TO_DMG=4) — потому
`EFFECT_COST[hp]=1/3`, `[dodge]=1/4`. Так метка и бой считаются из ОДНИХ чисел.
"""
from __future__ import annotations

import hashlib
import random

from bot.game import balance

# ── Ингредиенты: фиксированный СЪЕДОБНЫЙ словарь (не свободный ввод) ──────────
# Только съедобное сырьё/полуфабрикаты (без дерева/руды/камня/глины — это не еда).
# Свободного текста в ИИ не уходит → нет инъекций, конечное пространство комбо.
INGREDIENTS: tuple[str, ...] = (
    "grain", "hops", "water", "honey", "berries",
    "game", "herbs", "salt", "fish", "milk",
    "malt", "flour",
)
MIN_INGREDIENTS = 2
MAX_INGREDIENTS = 4

# Вкусовые теги ингредиента → смещают ВЫБОР эффектов (и у ИИ, и у фолбэка), чтобы
# «перец+сало» и «мёд+ягоды» звучали и работали по-разному. herbs в игре — 🌶️
# (острые травы), потому и spicy, и herbal.
INGREDIENT_TAGS: dict[str, tuple[str, ...]] = {
    "grain":   ("hearty",),
    "hops":    ("fermented", "bitter"),
    "water":   ("plain",),
    "honey":   ("sweet",),
    "berries": ("sweet", "tart"),
    "game":    ("fatty", "hearty"),
    "herbs":   ("spicy", "herbal"),
    "salt":    ("savory",),
    "fish":    ("hearty", "savory"),
    "milk":    ("fatty", "creamy"),
    "malt":    ("hearty", "fermented"),
    "flour":   ("hearty",),
}

# Тег → веса боевых эффектов (Ф0: только боевой словарь FLASK_EFFECTS). Ф1 расширит
# теги на эконом-эффекты (income/yield/…) — см. docs/ai_recipes.md §4.6.
TAG_EFFECTS: dict[str, dict[str, float]] = {
    "hearty":    {"hp": 1.0},
    "fatty":     {"hp": 1.0},
    "creamy":    {"hp": 0.6, "antidote": 0.4},
    "fermented": {"crit": 1.0},
    "bitter":    {"crit": 0.7, "dmg": 0.3},
    "sweet":     {"crit": 0.8, "hp": 0.2},
    "tart":      {"crit": 0.6, "dodge": 0.4},
    "spicy":     {"dmg": 1.0},
    "savory":    {"dmg": 0.7, "hp": 0.3},
    "herbal":    {"antidote": 0.6, "dodge": 0.4},
    "plain":     {"dmg": 0.5},
}

# ── Эффекты: белый список + стоимость 1 ед. в урон-эквиваленте ────────────────
# Боевой набор Ф0 = FLASK_EFFECTS. Стоимости выведены из конверсий рейда, чтобы
# бюджет == реальной силе в бою (см. raid.flask_mods).
EFFECT_COST: dict[str, float] = {
    "dmg": 1.0,        # +1 урона
    "hp": 1.0 / 3.0,   # +1 ❤ (в рейде hp//3 → урон)
    "dodge": 1.0 / 4.0,  # +1% уворота (dodge//4 → урон)
    "crit": 0.8,       # +1% крита (калибровка по wine/nalivka)
    "antidote": 4.0,   # бинарный, ситуативно ценный
}
ALLOWED_EFFECTS: tuple[str, ...] = ("dmg", "crit", "dodge", "hp", "antidote")
# Порядок = приоритет распределения и детерминированный тай-брейк по весам.
EFFECT_ORDER: tuple[str, ...] = ("dmg", "crit", "dodge", "hp", "antidote")
MAX_EFFECTS = 3        # 1..3 эффекта на рецепт («билды», см. §4.6.2)
# Мягкие потолки на одну величину — чтобы бюджет-тяжёлый в один стат рецепт не
# показывал абсурд («+60❤»). Излишек бюджета просто не тратится (рецепт ≤ бюджета).
EFFECT_MAX: dict[str, int] = {"dmg": 30, "hp": 48, "dodge": 45, "crit": 35}

# ── Бюджет из ценности ингредиентов (детерминированно) ───────────────────────
RECIPE_BUDGET_BASE = 3.0
RECIPE_BUDGET_K = 0.7
RECIPE_BUDGET_FLOOR = 4      # даже дешёвое комбо что-то даёт
RECIPE_BUDGET_CAP = 20       # потолок ≈ верх эксклюзива зодчих; имбы не будет

RECIPE_KEY_PREFIX = "tr_"    # ключ игрового рецепта (owns_recipe/варка)

# Ярусы по редкости (бюджетные полосы) — для UI-подсказки «какой силы блюдо выйдет».
RECIPE_TIERS: tuple[tuple[int, str], ...] = (
    (9, "Обычный"), (14, "Необычный"), (20, "Редкий"), (10 ** 9, "Экзотический"),
)


def budget_tier(budget: int) -> str:
    """Ярус по бюджету (для витрины). Совпадает с полосами docs/ai_recipes.md §4.6.4."""
    return next(name for cap, name in RECIPE_TIERS if budget <= cap)

# Затраты/выход эксперимента (Ф0: открытие = крафт; списывается из погреба).
EXPERIMENT_COST_EACH = 5     # сколько каждого выбранного ингредиента тратится
EXPERIMENT_OUTPUT = 3        # сколько порций блюда получаем


def price(key: str) -> float:
    """Ценность ингредиента (для бюджета). Все INGREDIENTS есть в RESOURCE_PRICE."""
    return float(balance.RESOURCE_PRICE.get(key, 0.0))


def valid_combo(ingredients: list[str]) -> bool:
    """2..4 РАЗНЫХ ингредиента, все из белого словаря (гейт на входе, анти-инъекция)."""
    uniq = set(ingredients)
    return (len(uniq) == len(ingredients)
            and MIN_INGREDIENTS <= len(uniq) <= MAX_INGREDIENTS
            and all(k in INGREDIENTS for k in uniq))


def combo_hash(ingredients: list[str]) -> str:
    """Детерминированный ключ комбинации: сорт+uniq → sha1. Порядок не важен."""
    canon = ",".join(sorted(set(ingredients)))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


def recipe_key(chash: str) -> str:
    """Игровой ключ рецепта из хэша (для tavern.products / owns_recipe)."""
    return RECIPE_KEY_PREFIX + chash[:12]


def recipe_budget(ingredients: list[str]) -> int:
    """Бюджет силы в урон-эквиваленте из суммарной ценности ингредиентов."""
    worth = sum(price(k) for k in set(ingredients))
    raw = RECIPE_BUDGET_BASE + worth * RECIPE_BUDGET_K
    return int(max(RECIPE_BUDGET_FLOOR, min(RECIPE_BUDGET_CAP, round(raw))))


def proposal_from_tags(ingredients: list[str]) -> dict[str, float]:
    """Веса эффектов из вкусовых тегов ингредиентов (процедурное «предложение»,
    аналог того, что предложит ИИ). Суммирует вклад тегов всех ингредиентов."""
    weights: dict[str, float] = {}
    for ing in set(ingredients):
        for tag in INGREDIENT_TAGS.get(ing, ()):  # noqa: SIM118
            for eff, w in TAG_EFFECTS.get(tag, {}).items():
                weights[eff] = weights.get(eff, 0.0) + w
    return weights


# ── In-memory кэш рецептов (seam показ=действие + имена для UI) ───────────────
# raid.flask_mods/flask_label и combat.flask_apply читают эффекты через resolver:
# сперва статический FLASK_EFFECTS, затем этот кэш. Прогревается из БД на старте
# (repo.all_recipes → set_recipe_cache) и пополняется на открытии (note_recipe).
# Значение: {"name","lore","effects"} — бою нужен effects, витринам — name/lore.
_RECIPE_CACHE: dict[str, dict] = {}


def _norm(rec) -> dict:
    """Привести запись (dict или ORM-объект) к {name,lore,reasoning,effects}."""
    g = (lambda k, d="": rec.get(k, d)) if isinstance(rec, dict) else (lambda k, d="": getattr(rec, k, d))
    return {"name": g("name", ""), "lore": g("lore", ""), "reasoning": g("reasoning", ""),
            "effects": dict(g("effects", {}) or {})}


def set_recipe_cache(records) -> None:
    """Заменить кэш целиком (тёплый старт из БД). records: итерабельные записи с
    полями key/name/lore/effects (dict или ORM Recipe)."""
    _RECIPE_CACHE.clear()
    for r in records or []:
        key = r["key"] if isinstance(r, dict) else r.key
        _RECIPE_CACHE[key] = _norm(r)


def note_recipe(rec: dict) -> None:
    """Добавить один рецепт в кэш (сразу после открытия — чтобы бой видел его)."""
    _RECIPE_CACHE[rec["key"]] = _norm(rec)


def effects_for_key(key: str) -> dict | None:
    """Эффекты рецепта по игровому ключу (или None, если не тайный рецепт)."""
    r = _RECIPE_CACHE.get(key)
    return r["effects"] if r else None


def meta_for_key(key: str) -> dict | None:
    """Полная запись рецепта из кэша ({name,lore,effects}) или None."""
    return _RECIPE_CACHE.get(key)


def name_for_key(key: str) -> str | None:
    r = _RECIPE_CACHE.get(key)
    return r["name"] if r else None


def is_recipe_key(key: str) -> bool:
    """Ключ принадлежит тайному рецепту (а не статическому благу)."""
    return isinstance(key, str) and key.startswith(RECIPE_KEY_PREFIX)


# ── Склад открытых блюд на таверне (tavern.recipes_stock; отдельно от products) ──
def stock_get(tavern, key: str) -> int:
    return int((getattr(tavern, "recipes_stock", None) or {}).get(key, 0))


def stock_add(tavern, key: str, n: int) -> None:
    """Прибавить порции блюда (переприсваивание dict — для JSONB)."""
    st = dict(getattr(tavern, "recipes_stock", None) or {})
    st[key] = max(0, st.get(key, 0) + int(n))
    tavern.recipes_stock = st


def stock_spend(tavern, key: str, n: int = 1) -> bool:
    """Списать порции блюда; False если не хватило (ничего не меняем)."""
    st = dict(getattr(tavern, "recipes_stock", None) or {})
    if st.get(key, 0) < n:
        return False
    st[key] = st[key] - int(n)
    tavern.recipes_stock = st
    return True


_LABEL_ORDER = ("dmg", "crit", "dodge", "hp", "antidote")
_LABEL_FMT = {
    "dmg": lambda v: f"+{v} урона",
    "crit": lambda v: f"+{v}% крита",
    "dodge": lambda v: f"+{v}% уворота",
    "hp": lambda v: f"+{v} ❤",
    "antidote": lambda v: "снимает яд",
}


def cellar_label(effects: dict) -> str:
    """Погреб-метка блюда (сырые эффекты, вне рейда). Для рейда — raid.flask_label
    (там hp/уворот идут в урон). Обе честны в своём контексте."""
    parts = [_LABEL_FMT[k](effects[k]) for k in _LABEL_ORDER
             if effects.get(k) and (k != "antidote" or effects[k])]
    return ", ".join(parts) or "—"


RECIPE_COOLDOWN_SEC = 60      # антиспам эксперимента (защита ИИ-бюджета)


def effect_points(effects: dict) -> float:
    """Суммарная стоимость эффектов в урон-эквиваленте (для инварианта ≤ бюджет)."""
    total = 0.0
    for k, v in effects.items():
        if k not in EFFECT_COST:
            continue
        if k == "antidote":
            total += EFFECT_COST["antidote"] if v else 0.0
        else:
            total += EFFECT_COST[k] * float(v)
    return total


def assign_effects(proposal: dict[str, float], budget: float) -> dict:
    """ЕДИНСТВЕННЫЙ источник чисел. ИИ/теги ПРЕДЛОЖИЛИ веса — КОД назначает величины:
    только белый список, ≤ MAX_EFFECTS эффектов, суммарная стоимость ≤ budget.

    Гарантии (проверяются тестами на случайных входах):
      • effect_points(результат) ≤ budget  (баланс не пробить);
      • ключи ⊆ ALLOWED_EFFECTS  (чужие эффекты отсеяны);
      • детерминизм при равных весах (тай-брейк по EFFECT_ORDER)."""
    budget = max(0.0, float(budget))
    weights = {k: float(v) for k, v in (proposal or {}).items()
               if k in EFFECT_COST and float(v) > 0}
    if not weights:                                   # ИИ ничего валидного не дал
        weights = {"dmg": 1.0}                        # безопасный дефолт — чистый урон
    ranked = sorted(weights, key=lambda k: (-weights[k], EFFECT_ORDER.index(k)))
    chosen = ranked[:MAX_EFFECTS]
    tw = sum(weights[k] for k in chosen)

    out: dict = {}
    spent = 0.0
    for k in chosen:                                  # 1-й проход: пропорц. долям
        cost = EFFECT_COST[k]
        share = budget * weights[k] / tw
        if k == "antidote":
            if share >= cost and budget - spent >= cost:
                out[k] = True
                spent += cost
            continue
        units = int(share // cost)
        units = min(units, int((budget - spent) // cost), EFFECT_MAX.get(k, 10**9))
        if units > 0:
            out[k] = units
            spent += units * cost

    numeric = [k for k in chosen if k != "antidote"]  # 2-й проход: добить остаток
    changed = True
    while changed:                                    # в топ-по-весу эффект, что влезет
        changed = False
        for k in numeric:
            cost = EFFECT_COST[k]
            if out.get(k, 0) >= EFFECT_MAX.get(k, 10**9):
                continue
            if budget - spent + 1e-9 >= cost:
                out[k] = out.get(k, 0) + 1
                spent += cost
                changed = True
                break
    return out


# ── Процедурный фолбэк: имя/лор без ИИ (детерминирован по combo_hash) ─────────
# Имя = «{Блюдо} {родительный/эпитет}» — грамматически чисто при любом роде блюда
# (без ведущего прилагательного, чтобы не ловить рассогласование рода).
_DISH = ("Похлёбка", "Взвар", "Солянка", "Зелье", "Настойка", "Квашня",
         "Бражка", "Потрошки", "Отвар", "Каша", "Варево", "Разносол")
_BYNAME = ("«У плахи»", "боярина Твердислава", "по-недоливски", "трактирщика",
           "старой корчмы", "деда Пафнутия", "с погоста", "заезжего гостя",
           "корчемная", "кабацкая", "по-стольному", "лихого люда")
_EFFECT_FLAVOR = {
    "dmg": "бьёт в голову — кулаки сами тянутся к драке",
    "crit": "точит глаз: удар ложится метче",
    "dodge": "ноги сами уводят от беды",
    "hp": "греет нутро и держит на ногах",
    "antidote": "гонит любую хворь и отраву",
}


def _rng(ingredients: list[str]) -> random.Random:
    """Детерминированный ГПСЧ, засеянный комбо — тот же combo → тот же фолбэк."""
    return random.Random(int(combo_hash(ingredients)[:12], 16))


def procedural_name(ingredients: list[str]) -> str:
    r = _rng(ingredients)
    return f"{r.choice(_DISH)} {r.choice(_BYNAME)}"


def procedural_lore(ingredients: list[str], effects: dict) -> str:
    r = _rng(ingredients)
    names = [balance.RESOURCE_NAMES.get(k, k) for k in sorted(set(ingredients))]
    top = max((k for k in effects if k in _EFFECT_FLAVOR),
              key=lambda k: effect_points({k: effects[k]}), default="dmg")
    joined = ", ".join(names[:-1]) + (" и " + names[-1] if len(names) > 1 else "")
    return f"Варево из {joined.lower()}. Говорят, {_EFFECT_FLAVOR.get(top, '')}."


def build_recipe(ingredients: list[str],
                 ai_name: str | None = None,
                 ai_lore: str | None = None,
                 ai_reasoning: str | None = None,
                 ai_proposal: dict[str, float] | None = None) -> dict:
    """Собрать рецепт: бюджет из ингредиентов + числа из клампа. Флейвор — от ИИ,
    если передан, иначе процедурный. Числа ВСЕГДА из assign_effects (не от ИИ).
    reasoning («Повар рассудил») — только от ИИ; без него пусто (фронт скрывает).

    Возвращает dict под таблицу recipes: name/lore/reasoning/effects/budget/combo_hash/key."""
    budget = recipe_budget(ingredients)
    proposal = ai_proposal if ai_proposal else proposal_from_tags(ingredients)
    effects = assign_effects(proposal, budget)
    name = (ai_name or "").strip() or procedural_name(ingredients)
    lore = (ai_lore or "").strip() or procedural_lore(ingredients, effects)
    chash = combo_hash(ingredients)
    return {
        "combo_hash": chash,
        "key": recipe_key(chash),
        "name": name,
        "lore": lore,
        "reasoning": (ai_reasoning or "").strip(),
        "effects": effects,
        "budget": budget,
        "ingredients": sorted(set(ingredients)),
    }
