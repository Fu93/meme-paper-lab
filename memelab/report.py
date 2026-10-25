"""Report maths + Markdown/JSON rendering."""
from __future__ import annotations

import statistics
from typing import Any

from .config import Config, config_to_dict
from .simulator import BacktestResult, Trade

TOP_NS = (5, 10, 20)
AGE_EDGES = [0, 5, 15, 60, 240, float("inf")]
PCT_EDGES = [0, 5, 10, 20, 40, float("inf")]
CONCENTRATION_LIMIT = 0.80
SMALL_N = 30


def win_rate(pnls: list[float]) -> float | None:
    return sum(1 for p in pnls if p > 0) / len(pnls) if pnls else None


def ex_top_n(pnls: list[float], n: int) -> float | None:
    """Total PnL after removing the n best trades. None if there are not more than n trades."""
    if len(pnls) <= n:
        return None
    return sum(sorted(pnls, reverse=True)[n:])


def top_share(pnls: list[float], k: int = 10) -> float | None:
    """Sum of the k best trades / total PnL. None unless total PnL > 0 (the ratio is meaningless
    otherwise). Can exceed 1.0 when the remaining trades lose money."""
    total = sum(pnls)
    if not pnls or total <= 0:
        return None
    return sum(sorted(pnls, reverse=True)[:k]) / total


def max_drawdown(trades: list[Trade]) -> float:
    """Max peak-to-trough fall of cumulative realised PnL (USD), ordered by exit time,
    starting from 0. Returned as a positive number."""
    eq = peak = dd = 0.0
    for t in sorted(trades, key=lambda t: (t.exit_time, t.address)):
        eq += t.pnl_usd
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def bucket_label(lo: float, hi: float) -> str:
    return f"{lo:g}+" if hi == float("inf") else f"{lo:g}-{hi:g}"


def bucketize(trades: list[Trade], key, edges: list[float]) -> list[dict[str, Any]]:
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = [t.pnl_usd for t in trades if key(t) is not None and lo <= key(t) < hi]
        rows.append(_bucket_row(bucket_label(lo, hi), sel))
    rows.append(_bucket_row("unknown", [t.pnl_usd for t in trades if key(t) is None]))
    return [r for r in rows if r["n"] > 0]


def _bucket_row(label: str, pnls: list[float]) -> dict[str, Any]:
    return {
        "bucket": label,
        "n": len(pnls),
        "win_rate": win_rate(pnls),
        "median_pnl": statistics.median(pnls) if pnls else None,
        "total_pnl": sum(pnls),
        "small_sample": len(pnls) < SMALL_N,
    }


def compute_report(result: BacktestResult, cfg: Config, data_label: str = "") -> dict[str, Any]:
    trades = result.trades
    pnls = [t.pnl_usd for t in trades]
    total = sum(pnls)
    ex = {n: ex_top_n(pnls, n) for n in TOP_NS}
    share = top_share(pnls, 10)
    warnings: list[str] = []
    if share is not None and share > CONCENTRATION_LIMIT:
        warnings.append(
            f"Top-10 winners account for {share:.0%} of total PnL (> {CONCENTRATION_LIMIT:.0%}): "
            "results depend on a handful of outliers."
        )
    for n, v in ex.items():
        if v is not None and v < 0:
            warnings.append(f"PnL excluding the top {n} winners is negative ({v:+.2f} USD).")
    if len(trades) < SMALL_N:
        warnings.append(f"Only {len(trades)} trades: too few to say anything statistically.")
    return {
        "data_label": data_label,
        "tokens_in_dataset": result.n_tokens,
        "n_trades": len(trades),
        "position_size_usd": cfg.execution.position_size_usd,
        "win_rate": win_rate(pnls),
        "median_trade_usd": statistics.median(pnls) if pnls else None,
        "mean_trade_usd": statistics.fmean(pnls) if pnls else None,
        "total_pnl_usd": total,
        "pnl_ex_top_n_usd": {str(n): v for n, v in ex.items()},
        "top10_share_of_pnl": share,
        "max_drawdown_usd": max_drawdown(trades),
        "by_entry_age_min": bucketize(trades, lambda t: t.entry_age_min, AGE_EDGES),
        "by_bundler_pct": bucketize(trades, lambda t: t.bundler_pct, PCT_EDGES),
        "by_sniper_pct": bucketize(trades, lambda t: t.sniper_pct, PCT_EDGES),
        "exit_reasons": dict(sorted(_count(t.exit_reason for t in trades).items())),
        "funnel": dict(result.funnel),
        "blocking_filters": dict(result.blockers),
        "warnings": warnings,
        "config": config_to_dict(cfg),
    }


def _count(it) -> dict[str, int]:
    d: dict[str, int] = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


DISCLAIMER = (
    "Paper simulation only. Software output, not investment advice, no signal, no promise of "
    "returns. No real trades were made. You bear your own risk."
)


def _f(v, fmt="{:+.2f}"):
    return "n/a" if v is None else fmt.format(v)


def _pct(v):
    return "n/a" if v is None else f"{v:.1%}"


def render_markdown(rep: dict[str, Any]) -> str:
    L: list[str] = []
    label = rep["data_label"]
    L.append("# memelab paper report")
    L.append("")
    if label:
        L.append(f"> **DATA: {label}**")
        L.append("")
    L.append(f"> {DISCLAIMER}")
    L.append("")
    for w in rep["warnings"]:
        L.append(f"> **WARNING: {w}**")
    if rep["warnings"]:
        L.append("")
    L.append("## Summary (USD, simulated)")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---|")
    L.append(f"| tokens in dataset | {rep['tokens_in_dataset']} |")
    L.append(f"| trades | {rep['n_trades']} |")
    L.append(f"| position size | {rep['position_size_usd']:g} |")
    L.append(f"| win rate | {_pct(rep['win_rate'])} |")
    L.append(f"| median trade | {_f(rep['median_trade_usd'])} |")
    L.append(f"| mean trade | {_f(rep['mean_trade_usd'])} |")
    L.append(f"| total PnL | {_f(rep['total_pnl_usd'])} |")
    for n, v in rep["pnl_ex_top_n_usd"].items():
        L.append(f"| total PnL excluding top {n} winners | {_f(v)} |")
    L.append(f"| top-10 share of total PnL | {_pct(rep['top10_share_of_pnl']) if rep['top10_share_of_pnl'] is not None else 'n/a (total PnL <= 0)'} |")
    L.append(f"| max drawdown (realised, by exit time) | {rep['max_drawdown_usd']:.2f} |")
    L.append("")
    for title, key in (
        ("By token age at entry decision (minutes)", "by_entry_age_min"),
        ("By bundler % (supply)", "by_bundler_pct"),
        ("By sniper % (supply)", "by_sniper_pct"),
    ):
        L.append(f"## {title}")
        L.append("")
        L.append("| bucket | n | win rate | median | total PnL | note |")
        L.append("|---|---|---|---|---|---|")
        for r in rep[key]:
            note = f"small n (<{SMALL_N})" if r["small_sample"] else ""
            L.append(f"| {r['bucket']} | {r['n']} | {_pct(r['win_rate'])} | {_f(r['median_pnl'])} | {_f(r['total_pnl'])} | {note} |")
        L.append("")
    L.append("## Exits and funnel")
    L.append("")
    L.append("Exit reasons: " + ", ".join(f"{k}={v}" for k, v in rep["exit_reasons"].items()))
    L.append("")
    L.append("Funnel: " + ", ".join(f"{k}={v}" for k, v in sorted(rep["funnel"].items())))
    L.append("")
    if rep["blocking_filters"]:
        L.append("Filters that never passed on any evaluated candle (tokens blocked): "
                 + ", ".join(f"{k}={v}" for k, v in sorted(rep["blocking_filters"].items())))
        L.append("")
    L.append("## Caveats")
    L.append("")
    L.append("- Fills are idealised (close prices, static pool liquidity, no MEV, no failed txs). Real results would be worse.")
    L.append("- Static token attributes are snapshots applied to the whole timeline (possible look-ahead).")
    L.append("- Bucket tables slice a small sample many ways; differences are mostly noise.")
    L.append("- Built by an AI agent; not audited. " + DISCLAIMER)
    L.append("")
    return "\n".join(L)
