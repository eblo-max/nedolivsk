"""Репутация-«молва»: накопитель остатка, пороги, прогресс-строка, вес аукциона.

Прод-боль: «продаю, а репутация не растёт» — мелкие продажи терялись (целочисленное
деление на 25). Теперь очки копятся, остаток не пропадает, порог ниже.
"""

from types import SimpleNamespace

from bot.game import balance, logic


def _tavern():
    return SimpleNamespace(reputation=0, rep_progress=0, auction_sold=0)


def _player():
    return SimpleNamespace(reputation=0)


def test_remainder_accumulates_no_loss():
    p, t = _player(), _tavern()
    # 5 порций гостям (×2 очка) = 10 — порога (24) ещё нет
    assert logic.add_goods_rep_progress(p, t, 5 * balance.REP_POINTS_RETAIL) == 0
    assert p.reputation == 0 and t.rep_progress == 10
    # ещё 8 порций = +16 → 26 ≥ 24 → +1 реп, остаток 2 (НЕ потерян)
    assert logic.add_goods_rep_progress(p, t, 8 * balance.REP_POINTS_RETAIL) == 1
    assert p.reputation == 1 and t.reputation == 1 and t.rep_progress == 2


def test_progress_line_counts_down():
    t = _tavern()
    # пустой прогресс: до +1 нужно 24 очка / 2 за порцию = 12 порций
    assert logic.retail_rep_left(t) == 12
    t.rep_progress = 2
    assert logic.retail_rep_left(t) == 11           # ceil((24-2)/2)


def test_auction_weight_is_weaker_than_retail():
    # аукцион даёт меньше очков за единицу, чем сбыт гостям
    assert balance.REP_POINTS_AUCTION < balance.REP_POINTS_RETAIL
    p, t = _player(), _tavern()
    # 24 ед. на бирже (×1) = ровно один порог → +1 реп
    assert logic.add_goods_rep_progress(p, t, 24 * balance.REP_POINTS_AUCTION) == 1
    assert p.reputation == 1


def test_big_sale_grants_multiple_points():
    p, t = _player(), _tavern()
    # 36 порций ×2 = 72 очка = 3 порога → +3 репутации, остаток 0
    assert logic.add_goods_rep_progress(p, t, 36 * balance.REP_POINTS_RETAIL) == 3
    assert p.reputation == 3 and t.rep_progress == 0
