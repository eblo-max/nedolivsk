"""Инварианты Фазы 0 «Чудеса города» + валюта Зодар: реестр, таблица, колонка,
сток. Ловит регрессы фундамента (битый FIRST_WONDER, рассинхрон ключей,
пропавшую колонку/сток) до того, как на них наступит Фаза 1."""

import os

os.environ.setdefault("BOT_TOKEN", "test:test")

from sqlalchemy import Integer  # noqa: E402

from bot.db import models  # noqa: E402
from bot.game import economy, wonder  # noqa: E402


def test_wonder_registry_self_consistent():
    assert wonder.WONDERS, "реестр чудес пуст"
    for key, w in wonder.WONDERS.items():
        assert w.key == key, f"ключ реестра != WonderDef.key: {key} vs {w.key}"
        assert w.name and w.blurb and w.bonus and w.sprite, f"пустое поле у {key}"
        assert w.phases, f"у чуда {key} нет фаз"
        pkeys = [p.key for p in w.phases]
        assert len(pkeys) == len(set(pkeys)), f"дубли ключей фаз у {key}"
        for p in w.phases:
            assert p.title, f"пустое название фазы у {key}"
            assert p.base_target > 0, f"нулевая/отриц. цель фазы у {key}"


def test_first_wonder_exists():
    assert wonder.FIRST_WONDER in wonder.WONDERS
    assert wonder.get(wonder.FIRST_WONDER) is not None
    assert wonder.get("_нет_такого_") is None


def test_first_wonder_is_wall_with_three_phases():
    w = wonder.get(wonder.FIRST_WONDER)
    assert w.name == "Твердыня" and len(w.phases) == 3


def test_zodar_column_present_and_typed():
    col = models.Player.__table__.columns.get("zodar")
    assert col is not None, "нет колонки zodar у players"
    assert isinstance(col.type, Integer), "zodar не INTEGER"
    assert col.nullable is False, "zodar должен быть NOT NULL"
    # bind-on-earn: значение стартует с 0
    assert col.default is not None and col.default.arg == 0


def test_wonders_table_registered():
    t = models.Base.metadata.tables.get("wonders")
    assert t is not None, "таблица wonders не зарегистрирована"
    for c in ("key", "phase", "progress", "target", "contributions", "status"):
        assert c in t.columns, f"нет колонки {c} в wonders"


def test_wonder_is_a_sink_not_faucet():
    assert "wonder" in economy.SINKS, "сток wonder не заведён"
    assert "wonder" not in economy.FAUCETS, "wonder ошибочно в кранах"
    assert "wonder" in economy.LABELS


# ── Фаза 1: ядро-логика ────────────────────────────────────────────────────
from types import SimpleNamespace as NS  # noqa: E402

from bot.game import production as prod  # noqa: E402


def _wonder(**kw):
    base = dict(key="wall", phase=1, progress=0, target=1000,
                contributions={}, status="building")
    base.update(kw)
    return NS(**base)


def test_item_points_weighs_by_value():
    from bot.game import balance
    # сырьё × RESOURCE_PRICE, товар × GOODS.price, золото × 0.5, чужое — 0
    assert wonder.item_points({"wood": 10}) == int(10 * balance.RESOURCE_PRICE["wood"])
    assert wonder.item_points({"ale3": 5}) == 5 * prod.GOODS["ale3"].price
    assert wonder.item_points({"gold": 100}) == 50            # труд ценнее денег
    assert wonder.item_points({"_нет_": 99}) == 0
    # золото дешевле эквивалентной ценности сырья
    assert wonder.item_points({"gold": 10}) < wonder.item_points(
        {"ore": 10})  # ore=7.0 → 70 vs gold 5


def test_phase_target_scales_with_active():
    assert wonder.phase_target(1200, 1) == 1200
    assert wonder.phase_target(1200, 40) == 48000
    assert wonder.phase_target(1200, 0) == 1200               # кламп на 1


def test_effective_points_diminishes_over_daily_cap():
    cap = wonder.DAILY_SOFT_CAP
    assert wonder.effective_points(1000, 0) == 1000           # под порогом — полный курс
    # частично за порогом: остаток вдвое слабее
    assert wonder.effective_points(1000, cap - 500) == 500 + 500 / wonder.DIMINISHED_DIV
    assert wonder.effective_points(1000, cap) == 1000 / wonder.DIMINISHED_DIV  # весь сверх
    assert wonder.effective_points(0, 0) == 0.0


def test_carry_remainder_never_wasted():
    # 200 эфф-очков → 1 зодар (200//180), остаток 20 переносится и добивает следующий
    a1, carry1 = wonder._award_from_carry(0.0, 200)
    assert a1 == 1 and abs(carry1 - 20) < 1e-9
    a2, carry2 = wonder._award_from_carry(carry1, 170)        # 20+170=190 → 1 зодар, 10
    assert a2 == 1 and abs(carry2 - 10) < 1e-9


def test_apply_contribution_accrues_then_rolls_phase_with_capstone():
    w = _wonder(target=1000)
    r1 = wonder.apply_contribution(w, "7", "Гоблин", raw_points=600,
                                   eff_points=0, active=1)
    assert w.progress == 600 and not r1["phase_done"] and w.phase == 1
    # добивающий вклад закрывает фазу 1 → капстоун, переход на фазу 2, перелив в прогресс
    r2 = wonder.apply_contribution(w, "8", "Тролль", raw_points=500,
                                   eff_points=0, active=1)
    assert r2["phase_done"] and r2["capstone"] and not r2["wonder_done"]
    assert w.phase == 2 and w.progress == 100                 # 1100-1000 перелив
    assert w.target == wonder.WONDERS["wall"].phases[1].base_target  # ×active=1
    # вклад, НЕ переваливший порог, — не капстоун
    r3 = wonder.apply_contribution(w, "7", "Гоблин", raw_points=10,
                                   eff_points=0, active=1)
    assert not r3["capstone"]


def test_apply_contribution_finishes_wonder_on_last_phase():
    w = _wonder(phase=3, target=500, progress=0)
    r = wonder.apply_contribution(w, "7", "Гоблин", raw_points=500,
                                  eff_points=0, active=1)
    # финал → 'sealing' (вклады закрыты); бонус/буф доплатит нотифаер, потом 'done'
    assert r["wonder_done"] and w.status == "sealing" and w.progress == 500


def test_big_convoy_cascades_through_multiple_phases_no_stall():
    """Один большой обоз может закрыть НЕСКОЛЬКО фаз за вклад — не застрять на 100%.
    Регресс: раньше перелив уносился лишь на 1 фазу → чудо висло на 100%, не сейлясь."""
    p = wonder.WONDERS["wall"].phases
    # обоз, перекрывающий все три фазы (base×active=1) сразу → сразу sealing
    w = _wonder(phase=1, target=p[0].base_target, progress=0)
    r = wonder.apply_contribution(w, "1", "Кит", raw_points=10 ** 6,
                                  eff_points=0, active=1)
    assert r["wonder_done"] and w.status == "sealing" and w.phase == len(p)
    assert w.progress == w.target                    # запечатано ровно на цели финала
    # обоз, закрывающий фазы 1+2 и с недобором до 3 — стоит на фазе 3 с переливом
    w2 = _wonder(phase=1, target=p[0].base_target, progress=0)
    over = p[0].base_target + p[1].base_target + 60  # 200+300+60
    r2 = wonder.apply_contribution(w2, "1", "Я", raw_points=over,
                                   eff_points=0, active=1)
    assert w2.phase == 3 and w2.progress == 60 and w2.status == "building"
    assert not r2["wonder_done"] and r2["phase_done"] and r2["capstone"]


def test_apply_contribution_awards_zodar_via_carry():
    w = _wonder(target=10 ** 9)                               # не закрыть — только копим
    r = wonder.apply_contribution(w, "7", "Гоблин", raw_points=400,
                                  eff_points=360, active=1)   # 360//180 = 2 зодара
    assert r["award"] == 2
    assert w.contributions["7"]["zodar"] == 2 and w.contributions["7"]["pts"] == 400


def test_phase_bonus_rewards_top_more_and_excludes_zero():
    contribs = {str(i): {"pts": (10 - i) * 100} for i in range(10)}  # убыв. вклад
    contribs["z"] = {"pts": 0}                                # не вкладывал
    bonus = wonder.phase_bonus(contribs)
    assert "z" not in bonus                                   # 0 очков — нет бонуса
    top = bonus["0"]                                          # крупнейший вкладчик
    assert top == max(bonus.values()) and top > bonus["9"]    # топ > хвоста
    assert all(v > 0 for v in bonus.values())


def test_active_bonuses_only_when_wonder_done():
    # буф вешается на escal (влияет на бой), НЕ на threshold (тот на бой не влияет)
    assert wonder.invasion_escal_mult(NS(live={})) == 1.0
    assert wonder.invasion_escal_mult(NS(live=None)) == 1.0
    w = NS(live={"wonders_done": ["wall"]})
    assert wonder.invasion_escal_mult(w) == wonder.WALL_ESCAL_MULT
    assert wonder.active_bonuses(w)["invasion_escal_mult"] == 0.85
    assert wonder.WALL_ESCAL_MULT < 1.0                    # Орда именно СЛАБЕЕ


def test_gardens_yield_buff_only_when_done():
    """🌿 Сады: множитель добычи 1.0 без чуда, ×1.05 с готовым; active_bonuses
    (world-путь) и gather_yield_mult (кэш-путь) согласованы."""
    wonder.set_done_cache([])
    try:
        assert wonder.gather_yield_mult() == 1.0
        wonder.set_done_cache(["gardens"])
        assert wonder.gather_yield_mult() == wonder.GARDENS_YIELD_MULT == 1.05
        w = NS(live={"wonders_done": ["gardens"]})
        assert wonder.active_bonuses(w)["gather_yield_mult"] == 1.05
        assert "invasion_escal_mult" not in wonder.active_bonuses(w)  # чужой буф не протёк
        wonder.set_done_cache([])
        wonder.note_done("gardens")                     # путь нотифаера (settle)
        assert wonder.gather_yield_mult() == 1.05
    finally:
        wonder.set_done_cache([])                       # не загрязняем другие тесты


def test_expedition_quote_applies_gardens_buff():
    """Показ=действие: единая котировка добычи реально умножается на бафф Садов
    (и показ панели, и начисление claim зовут её же)."""
    from bot.game import logic
    t = NS(level=5, production={}, products={}, upgrades=[], buildings=[],
           reputation=50, comfort=5, capacity=20)
    p = NS(gold=0, level=5, equipment={}, inventory={}, expeditions=[],
           region="green_valleys", buff_kind=None, buff_until=None,
           perks={}, created_at=None, tavern=t, story=None)
    wonder.set_done_cache([])
    try:
        base = logic.expedition_gain_quote(p, t, "wood")
        wonder.set_done_cache(["gardens"])
        buffed = logic.expedition_gain_quote(p, t, "wood")
    finally:
        wonder.set_done_cache([])
    assert base > 0 and buffed >= base                  # буф не в минус
    assert buffed <= int(base * 1.05) + 1               # и не больше заявленных +5%
    assert buffed >= int(base * 1.05) - 1               # реально применился


def test_done_list_dedups_and_excludes_main_screen():
    """Зал славы: дубли одного чуда (тестовые обкатки) не двоятся — берём новейшее;
    чудо главного экрана (мемориал) не дублируется внизу."""
    from datetime import datetime, timezone
    from bot.webapi.wonder import _done_list_dto
    mk = lambda i, key, top_name: NS(  # noqa: E731
        id=i, key=key, contributions={"1": {"name": top_name, "pts": 100}},
        updated_at=datetime(2026, 7, i, tzinfo=timezone.utc))
    ws = [mk(8, "wall", "Реальный"), mk(3, "wall", "Обкатка")]   # новые сверху
    out = _done_list_dto(ws)
    assert len(out) == 1 and out[0]["top"] == "Реальный"          # дедуп по key
    assert out[0]["name"] == "Твердыня" and out[0]["date"] == "08.07.2026"
    assert _done_list_dto(ws, exclude_id=8) == []                 # мемориал не двоится
    both = [mk(9, "gardens", "Зодчий"), mk(8, "wall", "Реальный")]
    names = [d["name"] for d in _done_list_dto(both, exclude_id=9)]
    assert names == ["Твердыня"]                                  # активная стройка садов →
    #                                                               внизу только Твердыня


def test_done_wonder_dto_is_sealed_memorial():
    """Мемориал: DTO возведённого чуда — status='done', sealed, 100% (экран стройки
    показывает готовое чудо, а не пустоту, пока не заложили новое)."""
    from bot.webapi.wonder import _wonder_dto
    w = _wonder(phase=3, progress=64000, target=64000, status="done",
                contributions={"1": {"name": "Зодчий", "pts": 10, "zodar": 2}})
    dto = _wonder_dto(w, 1)
    assert dto["status"] == "done" and dto["sealed"] is True
    assert dto["pct"] == 100 and dto["board"][0]["name"] == "Зодчий"
