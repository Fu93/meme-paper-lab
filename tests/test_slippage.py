import pytest

from memelab.execution import buy_fill, net_after_side_costs, price_impact, sell_fill


def test_impact_formula():
    assert price_impact(100, 10_000) == pytest.approx(0.02)
    assert price_impact(100, 10_000, 2.0) == pytest.approx(0.04)
    assert price_impact(100, 10_000, 0.0) == 0.0


def test_impact_grows_with_size_and_shrinks_with_liquidity():
    assert price_impact(200, 10_000) > price_impact(100, 10_000)
    assert price_impact(100, 20_000) < price_impact(100, 10_000)


def test_unknown_liquidity_raises():
    for bad in (None, 0, -5):
        with pytest.raises(ValueError):
            price_impact(100, bad)


def test_buy_worse_sell_worse_than_spot():
    assert buy_fill(1.0, 100, 10_000, 1.0) == pytest.approx(1.02)
    assert sell_fill(1.0, 100, 10_000, 1.0) == pytest.approx(1 / 1.02)
    assert buy_fill(1.0, 100, 10_000, 0.0) == 1.0 and sell_fill(1.0, 100, 10_000, 0.0) == 1.0


def test_side_costs():
    assert net_after_side_costs(100, 1.0, 2.0) == pytest.approx(97.0)
    assert net_after_side_costs(100, 1.0, None) == pytest.approx(99.0)
