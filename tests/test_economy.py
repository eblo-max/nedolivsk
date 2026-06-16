"""Экономика: биржевой налог-консервация и границы рыночного множителя."""

from bot.game import balance, bourse, market
from conftest import make_world


def test_bourse_tax_conserves():
    for gross in (1, 10, 100, 999, 5000):
        net = bourse.net_to_seller(gross)
        tax = bourse.tax_amount(gross)
        assert net + tax == gross                 # ничего не теряется/создаётся
        assert 0 <= tax <= gross
        assert net <= gross                        # продавец получает не больше брутто


def test_market_factor_neutral_on_fresh_world():
    w = make_world()
    for good in ("ale1", "ale2", "mead", "bread"):
        if good in __import__("bot.game.production", fromlist=["GOODS"]).GOODS:
            assert abs(market.factor(w, good) - 1.0) < 1e-6


def test_market_factor_within_bounds_under_extremes():
    from bot.game.production import GOODS
    good = next(iter(GOODS))
    # завал рынка -> к полу, дефицит -> к потолку, но всегда в коридоре
    glut = make_world(market={good: 10 ** 7, "_t": "2099-01-01T00:00:00+00:00"})
    short = make_world(market={good: -10 ** 7, "_t": "2099-01-01T00:00:00+00:00"})
    fg, fs = market.factor(glut, good), market.factor(short, good)
    assert balance.MARKET_PRICE_FLOOR <= fg <= balance.MARKET_PRICE_CEIL
    assert balance.MARKET_PRICE_FLOOR <= fs <= balance.MARKET_PRICE_CEIL
    assert fg < 1.0 < fs                            # завал дешевле, дефицит дороже


def test_bourse_price_corridor():
    from bot.game.production import GOODS
    good = next(iter(GOODS))
    assert bourse.price_floor(good) <= bourse.base_price(good) <= bourse.price_ceil(good)
    assert bourse.valid_price(good, bourse.base_price(good))
    assert not bourse.valid_price(good, 0)
