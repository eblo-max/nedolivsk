"""Фляга (фаза B): порции из погреба на один бой — списание, эффекты, антидот."""

import os
import random
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import combat  # noqa: E402


def _pl(products, level=3, equipment=None):
    return NS(level=level, equipment=equipment or {}, buff_kind=None, buff_until=None,
              hp=None, hp_at=None, gold=0, inventory={}, hunt_ready_at=None,
              tavern=NS(products=dict(products)))


def test_flask_consumes_and_buffs():
    p = _pl({"ale3": 2, "roast": 1})
    stats = {"damage": 10}
    chp, used, labels = combat.flask_apply(p, ["ale3", "roast"], stats, 50)
    assert used == ["ale3", "roast"] and len(labels) == 2
    assert stats["damage"] == 17                      # +7 эль ★★★
    assert chp == 64                                  # +14 жаркое (запас на бой)
    assert p.tavern.products == {"ale3": 1, "roast": 0}


def test_flask_caps_at_two_and_skips_missing():
    p = _pl({"ale1": 5})
    stats = {"damage": 0}
    chp, used, _ = combat.flask_apply(p, ["ale1", "wine", "ale1", "ale1"], stats, 35)
    assert used == ["ale1"]            # wine нет в погребе (скип), 3-й ale1 — за лимитом
    assert stats["damage"] == 3 and chp == 35
    assert p.tavern.products["ale1"] == 4


def test_antidote_restores_armor_vs_venom():
    """Сбитень — контрпик яда: с антидотом броня снова работает против ведьмы."""
    venom = combat.ENEMY["scorpion"]
    armored = {"damage": 30, "armor": 60}
    w_plain = combat.forecast(dict(armored), venom, 80, n=500, rng=random.Random(3))[0]
    with_anti = dict(armored, antidote=True)
    w_anti = combat.forecast(with_anti, venom, 80, n=500, rng=random.Random(3))[0]
    assert w_anti > w_plain + 10       # антидот ощутимо поднимает шанс


def test_mead_dodge_stacks_over_luck_cap():
    stats = {"luck": 40, "dodge_flat": 12}            # удача уже в капе 30
    assert combat._dodge_pct(stats) == 42             # мёд работает поверх (кап 45)
    assert combat._dodge_pct({"luck": 40, "dodge_flat": 30}) == 45


def test_hunt_accepts_flask_end_to_end():
    p = _pl({"ale3": 1}, level=5,
            equipment={"weapon": "kovsh:2", "chest": "fur_coat:2"})
    res = combat.hunt(p, "zayac", rng=random.Random(1), flask=["ale3"])
    assert res.ok and res.flask == ["+7 урона"]
    assert p.tavern.products["ale3"] == 0


# ── Вилка торга (мошна купца не тянет весь объём) ────────────────────────
def test_trade_deal_options_fork():
    from bot.game import trade
    offer = {"good": "ale2", "qty": 6, "wealth": 48, "max_unit": 14.0,
             "fv": 10.0, "greed": 0.3, "prices": [8, 10, 12, 14]}
    fork = trade.deal_options(offer, 14, want=6)
    assert fork == {"mine": {"unit": 14, "qty": 3}, "full": {"unit": 8, "qty": 6}}
    assert fork["mine"]["unit"] > fork["full"]["unit"]        # дорого/мало vs дешевле/всё
    assert fork["full"]["unit"] * fork["full"]["qty"] <= offer["wealth"]


def test_trade_deal_options_none_when_affordable_or_broke():
    from bot.game import trade
    rich = {"good": "ale2", "qty": 6, "wealth": 500, "max_unit": 14.0, "fv": 10.0,
            "greed": 0.3, "prices": [8, 10, 12, 14]}
    assert trade.deal_options(rich, 14, want=6) is None       # тянет всё — вилки нет
    broke = {**rich, "wealth": 20}   # 20//6=3 < пол (6) — вилки нет, лишь частичный
    assert trade.deal_options(broke, 14, want=6) is None      # всё не осилит даже по полу


# ── Фляга в рейде ────────────────────────────────────────────────────────
def test_raid_flask_mods_aggregate():
    from bot.game import raid
    m = raid.flask_mods(["ale3", "wine"])
    assert m == {"dmg": 7, "crit": 6, "antidote": False}
    assert raid.flask_mods(["sbiten"])["antidote"] is True
    assert raid.flask_mods(None) == {"dmg": 0, "crit": 0, "antidote": False}


def test_raid_player_damage_flask_boost():
    from bot.game import raid
    p = _pl({}, level=5)
    rng = random.Random(3)
    base, _ = raid.player_damage(p, rng)
    rng = random.Random(3)                         # тот же ролл — чистая разница
    boosted, _ = raid.player_damage(p, rng, raid.flask_mods(["ale3"]))
    assert boosted > base                          # +7 к базе до разброса


# ── Фляга в ночной ходке ─────────────────────────────────────────────────
def test_nightrun_flask_boosts_matching_approach():
    from bot.game import nightrun as nr
    p = _pl({})
    run = nr.start(p, "green_valleys", flask=["ale2"])
    assert run["flask"] == ["ale2"]
    run["leg"] = 3                              # глубже — база ниже потолка шанса
    base = nr.success_p(dict(run, flask=[]), p, "fight")
    boosted = nr.success_p(run, p, "fight")
    assert abs(boosted - base - nr.FLASK_P_BONUS) < 1e-9   # эль красит драку
    assert nr.success_p(run, p, "sneak") == nr.success_p(dict(run, flask=[]), p, "sneak")


def test_nightrun_sbiten_clears_situation_penalty():
    from bot.game import balance as bal, nightrun as nr
    sit = next(iter(bal.NIGHTRUN_SITUATION_PENALTY))
    p = _pl({})
    dirty = nr.start(p, "", situation=sit)
    clean = nr.start(p, "", situation=sit, flask=["sbiten"])
    assert nr.success_p(clean, p, "fight") > nr.success_p(dirty, p, "fight")


# ── Торг: купец всегда платёжеспособен (жалоба «соглашается и уходит») ────
def test_merchant_can_afford_at_least_one():
    """make_offer не рождает купца, который жмёт руку на цену, но не тянет
    даже 1 штуку (wealth >= потолок цены за единицу)."""
    import math
    from bot.game import trade
    for seed in range(500):
        r = random.Random(seed)
        tav = NS(products={"ale1": r.randint(3, 30)}, level=r.randint(1, 6), reputation=50)
        pl = NS(story={"faction": {}, "npc_rel": {}}, gold=0)
        offer = trade.make_offer(tav, pl, False, rng=r)
        if not offer:
            continue
        assert offer["wealth"] >= math.ceil(offer["max_unit"]), offer
        # на любую accept-цену покупает хотя бы 1
        for unit in offer["prices"]:
            dec, _ = trade.evaluate(offer, unit)
            if dec == "accept":
                assert trade._qty_affordable(offer, unit) >= 1, (offer, unit)


def test_trade_offer_expires():
    """Заброшенный оффер тихо протухает через TTL (не выскакивает вечно)."""
    import time as _t
    from bot.game import trade, balance
    fresh = {"ts": _t.time()}
    old = {"ts": _t.time() - (balance.TRADE_OFFER_TTL_MIN * 60 + 5)}
    legacy = {"good": "ale1"}                    # старый оффер без метки
    assert trade.is_stale(fresh) is False
    assert trade.is_stale(old) is True
    assert trade.is_stale(legacy) is True        # без ts — протухший
    assert trade.is_stale(None) is False


def test_trade_stale_offer_resyncs_not_dead_error():
    """Устаревшее действие торга (оффер сменился на флаки-сети: продажа прошла,
    ответ потерялся, гости позвали нового купца) — РЕСИНК на актуальный оффер, а
    не мёртвая {ok:False,error:bad}, из-за которой игрок застревал с нерабочей
    вилкой (жалоба 05.07). Источник-гард в стиле test_shop_price_single_source."""
    import inspect
    from bot.webapi import tavern
    src = inspect.getsource(tavern._api_trade)
    # take без вилки ставит stale (не голую ошибку), и ответ несёт свежий trade
    assert 'result="stale"' in src, "take не ресинкает — вернётся мёртвая bad"
    assert '"trade": _trade_dto(ss.get_trade(p))' in src, "ответ без свежего оффера для ресинка"
    # оффера нет вовсе → мягкий walk с обновлением кассы, а не error:gone
    assert '"result": "walk"' in src and '"state": _tavern_state' in src
    # прежние тупики (error bad/gone на этих путях) — вычищены
    assert '{"ok": False, "error": "gone"}' not in src
    assert src.count('"error": "bad"') <= 1        # осталась лишь на битом idx (op=offer)
