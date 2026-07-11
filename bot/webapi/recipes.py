"""«Тайные рецепты» — веб-эндпоинт эксперимента (ИИ-блюда) в здании «Кухня».

Поток эксперимента (под локом строки игрока):
  валидируем комбо (только словарь, анти-инъекция) → кулдаун → хватает ингредиентов
  → бюджет+combo_hash → рецепт из кэша БД (детерминизм на весь мир) ИЛИ invent()
  (+процедурный фолбэк) → списываем ингредиенты → порции блюда в свой склад → владение
  (кулинарная книга) → кулдаун → коммит. Числа эффектов назначает КОД (recipes.assign_
  effects), не ИИ. Блюдо пьётся как фляга в рейде/охоте (combat.flask_apply, seam).
"""
from datetime import datetime, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.game import ai_recipe, artel_shop, inventory, recipes
from bot.webapi.core import _auth, touch_seen


def _palette(p) -> list[dict]:
    """Съедобные ингредиенты с наличием у игрока — из чего экспериментировать.
    value — ценность (для живой оценки силы блюда на фронте до эксперимента)."""
    from bot.game import balance as bal
    names = {**bal.RESOURCE_NAMES, **bal.GOODS_NAMES}
    emojis = {**bal.RESOURCE_EMOJI, **bal.GOODS_EMOJI}
    return [{"key": k, "name": names.get(k, k),
             "emoji": emojis.get(k, "🍲"), "have": inventory.get(p, k),
             "value": recipes.price(k), "tags": list(recipes.INGREDIENT_TAGS.get(k, ()))}
            for k in recipes.INGREDIENTS]


def _cookbook(p) -> list[dict]:
    """Открытые игроком тайные блюда (персистентно), со складом и эффектом-меткой."""
    t = p.tavern
    out = []
    for key in artel_shop.owned_recipe_ids(p):
        if not recipes.is_recipe_key(key):
            continue                                  # только тайные блюда, не эксклюзив зодчих
        meta = recipes.meta_for_key(key)
        if not meta:
            continue
        out.append({"key": key, "name": meta["name"], "lore": meta["lore"],
                    "label": recipes.cellar_label(meta["effects"]),
                    "qty": recipes.stock_get(t, key)})
    out.sort(key=lambda r: (-r["qty"], r["name"]))
    return out


def _cooldown_left(p, now: datetime) -> int:
    if not p.recipe_at:
        return 0
    left = recipes.RECIPE_COOLDOWN_SEC - (now - p.recipe_at).total_seconds()
    return max(0, int(left))


def experiment_dto(p) -> dict:
    """Данные вкладки «Тайная кухня» внутри здания Кухня (для _api_building)."""
    return {
        "palette": _palette(p),
        "cost_each": recipes.EXPERIMENT_COST_EACH,
        "output": recipes.EXPERIMENT_OUTPUT,
        "min": recipes.MIN_INGREDIENTS,
        "max": recipes.MAX_INGREDIENTS,
        "cooldown": recipes.RECIPE_COOLDOWN_SEC,
        "cooldown_left": _cooldown_left(p, datetime.now(timezone.utc)),
        "ai": ai_recipe.available(),                  # включён ли ИИ (иначе процедурно)
        # константы бюджета — фронт считает живую «силу ~N» и ярус до эксперимента
        "budget_base": recipes.RECIPE_BUDGET_BASE, "budget_k": recipes.RECIPE_BUDGET_K,
        "budget_floor": recipes.RECIPE_BUDGET_FLOOR, "budget_cap": recipes.RECIPE_BUDGET_CAP,
        "tiers": [[cap if cap < 10 ** 8 else 9999, name] for cap, name in recipes.RECIPE_TIERS],
        "cookbook": _cookbook(p),
    }


def _recipe_card(data: dict, t) -> dict:
    """Карточка блюда для фронта (после открытия/варки)."""
    return {"key": data["key"], "name": data["name"], "lore": data["lore"],
            "reasoning": data.get("reasoning", ""),
            "label": recipes.cellar_label(data["effects"]),
            "effects": data["effects"], "budget": data["budget"],
            "luck": recipes.luck_tier(data["budget"], data.get("ingredients", [])),
            "qty": recipes.stock_get(t, data["key"])}


def _row_data(row) -> dict:
    """Recipe ORM → data-dict (одинаковый формат с recipes.build_recipe)."""
    ing = (getattr(row, "ingredients", "") or "")
    return {"combo_hash": row.combo_hash, "key": row.key, "name": row.name,
            "lore": row.lore or "", "reasoning": getattr(row, "reasoning", "") or "",
            "ingredients": ing.split(",") if ing else [],
            "effects": dict(row.effects or {}), "budget": row.budget}


async def _api_recipe_experiment(request: web.Request) -> web.Response:
    """Открыть/сварить тайное блюдо из выбранных ингредиентов.

    Фаза A (без лока): проверки + ИИ-вызов ВНЕ транзакции — чтобы 2-3 с обращения к
    Claude не держали лок строки игрока и соединение пула. Фаза B (лок строки): атомарно
    списываем ингредиенты, варим порции, ставим кулдаун; рецепт — гонко-безопасный
    get-or-create по combo_hash (два первооткрывателя одного комбо не роняют друг друга)."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    ings = [str(x) for x in (body.get("ingredients") or [])]
    if not recipes.valid_combo(ings):
        return web.json_response({"ok": False, "error": "bad_combo"})
    chash = recipes.combo_hash(ings)
    now = datetime.now(timezone.utc)
    cost = {k: recipes.EXPERIMENT_COST_EACH for k in set(ings)}

    # ── Фаза A: быстрые проверки (без лока) + рецепт из БД или ИИ вне транзакции ──
    async with session_factory() as s:
        p0 = await repo.get_player(s, uid)
        if p0 is None or not p0.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        left = _cooldown_left(p0, now)
        if left > 0:
            return web.json_response({"ok": False, "error": "cooldown", "left": left})
        if not inventory.can_afford(p0, cost):
            return web.json_response({"ok": False, "error": "not_enough",
                                      "need": recipes.EXPERIMENT_COST_EACH})
        existing = await repo.get_recipe_by_hash(s, chash)
        existing_data = _row_data(existing) if existing is not None else None

    if existing_data is not None:
        data = existing_data                                  # уже открыт в мире — ИИ не зовём
    else:
        budget = recipes.recipe_budget(ings)
        ai = await ai_recipe.invent(ings, budget)             # None → процедурный фолбэк
        name, lore, reasoning, proposal = ai if ai else (None, None, None, None)
        data = recipes.build_recipe(ings, ai_name=name, ai_lore=lore,
                                    ai_reasoning=reasoning, ai_proposal=proposal)

    # ── Фаза B: атомарно на строке игрока (лок) ──────────────────────────────
    async with session_factory() as s:
        p = await repo.get_player(s, uid, for_update=True)
        if p is None or not p.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        await touch_seen(s, uid)
        now = datetime.now(timezone.utc)
        left = _cooldown_left(p, now)
        if left > 0:                                          # успел параллельный эксперимент
            return web.json_response({"ok": False, "error": "cooldown", "left": left})
        if not inventory.can_afford(p, cost):
            return web.json_response({"ok": False, "error": "not_enough",
                                      "need": recipes.EXPERIMENT_COST_EACH})
        row = await repo.upsert_recipe(s, data, discoverer_id=uid)  # get-or-create по хэшу
        data = _row_data(row)                                 # канонная строка (мог выиграть другой)
        new_to_world = existing_data is None and row.discoverer_id == uid
        recipes.note_recipe(data)
        inventory.pay(p, cost)
        recipes.stock_add(p.tavern, data["key"], recipes.EXPERIMENT_OUTPUT)
        first_time = artel_shop.grant_recipe(p, data["key"])
        p.recipe_at = now
        repo.add_log(s, "player", p.id,
                     f"🍲 {'открыл' if first_time else 'сварил'} рецепт: {data['name']}")
        await s.commit()
        card = _recipe_card(data, p.tavern)
        dto = experiment_dto(p)

    return web.json_response({"ok": True, "recipe": card, "experiment": dto,
                              "new_to_world": new_to_world, "first_time": first_time},
                             headers={"Cache-Control": "no-store"})
