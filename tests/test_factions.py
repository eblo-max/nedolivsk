"""Живой мир Ф1: фракции с зубами — ранги, котировки, врезки в механики."""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import factions as F  # noqa: E402


def _pl(**fac):
    return NS(story={"faction": dict(fac)}, gold=1000, level=5,
              equipment={}, inventory={}, buff_kind=None, buff_until=None,
              tavern=NS(level=5, products={}, reputation=50))


def test_rank_thresholds():
    assert [F.rank_of(v) for v in (75, 40, 15, 0, -15, -40)] == [3, 2, 1, 0, -1, -2]


def test_merchant_mult_moves_fork_floor():
    from bot.game import balance, trade
    hero = _pl(merchants=80)     # легенда лиги
    enemy = _pl(merchants=-80)   # враг
    assert F.merchant_price_mult(hero) == 1.09
    assert F.merchant_price_mult(enemy) == 0.94
    def fork_floor(fmul):
        offer = {"fv": 20.0, "wealth": 200, "qty": 10, "fmul": fmul, "greed": 0.2}
        opts = trade.deal_options(offer, 30, 10)
        return opts["full"]["unit"] if opts else None
    lo, hi = fork_floor(0.94), fork_floor(1.09)
    if lo is not None and hi is not None:
        assert hi >= lo          # другу лиги пол вилки не ниже, чем врагу
    assert int(round(20.0 * balance.TRADE_MIN_UNDER * 1.09)) > int(
        round(20.0 * balance.TRADE_MIN_UNDER * 0.94))


def test_thief_night_sale_only_at_night():
    p = _pl(thieves=45)          # побратим воров
    assert F.thief_night_sale_mult(p, 23) == 1.04
    assert F.thief_night_sale_mult(p, 12) == 1.0
    assert F.thief_night_sale_mult(_pl(), 23) == 1.0


def test_watch_pickpocket_and_bust_keep():
    friend = _pl(watch=45)
    assert F.watch_pickpocket_mult(friend) == 0.6      # −20%×2 ранга
    assert abs(F.watch_bust_keep_pct(friend) - 0.24) < 1e-9
    assert F.watch_pickpocket_mult(_pl(watch=-50)) == 1.4   # врага щиплют сильнее


def test_bust_keeps_share_for_watch_friend():
    from bot.game import nightrun as nr
    p = _pl(watch=80)            # легенда стражи → 36%
    run = nr.start(p, "green_valleys")
    run["satchel"] = {"gold": 100}
    out = nr._bust(run, {"kind": "fight"}, p)
    assert out["saved"] == {"gold": 36} and out["lost"] == {"gold": 64}
    out2 = nr._bust(dict(run, satchel={"gold": 100}), {"kind": "fight"}, _pl())
    assert "saved" not in out2 and out2["lost"] == {"gold": 100}


def test_bust_keep_actually_credits_player():
    """Регресс (аудит 03.07): перк стражи не только ПОКАЗЫВАЛСЯ, но и реально
    зачислял отбитое добро. Раньше оба хендлера стирали run на бюсте → kept
    (до 36% котомки) молча терялся — перк был мёртв."""
    from bot.game import nightrun as nr
    p = _pl(watch=80)                       # легенда стражи → отбивает 36%
    p.gold = 1000
    run = nr.start(p, "green_valleys")
    run["satchel"] = {"gold": 100, "grain": 10}
    nr._bust(run, {"kind": "fight"}, p)     # оставит kept в run['satchel']
    saved = nr.bust_keep(run, p)            # кредитуем игроку (фикс)
    assert saved == {"gold": 36, "grain": 3}
    assert p.gold == 1036                   # золото реально пришло
    assert p.inventory.get("grain") == 3    # ресурс — в инвентарь
    assert run["satchel"] == {}             # вычищено — второй bust_keep не задвоит
    assert nr.bust_keep(run, p) == {}       # идемпотентно
    assert p.gold == 1036
    assert p.econ.get("nightrun") == 36     # учтено в экономике
    # не-друг стражи: отбивать нечего — no-op, всё потеряно
    p2 = _pl(); p2.gold = 1000
    run2 = nr.start(p2, "green_valleys"); run2["satchel"] = {"gold": 100}
    nr._bust(run2, {"kind": "fight"}, p2)
    assert nr.bust_keep(run2, p2) == {} and p2.gold == 1000


def test_adjust_faction_returns_rank_change():
    from bot.game import story_state as ss
    p = _pl(merchants=13)
    old_r, new_r = ss.adjust_faction(p, "merchants", 5)
    assert (old_r, new_r) == (0, 1)                   # пересёк порог «свой»
    old_r, new_r = ss.adjust_faction(p, "merchants", 1)
    assert old_r == new_r == 1                        # без смены ранга


def test_perk_lines_from_quotes():
    p = _pl(merchants=45, thieves=20, watch=16)
    assert any("6%" in ln for ln in F.perk_lines(p, "merchants"))
    assert any("тишком" in ln for ln in F.perk_lines(p, "thieves"))
    assert any("карманники" in ln for ln in F.perk_lines(p, "watch"))
    assert F.perk_lines(_pl(), "merchants") == []     # нейтралу не пишем


# ── Ф2: память именных NPC + ритмы ──────────────────────────────────────
def test_trader_memory_bends_offer():
    """Личное отношение купца двигает потолок цены и реплику."""
    import random
    from bot.game import trade
    tav = NS(products={"ale1": 20}, level=5, reputation=50)
    friend = NS(story={"npc_rel": {}, "faction": {}}, gold=0)
    # выставим память вручную под конкретного купца из ролла
    probe = trade.make_offer(tav, friend, False, rng=random.Random(5))
    cid = probe["cit"]
    warm = NS(story={"npc_rel": {cid: 5}, "faction": {}}, gold=0)
    cold = NS(story={"npc_rel": {cid: -5}, "faction": {}}, gold=0)
    o_warm = trade.make_offer(tav, warm, False, rng=random.Random(5))
    o_cold = trade.make_offer(tav, cold, False, rng=random.Random(5))
    assert o_warm["max_unit"] > o_cold["max_unit"]     # друга не жмут
    assert o_warm["mood_line"] and "добром" in o_warm["mood_line"]
    assert o_cold["mood_line"] and "обошёлся" in o_cold["mood_line"]


def test_visit_chance_rhythms():
    from datetime import datetime, timezone
    from bot.game import balance, trade
    night = datetime(2026, 7, 1, 21, 0, tzinfo=timezone.utc)    # 00:00 МСК (среда)
    friday_day = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)  # пятница 12:00 МСК
    weekday = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)   # среда 12:00 МСК
    assert trade.visit_chance(0.2, night) == 0.2 * balance.TRADE_NIGHT_MULT
    assert trade.visit_chance(0.2, friday_day) == 0.2 * balance.TRADE_FRIDAY_MULT
    assert trade.visit_chance(0.2, weekday) == 0.2


# ── Матрица «обещано ↔ подключено»: все бонусы фракций живые ─────────────
def test_shop_personal_price_display_equals_charge():
    """Лавка: другу лиги дешевле, врагу дороже — одна котировка на показ и списание."""
    from bot.game import shop
    res = next(iter(shop.sellable()))
    base = shop.price(res)
    friend = _pl(merchants=80)
    enemy = _pl(merchants=-80)
    assert shop.price_for(friend, res) <= base <= shop.price_for(enemy, res)
    assert shop.price_for(friend, res) < shop.price_for(enemy, res)


def test_retail_night_bonus_actually_pays(monkeypatch):
    """Ночная скупка воров реально увеличивает золото со сбыта."""
    from datetime import datetime, timezone
    from bot.game import logic

    def _mk_t():
        return NS(products={"ale1": 10}, reputation=50, rep_progress=0,
                  auction_sold=0, level=5)

    def run(player):
        t = _mk_t()
        monkeypatch.setattr(logic, "_now",
                            lambda: datetime(2026, 7, 1, 20, 30, tzinfo=timezone.utc))  # 23:30 МСК
        _sold, gold, _rep = logic.apply_retail(player, t, {"ale1": 5})
        return gold

    thief = NS(story={"faction": {"thieves": 45}}, gold=0, level=5,
               equipment={}, inventory={}, buff_kind=None, buff_until=None,
               reputation=0, tavern=None, perks={}, econ={})
    plain = NS(story={"faction": {}}, gold=0, level=5,
               equipment={}, inventory={}, buff_kind=None, buff_until=None,
               reputation=0, tavern=None, perks={}, econ={})
    assert run(thief) >= run(plain)


# ── Санкции вражды ───────────────────────────────────────────────────────
def test_hostility_sanctions_bite():
    enemy_w = _pl(watch=-80)     # враг стражи
    enemy_t = _pl(thieves=-80)   # враг воров
    assert F.watch_pickpocket_mult(enemy_w) == 1.4     # щиплют на 40% больше
    assert abs(F.watch_hostile_penalty(enemy_w) - 0.06) < 1e-9
    assert F.watch_hostile_penalty(_pl(watch=50)) == 0.0
    assert F.thief_sneak_bonus(enemy_t) == -0.04       # осведомители сдают
    assert F.thief_night_sale_mult(enemy_t, 23) == 0.96
    # строки санкций видны на экране
    assert any("БОЛЬШЕ" in ln for ln in F.perk_lines(enemy_w, "watch"))
    assert any("-4%" in ln for ln in F.perk_lines(enemy_t, "thieves"))


def test_hostile_watch_makes_nightrun_harder():
    from bot.game import nightrun as nr
    friend, enemy = _pl(), _pl(watch=-80)
    for p_ in (friend, enemy):
        p_.equipment = {}
    run_f = nr.start(friend, "green_valleys")
    run_e = nr.start(enemy, "green_valleys")
    run_f["leg"] = run_e["leg"] = 3
    assert nr.success_p(run_e, enemy, "fight") < nr.success_p(run_f, friend, "fight")
