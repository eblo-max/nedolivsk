"""Интеграционный тест эндпоинта /api/recipe/experiment БЕЗ реальной БД.

Гоняем НАСТОЯЩИЙ хендлер (_api_recipe_experiment) с фейками БД/авторизации/ИИ, но
РЕАЛЬНЫМИ touch_seen / inventory / artel_shop / складом рецептов. Именно это поймало
бы прод-баг `touch_seen(p)` вместо `await touch_seen(s, uid)` (кривой вызов упал бы
здесь TypeError'ом, а не у игрока). Снапшот-роут-тест ловит пропажу роута, AST-гард —
неопределённые имена; а это — что хендлер реально ОТРАБАТЫВАЕТ от начала до конца.
"""
import asyncio
import json
import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.webapi import recipes as wr  # noqa: E402
from bot.game import recipes as core  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):     # touch_seen пишет last_seen_at/nudge_tier
        return None

    async def commit(self):
        pass


def _player(**over):
    t = NS(products={}, recipes_stock={})
    p = NS(tavern=t, recipe_at=None, gold=1000,
           inventory={k: 100 for k in core.INGREDIENTS}, story={}, id=7, first_name="Тест")
    for k, v in over.items():
        setattr(p, k, v)
    return p


def _wire(monkeypatch, player, *, existing=None, invent=None, ingredients=("game", "herbs")):
    """Подменяем ТОЛЬКО внешние границы (БД/авторизация/ИИ). touch_seen/inventory/
    artel_shop/склад — настоящие."""
    async def fake_auth(_req):
        return player.id, {"ingredients": list(ingredients)}

    async def fake_get_player(_s, _uid, for_update=False):
        return player

    async def fake_get_recipe_by_hash(_s, _h, lock=False):
        return existing

    async def fake_upsert(_s, data, discoverer_id):
        row = {**data, "ingredients": ",".join(data.get("ingredients", []))}  # как в БД (String)
        return NS(**row, discoverer_id=discoverer_id)    # канонная «строка» из data

    async def fake_invent(_ings, _budget):
        return invent                                    # None → процедурный фолбэк

    monkeypatch.setattr(wr, "_auth", fake_auth)
    monkeypatch.setattr(wr, "session_factory", lambda: _FakeSession())
    monkeypatch.setattr(wr.repo, "get_player", fake_get_player)
    monkeypatch.setattr(wr.repo, "get_recipe_by_hash", fake_get_recipe_by_hash)
    monkeypatch.setattr(wr.repo, "upsert_recipe", fake_upsert)
    monkeypatch.setattr(wr.repo, "add_log", lambda *a, **k: None)
    monkeypatch.setattr(wr.ai_recipe, "invent", fake_invent)


def _body(resp):
    return json.loads(resp.body)


def test_experiment_happy_path_procedural(monkeypatch):
    """Полный проход хендлера: открытие блюда, списание, склад, владение. (Ловит
    именно класс бага touch_seen — реальный touch_seen тут вызывается по-настоящему.)"""
    p = _player()
    _wire(monkeypatch, p, existing=None, invent=None)
    resp = _run(wr._api_recipe_experiment(object()))
    b = _body(resp)
    assert b["ok"] is True
    assert b["recipe"]["key"].startswith(core.RECIPE_KEY_PREFIX)
    assert b["new_to_world"] is True and b["first_time"] is True
    # ингредиенты списаны (по 5 каждого из 100)
    assert p.inventory["game"] == 95 and p.inventory["herbs"] == 95
    # порции блюда в склад, ключ во владение (кулинарная книга)
    key = b["recipe"]["key"]
    assert core.stock_get(p.tavern, key) == core.EXPERIMENT_OUTPUT
    assert key in p.story.get("artel", {}).get("recipes", [])
    assert p.recipe_at is not None                       # кулдаун поставлен


def test_experiment_threads_ai_reasoning(monkeypatch):
    """Флейвор ИИ (имя/лор/reasoning) доходит до карточки; числа — от кода."""
    p = _player()
    ai = ("Дичина боярская", "Сытно и лихо.", "Дичь да травы — сила и лёгкость.",
          {"dmg": 3.0, "hp": 2.0})
    _wire(monkeypatch, p, existing=None, invent=ai)
    b = _body(_run(wr._api_recipe_experiment(object())))
    assert b["ok"] and b["recipe"]["name"] == "Дичина боярская"
    assert b["recipe"]["reasoning"] == "Дичь да травы — сила и лёгкость."  # «Повар рассудил»
    pts = core.effect_points(b["recipe"]["effects"])
    assert pts <= b["recipe"]["budget"] + 1e-6           # баланс: числа из бюджета


def test_experiment_cooldown_blocks(monkeypatch):
    from datetime import datetime, timezone
    p = _player(recipe_at=datetime.now(timezone.utc))    # только что экспериментировал
    _wire(monkeypatch, p)
    b = _body(_run(wr._api_recipe_experiment(object())))
    assert b["ok"] is False and b["error"] == "cooldown" and b["left"] > 0


def test_experiment_not_enough_blocks(monkeypatch):
    p = _player(inventory={})                             # пустой погреб
    _wire(monkeypatch, p)
    b = _body(_run(wr._api_recipe_experiment(object())))
    assert b["ok"] is False and b["error"] == "not_enough"


def test_experiment_bad_combo_rejected(monkeypatch):
    p = _player()
    _wire(monkeypatch, p, ingredients=("game",))         # один ингредиент — невалидно
    b = _body(_run(wr._api_recipe_experiment(object())))
    assert b["ok"] is False and b["error"] == "bad_combo"


def test_known_recipe_skips_ai(monkeypatch):
    """Уже открытое в мире комбо не зовёт ИИ — берётся из БД (детерминизм)."""
    p = _player()
    ch = core.combo_hash(["game", "herbs"])
    row = NS(combo_hash=ch, key=core.recipe_key(ch), name="Старое блюдо", lore="л",
             reasoning="р", ingredients="game,herbs", effects={"hp": 12}, budget=11, discoverer_id=999)
    called = {"invent": False}

    async def spy_invent(_i, _b):
        called["invent"] = True
        return None
    _wire(monkeypatch, p, existing=row)
    monkeypatch.setattr(wr.ai_recipe, "invent", spy_invent)
    b = _body(_run(wr._api_recipe_experiment(object())))
    assert b["ok"] and b["recipe"]["name"] == "Старое блюдо"
    assert b["new_to_world"] is False
    assert called["invent"] is False                     # ИИ НЕ звался на известное комбо
