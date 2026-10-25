"""Entry filters: pure functions, vocabulary modelled on Binance meme-rush style filters.

Rule for missing data: if a threshold is configured and the field is None, the filter FAILS
(fail closed). A threshold of None means "filter disabled".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Snapshot, TokenLaunch, snapshot_at


@dataclass
class FilterConfig:
    progress_min_pct: float | None = None
    progress_max_pct: float | None = None
    age_min_min: float | None = None
    age_max_min: float | None = None
    holders_min: int | None = None
    liquidity_min_usd: float | None = None
    top10_max_pct: float | None = None
    dev_max_pct: float | None = None
    sniper_max_pct: float | None = None
    insider_max_pct: float | None = None
    bundler_max_pct: float | None = None
    tax_max_pct: float | None = None
    mcap_min_usd: float | None = None
    mcap_max_usd: float | None = None
    exclude_dev_flags: list[str] = field(default_factory=list)


def at_least(value: float | None, threshold: float | None) -> bool:
    if threshold is None:
        return True
    if value is None:
        return False
    return value >= threshold


def at_most(value: float | None, threshold: float | None) -> bool:
    if threshold is None:
        return True
    if value is None:
        return False
    return value <= threshold


def f_progress(s: Snapshot, c: FilterConfig) -> bool:
    return at_least(s.progress_pct, c.progress_min_pct) and at_most(s.progress_pct, c.progress_max_pct)


def f_age(s: Snapshot, c: FilterConfig) -> bool:
    return at_least(s.age_min, c.age_min_min) and at_most(s.age_min, c.age_max_min)


def f_holders(s: Snapshot, c: FilterConfig) -> bool:
    return at_least(s.holders, c.holders_min)


def f_liquidity(s: Snapshot, c: FilterConfig) -> bool:
    return at_least(s.liquidity_usd, c.liquidity_min_usd)


def f_top10(s: Snapshot, c: FilterConfig) -> bool:
    return at_most(s.top10_pct, c.top10_max_pct)


def f_dev(s: Snapshot, c: FilterConfig) -> bool:
    return at_most(s.dev_pct, c.dev_max_pct)


def f_sniper(s: Snapshot, c: FilterConfig) -> bool:
    return at_most(s.sniper_pct, c.sniper_max_pct)


def f_insider(s: Snapshot, c: FilterConfig) -> bool:
    return at_most(s.insider_pct, c.insider_max_pct)


def f_bundler(s: Snapshot, c: FilterConfig) -> bool:
    return at_most(s.bundler_pct, c.bundler_max_pct)


def f_tax(s: Snapshot, c: FilterConfig) -> bool:
    if c.tax_max_pct is None:
        return True
    known = [t for t in (s.buy_tax_pct, s.sell_tax_pct) if t is not None]
    if not known:
        return False
    return max(known) <= c.tax_max_pct


def f_mcap(s: Snapshot, c: FilterConfig) -> bool:
    return at_least(s.mcap_usd, c.mcap_min_usd) and at_most(s.mcap_usd, c.mcap_max_usd)


def f_dev_flags(s: Snapshot, c: FilterConfig) -> bool:
    banned = {x.lower() for x in c.exclude_dev_flags}
    return not (banned & {x.lower() for x in s.dev_flags})


FILTERS = [
    ("progress", f_progress),
    ("age", f_age),
    ("holders", f_holders),
    ("liquidity", f_liquidity),
    ("top10", f_top10),
    ("dev", f_dev),
    ("sniper", f_sniper),
    ("insider", f_insider),
    ("bundler", f_bundler),
    ("tax", f_tax),
    ("mcap", f_mcap),
    ("dev_flags", f_dev_flags),
]


def failed_filters(s: Snapshot, c: FilterConfig) -> list[str]:
    return [name for name, fn in FILTERS if not fn(s, c)]


def passes_all(s: Snapshot, c: FilterConfig) -> bool:
    return not failed_filters(s, c)


def find_entry_index(
    token: TokenLaunch, c: FilterConfig, latency_candles: int = 0
) -> tuple[int | None, set[str]]:
    """First candle index where every filter passes AND a fill candle (idx+latency) exists
    that is not the last candle. Also returns the set of filters that never passed on any
    evaluated candle ("blocking filters"), used only for the funnel report.
    """
    n = len(token.candles)
    ever_passed: dict[str, bool] = {name: False for name, _ in FILTERS}
    evaluated = 0
    for i in range(n):
        if i + latency_candles >= n - 1:
            break  # no room to fill and then hold at least one candle
        s = snapshot_at(token, i)
        if c.age_max_min is not None and s.age_min > c.age_max_min:
            break
        evaluated += 1
        failed = failed_filters(s, c)
        for name, _ in FILTERS:
            if name not in failed:
                ever_passed[name] = True
        if not failed:
            return i, set()
    blockers = {name for name, ok in ever_passed.items() if not ok} if evaluated else set()
    return None, blockers
