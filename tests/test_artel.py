"""Лавка Артели (Фаза 2): каталог-инварианты, владение, применение, показ=действие."""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import artel_shop as shop  # noqa: E402


def _pl(zodar=0, story=None):
    return NS(zodar=zodar, story=story or {})


def test_catalog_self_consistent():
    assert shop.CATALOG
    ids = [r.id for r in shop.CATALOG]
    assert len(ids) == len(set(ids)), "дубли id в каталоге"
    for r in shop.CATALOG:
        assert r.cost > 0 and r.name and r.emoji
        assert r.kind in ("title", "facade", "recipe") and r.payload
        if r.kind == "recipe":                       # Ф2b: рецепт знает, где готовится и что даёт
            assert r.building and r.effect
        assert shop.get(r.id) is r
    assert shop.get("_нет_") is None


def test_apply_and_owns_title():
    p = _pl(zodar=100)
    r = next(x for x in shop.CATALOG if x.kind == "title")
    assert not shop.owns(p, r)
    shop.apply(p, r)
    assert shop.owns(p, r) and r.id in shop.owned_ids(p)
    assert r.payload in p.story["artel"]["titles"]


def test_apply_idempotent_no_dup():
    p = _pl(zodar=100)
    r = next(x for x in shop.CATALOG if x.kind == "title")
    shop.apply(p, r)
    shop.apply(p, r)                                   # повторно
    assert p.story["artel"]["titles"].count(r.payload) == 1


def test_apply_facade():
    p = _pl(zodar=100)
    r = next(x for x in shop.CATALOG if x.kind == "facade")
    shop.apply(p, r)
    assert shop.owns(p, r) and p.story["artel"]["facade"] == r.payload


def test_catalog_dto_flags_match_state():
    r = min(shop.CATALOG, key=lambda x: x.cost)        # самое дешёвое
    poor = _pl(zodar=r.cost - 1)
    rich = _pl(zodar=r.cost)
    poor_dto = {d["id"]: d for d in shop.catalog_dto(poor)}[r.id]
    rich_dto = {d["id"]: d for d in shop.catalog_dto(rich)}[r.id]
    assert poor_dto["affordable"] is False and rich_dto["affordable"] is True
    assert poor_dto["cost"] == r.cost                  # показ=действие: цена == спишется
    shop.apply(rich, r)
    owned_dto = {d["id"]: d for d in shop.catalog_dto(rich)}[r.id]
    assert owned_dto["owned"] is True


def test_recipe_owns_apply_and_lookup():
    """Ф2b: покупка рецепта кладётся в story['artel']['recipes'], owns_recipe видит его."""
    p = _pl(zodar=1000)
    r = next(x for x in shop.CATALOG if x.kind == "recipe")
    assert not shop.owns(p, r) and not shop.owns_recipe(p, r.payload)
    shop.apply(p, r)
    assert shop.owns(p, r) and shop.owns_recipe(p, r.payload)
    assert r.payload in shop.owned_recipe_ids(p)
    assert r.payload in p.story["artel"]["recipes"]
    shop.apply(p, r)                                   # повторно — без дублей
    assert p.story["artel"]["recipes"].count(r.payload) == 1


def test_recipes_cover_all_exclusive_targets():
    """Каждый эксклюзив-таргет (production.EXCLUSIVE + items.WONDER_GEAR) имеет рецепт в Лавке."""
    from bot.game import items, production
    recipe_payloads = {r.payload for r in shop.CATALOG if r.kind == "recipe"}
    for key in set(production.EXCLUSIVE) | set(items.WONDER_GEAR):
        assert key in recipe_payloads, f"нет рецепта в Лавке для {key}"


def test_recipe_dto_carries_building_and_effect():
    p = _pl(zodar=1000)
    r = next(x for x in shop.CATALOG if x.kind == "recipe")
    dto = {d["id"]: d for d in shop.catalog_dto(p)}[r.id]
    assert dto["building"] == r.building and dto["effect"] == r.effect
    assert dto["kind"] == "recipe"


def test_zodar_not_earnable_or_tradeable_here():
    """Инвариант bind-on-earn: в Лавке зодар только ТРАТЯТ (кран/торговля — нигде)."""
    import inspect
    src = inspect.getsource(shop)
    # ни одной операции начисления зодара в модуле Лавки
    assert "zodar +=" not in src and "zodar = " not in src.replace("getattr", "")
