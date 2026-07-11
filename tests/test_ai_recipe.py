"""ИИ-слой «Тайных рецептов» (bot/game/ai_recipe.py) — БЕЗ реальных вызовов API.

Мокаем клиента Claude: проверяем парсинг ответа в (name, lore, proposal), отсев
чужих эффектов, модерацию текста, и что ЛЮБОЙ сбой (нет ключа / отказ / исключение)
→ None (вызывающий уходит в детерминированный процедурный фолбэк — игра не падает).
"""
import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import ai_recipe  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Resp:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed_output = parsed
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    async def parse(self, **kw):
        if self._exc:
            raise self._exc
        return self._resp


class _Client:
    def __init__(self, resp=None, exc=None):
        self.messages = _Messages(resp, exc)


def _patch(monkeypatch, client):
    monkeypatch.setattr(ai_recipe, "available", lambda: True)
    monkeypatch.setattr(ai_recipe, "_client", client)


def test_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(ai_recipe.settings, "anthropic_api_key", "")
    assert ai_recipe.available() is False
    assert _run(ai_recipe.invent(["game", "herbs"], 10)) is None   # нет ключа → фолбэк


def test_invent_parses_and_filters_effects(monkeypatch):
    parsed = ai_recipe.AIRecipe(
        name="Огневая солянка «У плахи»",
        lore="Наперчено так, что палач слезу пустил.",
        effects={"dmg": 4, "crit": 2, "lifesteal": 9, "gold": 5},   # с чужими ключами
    )
    _patch(monkeypatch, _Client(resp=_Resp(parsed)))
    got = _run(ai_recipe.invent(["game", "herbs"], 11))
    assert got is not None
    name, lore, proposal = got
    assert name == "Огневая солянка «У плахи»" and lore.startswith("Наперчено")
    assert set(proposal) <= set(ai_recipe.recipes.EFFECT_COST)      # чужие отсеяны
    assert "lifesteal" not in proposal and "gold" not in proposal


def test_refusal_falls_back(monkeypatch):
    parsed = ai_recipe.AIRecipe(name="x", lore="y", effects={"dmg": 1})
    _patch(monkeypatch, _Client(resp=_Resp(parsed, stop_reason="refusal")))
    assert _run(ai_recipe.invent(["game", "herbs"], 10)) is None    # отказ → фолбэк


def test_api_exception_falls_back(monkeypatch):
    _patch(monkeypatch, _Client(exc=RuntimeError("network down")))
    assert _run(ai_recipe.invent(["game", "herbs"], 10)) is None    # исключение → фолбэк


def test_text_moderation_truncates_and_strips(monkeypatch):
    parsed = ai_recipe.AIRecipe(
        name="  Очень\n\tдлинное  " + "щи " * 60,                   # мусорные пробелы + длина
        lore="l" * 500,
        effects={"hp": 1},
    )
    _patch(monkeypatch, _Client(resp=_Resp(parsed)))
    name, lore, _ = _run(ai_recipe.invent(["game", "milk"], 8))
    assert len(name) <= ai_recipe.NAME_MAX and "\n" not in name and "\t" not in name
    assert len(lore) <= ai_recipe.LORE_MAX


def test_end_to_end_build_uses_ai_flavor_but_code_numbers(monkeypatch):
    """Полный путь: invent → recipes.build_recipe. Имя/лор от ИИ, числа из клампа."""
    from bot.game import recipes
    parsed = ai_recipe.AIRecipe(name="Царское жаркое", lore="Пир на весь Недоливск.",
                                effects={"dmg": 99, "crit": 99})   # ИИ просит имбу
    _patch(monkeypatch, _Client(resp=_Resp(parsed)))
    ing = ["game", "herbs", "honey"]
    ai = _run(ai_recipe.invent(ing, recipes.recipe_budget(ing)))
    name, lore, proposal = ai
    rec = recipes.build_recipe(ing, ai_name=name, ai_lore=lore, ai_proposal=proposal)
    assert rec["name"] == "Царское жаркое"                          # флейвор — ИИ
    assert recipes.effect_points(rec["effects"]) <= rec["budget"] + 1e-6  # но не имба
