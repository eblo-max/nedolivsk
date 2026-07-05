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


def test_top_title_returns_highest_prestige():
    """У имени показываем ВЫСШИЙ купленный титул (ранг zodchy<mason<pillar)."""
    p = _pl(zodar=1000)
    assert shop.top_title(p) is None                       # нет титулов
    shop.apply(p, shop.get("t_zodchy"))
    assert shop.top_title(p)["key"] == "zodchy"
    shop.apply(p, shop.get("t_pillar"))                    # выше по рангу
    assert shop.top_title(p)["key"] == "pillar"
    shop.apply(p, shop.get("t_mason"))                     # ниже pillar — не перебивает
    assert shop.top_title(p)["key"] == "pillar"
    tt = shop.top_title(p)
    assert tt["emoji"] and tt["short"]


def test_facade_and_prestige_dto():
    p = _pl(zodar=1000)
    assert shop.facade_badge(p) is None
    dto = shop.prestige_dto(p)
    assert dto == {"title": None, "facade": None}
    shop.apply(p, shop.get("f_carved"))
    fb = shop.facade_badge(p)
    assert fb["key"] == "carved" and fb["emoji"] and fb["short"]
    assert shop.prestige_dto(p)["facade"]["key"] == "carved"


_TIERS = {"bronze", "silver", "gold", "legendary"}
_STYLES = set(shop.STYLE_LABEL)   # все известные стили титулов


def test_titles_have_styles_facades_have_tiers():
    """Инвариант: у каждого ТИТУЛА — валидный стиль (визуал), у каждого ФАСАДА —
    ярус; у каждого стиля есть подпись STYLE_LABEL."""
    for r in shop.CATALOG:
        if r.kind == "title":
            assert r.payload in shop.TITLE_BADGE and r.payload in shop.TITLE_RANK
            st = shop.TITLE_BADGE[r.payload]["style"]
            assert st in _STYLES, f"неизвестный стиль {st}"
            assert shop.reward_style(r) == st
        if r.kind == "facade":
            assert r.payload in shop.FACADE_BADGE and r.payload in shop.FACADE_RANK
            assert shop.FACADE_BADGE[r.payload]["tier"] in _TIERS
            assert shop.reward_tier(r) in _TIERS


def test_exotic_styles_present_and_legend_is_holo():
    """Необычные стили (неон/плазма/жар/иней/бездна/голограмма) реально в наборе."""
    styles = {shop.TITLE_BADGE[k]["style"] for k in shop.TITLE_RANK}
    assert {"neon", "plasma", "frost", "ember", "void", "holo"} <= styles
    p = _pl(zodar=9999)
    shop.apply(p, shop.get("t_legend"))
    tt = shop.top_title(p)
    assert tt["key"] == "legend" and tt["style"] == "holo"
    d = {x["id"]: x for x in shop.catalog_dto(p)}
    assert d["t_spark"]["style"] == "neon" and d["t_legend"]["style"] == "holo"
    assert d["f_blazing"]["tier"] == "legendary"   # фасады — по-прежнему ярус


def test_title_shown_selection_overrides_highest():
    p = _pl(zodar=9999)
    shop.apply(p, shop.get("t_keeper"))              # ранг ниже
    shop.apply(p, shop.get("t_spark"))              # ранг выше → авто-высший
    assert shop.top_title(p)["key"] == "spark"
    assert shop.set_title_shown(p, "keeper") is True
    assert shop.top_title(p)["key"] == "keeper"     # показывается выбранный
    assert shop.set_title_shown(p, "") is True      # снять выбор → снова авто
    assert shop.top_title(p)["key"] == "spark"
    assert shop.set_title_shown(p, "legend") is False   # не владеет — нельзя


def test_facades_collected_and_selectable():
    p = _pl(zodar=9999)
    shop.apply(p, shop.get("f_carved"))
    shop.apply(p, shop.get("f_gilded"))             # оба куплены, новый выбран
    assert shop.owns(p, shop.get("f_carved")) and shop.owns(p, shop.get("f_gilded"))
    assert shop.facade_badge(p)["key"] == "gilded"
    assert shop.set_facade(p, "carved") is True
    assert shop.facade_badge(p)["key"] == "carved"
    assert shop.set_facade(p, "") is True           # снять вывеску
    assert shop.facade_badge(p) is None
    assert shop.set_facade(p, "crested") is False   # не владеет


def test_facade_backward_compat_single_string():
    p = _pl(story={"artel": {"facade": "carved"}})   # старый формат — одиночный фасад
    assert shop.owns(p, shop.get("f_carved"))        # владение читается из списка-конверсии
    assert shop.facade_badge(p)["key"] == "carved"


def test_prestige_options_dto_shape():
    p = _pl(zodar=9999)
    shop.apply(p, shop.get("t_zodchy"))
    shop.apply(p, shop.get("f_carved"))
    dto = shop.prestige_options_dto(p)
    assert dto["has"] and len(dto["titles"]) == 1 and len(dto["facades"]) == 1
    assert dto["titles"][0]["key"] == "zodchy" and dto["titles"][0]["shown"] is True
    assert dto["facades"][0]["shown"] is True


def test_zodar_not_earnable_or_tradeable_here():
    """Инвариант bind-on-earn: в Лавке зодар только ТРАТЯТ (кран/торговля — нигде)."""
    import inspect
    src = inspect.getsource(shop)
    # ни одной операции начисления зодара в модуле Лавки
    assert "zodar +=" not in src and "zodar = " not in src.replace("getattr", "")
