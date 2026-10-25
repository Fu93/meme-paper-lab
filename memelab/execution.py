"""Fill assumptions. Idealised: see README limitations."""
from __future__ import annotations


def price_impact(size_usd: float, liquidity_usd: float | None, multiplier: float = 1.0) -> float:
    """Constant-product estimate. Pool of total value L has quote reserve R = L/2.
    Buying `size` of quote moves the average execution price by (1 + size/R).
    Selling tokens worth `size` at spot gets average price spot/(1 + size/R) (to first order).
    Returns the fraction `impact = multiplier * size / (L/2)`; buy price = spot*(1+impact),
    sell price = spot/(1+impact). Raises ValueError if liquidity is unknown/non-positive.
    """
    if liquidity_usd is None or liquidity_usd <= 0:
        raise ValueError("liquidity unknown or non-positive")
    return multiplier * size_usd / (liquidity_usd / 2.0)


def buy_fill(spot: float, size_usd: float, liquidity_usd: float | None, multiplier: float) -> float:
    return spot * (1.0 + price_impact(size_usd, liquidity_usd, multiplier))


def sell_fill(spot: float, tokens: float, liquidity_usd: float | None, multiplier: float) -> float:
    impact = price_impact(tokens * spot, liquidity_usd, multiplier)
    return spot / (1.0 + impact)


def net_after_side_costs(gross_usd: float, fee_pct: float, tax_pct: float | None) -> float:
    return gross_usd * (1.0 - fee_pct / 100.0 - (tax_pct or 0.0) / 100.0)
