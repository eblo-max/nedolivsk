"""Рычаги ценности аукциона: капризные премиум-гости + бонус за ассортимент."""

from types import SimpleNamespace

from bot.game import balance, logic, production


def _tavern(products, capacity=20, reputation=300):
    return SimpleNamespace(products=products, capacity=capacity, reputation=reputation)


# ── Рычаг 1: капризные состоятельные гости ──────────────────────────────────
def test_premium_leave_without_premium_drinks():
    t = _tavern({"ale1": 100000})                      # только дешёвое пойло (5)
    want, _unsold, left = logic._retail_demand(t, 8, 1.0, 1.0)
    assert left > 0                                    # богачи ушли несолоно
    assert want.get("ale1", 0) > 0                     # пьянь всё равно берёт дешёвое


def test_premium_satisfied_with_expensive_drink():
    t = _tavern({"ale3": 100000})                      # дорогое (15) — богачам есть что
    want, _unsold, left = logic._retail_demand(t, 8, 1.0, 1.0)
    assert left == 0                                   # всем налили
    assert want.get("ale3", 0) > 0


def test_premium_left_grows_with_reputation():
    cheap = {"ale1": 100000}
    _, _, lo = logic._retail_demand(_tavern(cheap, reputation=60), 8, 1.0, 1.0)
    _, _, hi = logic._retail_demand(_tavern(cheap, reputation=300), 8, 1.0, 1.0)
    assert hi > lo                                     # выше реп → больше ушедших богачей


def test_premium_threshold_is_the_cutoff():
    # ровно на пороге PREMIUM_MIN_PRICE напиток уже «премиум» и удерживает богачей
    prem = next(k for k, g in production.DRINKS.items()
                if g.price == balance.PREMIUM_MIN_PRICE)
    _, _, left = logic._retail_demand(_tavern({prem: 100000}), 8, 1.0, 1.0)
    assert left == 0


# ── Рычаг 2: бонус за ассортимент (по РЕАЛЬНО проданному, не по складу) ──────
def test_assortment_steps_up_by_sold_kinds():
    assert logic.assortment_mult({"ale1": 5}) == 1.0                  # один вид продан
    m3 = logic.assortment_mult({"ale1": 5, "bread": 5, "roast": 5})
    assert abs(m3 - (1 + 2 * balance.ASSORTMENT_STEP)) < 1e-9         # три вида


def test_assortment_capped_and_empty_safe():
    many = {g: 5 for g in list(production.GOODS)[:12]}
    assert logic.assortment_mult(many) == balance.ASSORTMENT_MAX      # потолок
    assert logic.assortment_mult(None) == 1.0
    assert logic.assortment_mult({}) == 1.0


def test_assortment_not_farmable_by_unsold_tokens():
    # 1 проданный вид = бонуса нет, даже если на складе лежат жетоны (склад не в счёт)
    assert logic.assortment_mult({"ale1": 100}) == 1.0


def test_assortment_raises_revenue_preview():
    player = SimpleNamespace(buff_kind=None, buff_until=None, tavern=None)
    sold_many = {"ale3": 2, "wine": 2, "pie": 2, "cheese": 2}         # четыре вида
    plain = logic.retail_total(sold_many)                            # базовая цена
    with_mult = logic.retail_total(sold_many, player)               # с ассортиментом
    assert logic.assortment_mult(sold_many) > 1.0
    assert with_mult > plain                                        # множитель применён
