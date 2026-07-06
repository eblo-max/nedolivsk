"""Торг с купцом: дожим НИКОГДА не теряет купца (регресс жалобы «дожал — сбежал,
вернуло в начало»). Раньше жадный (greed≥0.75) на push с шансом 50% уходил."""
import os

os.environ.setdefault("BOT_TOKEN", "test:test")

import random  # noqa: E402

from bot.game import trade as t  # noqa: E402


def test_push_never_walks_any_greed():
    """При любой жадности и любом seed дожим возвращает только concede|hold — не walk."""
    for greed in (0.0, 0.3, 0.55, 0.7, 0.75, 0.9, 1.0):
        offer = {"greed": greed, "max_unit": 12.0, "counter": 8}
        outs = {t.push(dict(offer), random.Random(s))[0] for s in range(300)}
        assert outs <= {"concede", "hold"}, f"greed={greed}: дожим дал {outs}"
        assert "walk" not in outs


def test_push_generous_concedes_to_ceiling_then_holds():
    """Щедрый уступает до истинного потолка, потом упирается (не бесконечная уступка)."""
    offer = {"greed": 0.1, "max_unit": 12.0, "counter": 8}
    d1, p1 = t.push(offer)
    assert d1 == "concede" and p1 == 12               # довёл до потолка
    offer["counter"] = p1                             # уже на потолке
    d2, p2 = t.push(offer)
    assert d2 == "hold" and p2 == 12                  # дальше не уступает, но и не уходит


def test_push_greedy_holds_not_walks():
    """Жадный упирается на текущей контр-цене — сделка остаётся живой."""
    offer = {"greed": 0.95, "max_unit": 6.0, "counter": 6}
    for s in range(50):
        d, p = t.push(dict(offer), random.Random(s))
        assert d == "hold" and p == 6
