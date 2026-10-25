"""Deterministic exit-ladder simulator + portfolio constraints.

Checks use candle CLOSE prices only (no intrabar highs/lows). Within one candle the order is:
stop loss -> take-profit rungs -> trailing stop -> time stop. Stop loss is checked first
(pessimistic). Latency: a decision at candle j is filled at candle min(j+L, last) price.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .config import Config
from .execution import buy_fill, net_after_side_costs, sell_fill
from .filters import find_entry_index
from .models import TokenLaunch


@dataclass
class Fill:
    t_min: float
    kind: str
    spot: float
    fill_price: float
    tokens: float
    net_usd: float


@dataclass
class Trade:
    address: str
    symbol: str
    platform: str
    entry_time: int  # epoch s of fill
    exit_time: int  # epoch s of last fill
    entry_age_min: float  # token age when the entry decision was made
    entry_price: float
    size_usd: float
    proceeds_usd: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str
    peak_multiple: float
    bundler_pct: float | None
    sniper_pct: float | None
    fills: list[Fill] = field(default_factory=list)


def simulate_trade(token: TokenLaunch, entry_idx: int, cfg: Config) -> Trade:
    ex, e = cfg.execution, cfg.exits
    L = ex.latency_candles
    cs = token.candles
    last = len(cs) - 1
    fi = entry_idx + L
    if fi >= last:
        raise ValueError("no room after fill")
    ref = cs[fi].price
    size = ex.position_size_usd
    bf = buy_fill(ref, size, token.liquidity_usd, ex.slippage_multiplier)
    invested_net = net_after_side_costs(size, ex.fee_pct, token.buy_tax_pct)
    tokens0 = invested_net / bf
    remaining = tokens0
    fills = [Fill(cs[fi].t_min, "buy", ref, bf, tokens0, -size)]
    proceeds = 0.0
    last_fill_idx = fi
    reason = "data_end"
    hit_tp = [False] * len(e.take_profits)
    trailing_on, peak = False, 0.0
    peak_mult = 1.0

    def sell(decision_idx: int, tokens: float, kind: str) -> None:
        nonlocal remaining, proceeds, last_fill_idx
        xi = min(decision_idx + L, last)
        spot = cs[xi].price
        fp = sell_fill(spot, tokens, token.liquidity_usd, ex.slippage_multiplier)
        net = net_after_side_costs(tokens * fp, ex.fee_pct, token.sell_tax_pct)
        proceeds += net
        remaining -= tokens
        last_fill_idx = max(last_fill_idx, xi)
        fills.append(Fill(cs[xi].t_min, kind, spot, fp, tokens, net))

    closed = False
    for j in range(fi + 1, last + 1):
        p = cs[j].price
        peak_mult = max(peak_mult, p / ref)
        if e.stop_loss_pct is not None and p <= ref * (1 - e.stop_loss_pct / 100):
            sell(j, remaining, "stop_loss")
            reason, closed = "stop_loss", True
            break
        for k, tp in enumerate(e.take_profits):
            if not hit_tp[k] and p >= ref * (1 + tp.at_gain_pct / 100):
                hit_tp[k] = True
                amt = min(remaining, tokens0 * tp.sell_fraction)
                if amt > 0:
                    sell(j, amt, f"tp_{tp.at_gain_pct:g}")
        if remaining <= tokens0 * 1e-12:
            reason, closed = "take_profit_full", True
            break
        if e.trailing is not None:
            if trailing_on:
                peak = max(peak, p)
                if p <= peak * (1 - e.trailing.drawdown_pct / 100):
                    sell(j, remaining, "trailing_stop")
                    reason, closed = "trailing_stop", True
                    break
            elif p >= ref * (1 + e.trailing.activate_gain_pct / 100):
                trailing_on, peak = True, p
        if e.time_stop_min is not None and cs[j].t_min - cs[fi].t_min >= e.time_stop_min:
            sell(j, remaining, "time_stop")
            reason, closed = "time_stop", True
            break
    if not closed:
        sell(last, remaining, "data_end")
    pnl = proceeds - size
    return Trade(
        address=token.address,
        symbol=token.symbol,
        platform=token.platform,
        entry_time=int(token.launch_time + cs[fi].t_min * 60),
        exit_time=int(token.launch_time + cs[last_fill_idx].t_min * 60),
        entry_age_min=cs[entry_idx].t_min,
        entry_price=ref,
        size_usd=size,
        proceeds_usd=proceeds,
        pnl_usd=pnl,
        pnl_pct=pnl / size * 100.0,
        exit_reason=reason,
        peak_multiple=peak_mult,
        bundler_pct=token.bundler_pct,
        sniper_pct=token.sniper_pct,
        fills=fills,
    )


@dataclass
class BacktestResult:
    trades: list[Trade]
    funnel: Counter
    blockers: Counter
    n_tokens: int


def run_backtest(tokens: list[TokenLaunch], cfg: Config) -> BacktestResult:
    funnel: Counter = Counter()
    blockers: Counter = Counter()
    cands: list[tuple[int, str, TokenLaunch, int]] = []
    for t in tokens:
        if len(t.candles) < 3:
            funnel["skipped_too_few_candles"] += 1
            continue
        idx, blk = find_entry_index(t, cfg.filters, cfg.execution.latency_candles)
        if idx is None:
            funnel["no_candle_passed_filters"] += 1
            for b in blk:
                blockers[b] += 1
            continue
        if not t.liquidity_usd or t.liquidity_usd <= 0:
            funnel["skipped_no_liquidity_data"] += 1
            continue
        fill_t = int(t.launch_time + t.candles[idx + cfg.execution.latency_candles].t_min * 60)
        cands.append((fill_t, t.address, t, idx))
    funnel["passed_filters"] = len(cands)
    cands.sort(key=lambda c: (c[0], c[1]))

    trades: list[Trade] = []
    pf = cfg.portfolio
    for fill_t, _, tok, idx in cands:
        if pf.max_concurrent is not None:
            open_n = sum(1 for tr in trades if tr.exit_time > fill_t)
            if open_n >= pf.max_concurrent:
                funnel["skipped_max_concurrent"] += 1
                continue
        if pf.daily_loss_stop_usd is not None:
            day = fill_t // 86400
            realised = sum(tr.pnl_usd for tr in trades if tr.exit_time <= fill_t and tr.exit_time // 86400 == day)
            if realised <= -pf.daily_loss_stop_usd:
                funnel["skipped_daily_loss_stop"] += 1
                continue
        trades.append(simulate_trade(tok, idx, cfg))
    funnel["traded"] = len(trades)
    return BacktestResult(trades, funnel, blockers, len(tokens))
