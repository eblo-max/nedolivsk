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
