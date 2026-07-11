"""«Тайные рецепты» — ядро (bot/game/recipes.py) БЕЗ сети.

Доказываем главный инвариант баланса: что бы ИИ ни предложил, КОД назначает числа
и НИКОГДА не превышает бюджет; проходят только эффекты из белого списка. Плюс
детерминизм комбо и валидность процедурного фолбэка (работает без ANTHROPIC_API_KEY).
"""
import itertools
import os
import random

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import recipes  # noqa: E402
from bot.game import balance  # noqa: E402


# ── Бюджет ───────────────────────────────────────────────────────────────────
def test_all_ingredients_priced_and_edible():
    """Каждый ингредиент имеет ценность (иначе бюджет = 0) и не строймат."""
    for k in recipes.INGREDIENTS:
        assert recipes.price(k) > 0, k
        assert k in balance.RESOURCE_PRICE, k
    assert not ({"wood", "ore", "clay", "stone"} & set(recipes.INGREDIENTS))


def test_budget_bounded_and_monotone_by_worth():
    lo = recipes.recipe_budget(["water", "grain"])          # дешёвое комбо
    hi = recipes.recipe_budget(["game", "honey", "herbs", "salt"])  # дорогое
    assert recipes.RECIPE_BUDGET_FLOOR <= lo <= hi <= recipes.RECIPE_BUDGET_CAP
    # порядок ингредиентов и дубли не влияют на бюджет
    assert recipes.recipe_budget(["game", "grain"]) == recipes.recipe_budget(["grain", "game"])


def test_budget_never_exceeds_cap_on_any_combo():
    for r in range(recipes.MIN_INGREDIENTS, recipes.MAX_INGREDIENTS + 1):
        for combo in itertools.combinations(recipes.INGREDIENTS, r):
            b = recipes.recipe_budget(list(combo))
            assert recipes.RECIPE_BUDGET_FLOOR <= b <= recipes.RECIPE_BUDGET_CAP, combo


# ── Кламп: главный инвариант баланса ─────────────────────────────────────────
def test_assign_never_exceeds_budget_property():
    """Свойство на случайных «предложениях ИИ»: стоимость назначенного ≤ бюджета."""
    rng = random.Random(42)
    keys = list(recipes.EFFECT_COST) + ["garbage", "hp", "dmg"]  # с мусором и повторами
    for _ in range(3000):
        budget = rng.uniform(0, recipes.RECIPE_BUDGET_CAP)
        proposal = {k: rng.uniform(-2, 5) for k in rng.sample(keys, rng.randint(0, len(keys)))}
        out = recipes.assign_effects(proposal, budget)
        assert recipes.effect_points(out) <= budget + 1e-6, (budget, proposal, out)
        assert set(out) <= set(recipes.ALLOWED_EFFECTS)      # только белый список
        assert len(out) <= recipes.MAX_EFFECTS


def test_assign_filters_foreign_effects():
    out = recipes.assign_effects({"lifesteal": 99, "gold": 99, "dmg": 1}, 10)
    assert set(out) <= {"dmg"}                               # чужие ключи отсеяны
    assert "lifesteal" not in out and "gold" not in out


def test_assign_empty_proposal_defaults_to_damage():
    out = recipes.assign_effects({}, 9)
    assert out.get("dmg", 0) > 0 and set(out) == {"dmg"}     # безопасный дефолт


def test_assign_uses_most_of_budget():
    """Добивка остатка: рецепт не должен «сливать» половину бюджета впустую."""
    out = recipes.assign_effects({"dmg": 1.0}, 12)
    assert recipes.effect_points(out) >= 12 - 1.0            # почти весь бюджет в дело


def test_assign_deterministic_on_equal_weights():
    a = recipes.assign_effects({"dmg": 1, "crit": 1, "hp": 1}, 10)
    b = recipes.assign_effects({"crit": 1, "hp": 1, "dmg": 1}, 10)
    assert a == b                                            # порядок ключей не важен


def test_assign_respects_soft_caps():
    out = recipes.assign_effects({"hp": 1.0}, recipes.RECIPE_BUDGET_CAP)
    assert out.get("hp", 0) <= recipes.EFFECT_MAX["hp"]      # без абсурдного «+60❤»


def test_antidote_is_binary_and_costs_budget():
    rich = recipes.assign_effects({"antidote": 1.0}, 10)
    assert rich.get("antidote") is True
    poor = recipes.assign_effects({"antidote": 1.0}, 2)      # бюджета не хватает
    assert "antidote" not in poor


# ── Детерминизм / хэш / ключ ─────────────────────────────────────────────────
def test_combo_hash_order_and_dupes_invariant():
    a = recipes.combo_hash(["game", "honey", "herbs"])
    b = recipes.combo_hash(["herbs", "game", "honey", "game"])  # порядок+дубль
    assert a == b
    assert recipes.combo_hash(["game", "honey"]) != a          # другое комбо — другой хэш


def test_recipe_key_stable_and_prefixed():
    k = recipes.recipe_key(recipes.combo_hash(["game", "honey"]))
    assert k.startswith(recipes.RECIPE_KEY_PREFIX) and len(k) > len(recipes.RECIPE_KEY_PREFIX)


# ── Валидация входа (анти-инъекция) ──────────────────────────────────────────
def test_valid_combo_gate():
    assert recipes.valid_combo(["game", "honey"])
    assert recipes.valid_combo(["game", "honey", "herbs", "salt"])
    assert not recipes.valid_combo(["game"])                     # мало
    assert not recipes.valid_combo(["game", "honey", "herbs", "salt", "milk"])  # много
    assert not recipes.valid_combo(["game", "game"])             # дубли
    assert not recipes.valid_combo(["game", "wood"])             # не съедобное
    assert not recipes.valid_combo(["game", "'; DROP TABLE"])    # мусор/инъекция


# ── Процедурный фолбэк (без ИИ) ──────────────────────────────────────────────
def test_procedural_recipe_valid_and_deterministic():
    ing = ["game", "herbs", "honey"]
    a = recipes.build_recipe(ing)
    b = recipes.build_recipe(list(reversed(ing)))
    assert a == b                                               # то же комбо → тот же рецепт
    assert a["name"] and a["lore"]                             # флейвор есть
    assert a["effects"] and set(a["effects"]) <= set(recipes.ALLOWED_EFFECTS)
    assert recipes.effect_points(a["effects"]) <= a["budget"] + 1e-6
    assert a["key"] == recipes.recipe_key(a["combo_hash"])


def test_build_recipe_prefers_ai_flavor_keeps_code_numbers():
    ing = ["game", "herbs"]
    r = recipes.build_recipe(ing, ai_name="Похмельный борщ боярина",
                             ai_lore="Секрет корчмы.", ai_proposal={"crit": 5})
    assert r["name"] == "Похмельный борщ боярина"              # флейвор — от ИИ
    assert r["lore"] == "Секрет корчмы."
    # но числа — из клампа по бюджету, не «5 крита» как попросил ИИ
    assert recipes.effect_points(r["effects"]) <= r["budget"] + 1e-6


def test_full_matrix_every_combo_builds_valid_recipe():
    """Каждая допустимая комбинация даёт валидный сбалансированный рецепт (фолбэк)."""
    seen_keys = set()
    for r in range(recipes.MIN_INGREDIENTS, recipes.MAX_INGREDIENTS + 1):
        for combo in itertools.combinations(recipes.INGREDIENTS, r):
            rec = recipes.build_recipe(list(combo))
            assert rec["effects"], combo
            assert recipes.effect_points(rec["effects"]) <= rec["budget"] + 1e-6, combo
            assert set(rec["effects"]) <= set(recipes.ALLOWED_EFFECTS), combo
            seen_keys.add(rec["key"])
    # ключи уникальны на комбо (нет коллизий префикса на всём пространстве Ф0)
    total = sum(1 for r in range(recipes.MIN_INGREDIENTS, recipes.MAX_INGREDIENTS + 1)
                for _ in itertools.combinations(recipes.INGREDIENTS, r))
    assert len(seen_keys) == total


def test_luck_tier_empty_ingredients_is_normal():
    """Регресс: старые рецепты без сохранённого состава НЕ должны ложно светить
    «✨ Удачная партия» (иначе база=recipe_budget([])=4 → любой рецепт «lucky»)."""
    assert recipes.luck_tier(15, []) == "normal"
    assert recipes.luck_tier(20, []) == "normal"


def test_luck_tier_reflects_roll_vs_base():
    ing = ["game", "herbs"]
    base = recipes.recipe_budget(ing)
    assert recipes.luck_tier(round(base * 1.15), ing) == "lucky"    # ролл заметно выше базы
    assert recipes.luck_tier(round(base * 0.85), ing) == "lean"     # заметно ниже
    assert recipes.luck_tier(base, ing) == "normal"
