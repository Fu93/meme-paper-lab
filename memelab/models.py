"""Data model. All money is USD; all percentages are in percent units (5 = 5%)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candle:
    t_min: float  # minutes since launch
    price: float  # USD per token (close; the simulator only ever looks at this one number)
    progress_pct: float | None = None  # optional vendor-reported bonding-curve progress at this candle (0-100)


@dataclass
class TokenLaunch:
    address: str
    symbol: str
    launch_time: int  # epoch seconds (UTC)
    platform: str
    candles: list[Candle]
    total_supply: float = 1e9
    graduation_mcap_usd: float | None = None  # used only to derive bonding-curve "progress"
    liquidity_usd: float | None = None  # total pool value (both sides); STATIC snapshot
    holders: int | None = None  # STATIC snapshot
    top10_pct: float | None = None
    dev_pct: float | None = None
    sniper_pct: float | None = None
    insider_pct: float | None = None
    bundler_pct: float | None = None
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    dev_flags: tuple[str, ...] = ()
    synthetic: bool = False


@dataclass(frozen=True)
class Snapshot:
    """What the entry filters see at one candle. Static fields come from the token record."""

    age_min: float
    price: float
    mcap_usd: float
    progress_pct: float | None
    liquidity_usd: float | None
    holders: int | None
    top10_pct: float | None
    dev_pct: float | None
    sniper_pct: float | None
    insider_pct: float | None
    bundler_pct: float | None
    buy_tax_pct: float | None
    sell_tax_pct: float | None
    dev_flags: tuple[str, ...] = field(default_factory=tuple)


def snapshot_at(token: TokenLaunch, idx: int) -> Snapshot:
    c = token.candles[idx]
    mcap = c.price * token.total_supply
    progress = c.progress_pct
    if progress is None and token.graduation_mcap_usd:
        progress = min(100.0, mcap / token.graduation_mcap_usd * 100.0)
    return Snapshot(
        age_min=c.t_min,
        price=c.price,
        mcap_usd=mcap,
        progress_pct=progress,
        liquidity_usd=token.liquidity_usd,
        holders=token.holders,
        top10_pct=token.top10_pct,
        dev_pct=token.dev_pct,
        sniper_pct=token.sniper_pct,
        insider_pct=token.insider_pct,
        bundler_pct=token.bundler_pct,
        buy_tax_pct=token.buy_tax_pct,
        sell_tax_pct=token.sell_tax_pct,
        dev_flags=tuple(token.dev_flags),
    )
