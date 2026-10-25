import json

import pytest

from conftest import make_cfg
from memelab.report import (bucketize, compute_report, ex_top_n, max_drawdown, render_markdown, top_share,
                            win_rate)
from memelab.simulator import BacktestResult, Trade
from collections import Counter


def trade(pnl, exit_time=0, age=10.0, bundler=None, sniper=None, addr="0x"):
    return Trade(address=addr, symbol="S", platform="P", entry_time=0, exit_time=exit_time,
                 entry_age_min=age, entry_price=1, size_usd=100, proceeds_usd=100 + pnl, pnl_usd=pnl,
                 pnl_pct=pnl, exit_reason="x", peak_multiple=1, bundler_pct=bundler, sniper_pct=sniper)


def result(trades):
    return BacktestResult(trades, Counter(), Counter(), len(trades))


def test_win_rate_median_mean_total():
    ts = [trade(p) for p in (-50, -50, 10, 100)]
    rep = compute_report(result(ts), make_cfg())
    assert rep["win_rate"] == 0.5
    assert rep["median_trade_usd"] == -20
    assert rep["mean_trade_usd"] == pytest.approx(2.5)
    assert rep["total_pnl_usd"] == 10


def test_win_rate_empty():
    assert win_rate([]) is None


def test_ex_top_n():
    pnls = [100, 50, 10, -20, -30]
    assert ex_top_n(pnls, 1) == 10 - 20 - 30 + 50
    assert ex_top_n(pnls, 2) == -40
    assert ex_top_n(pnls, 5) is None  # nothing left
    assert ex_top_n(pnls, 9) is None


def test_top_share():
    pnls = [100, 50, -50]
    assert top_share(pnls, 1) == pytest.approx(100 / 100)
    assert top_share(pnls, 2) == pytest.approx(150 / 100)  # can exceed 100%
    assert top_share([-5, -1], 1) is None  # total <= 0
    assert top_share([], 10) is None


def test_max_drawdown_by_exit_time():
    ts = [trade(50, 1), trade(-30, 2), trade(-40, 3), trade(100, 4), trade(-10, 5)]
    # equity: 50, 20, -20, 80, 70 ; peak 50 -> trough -20 => 70
    assert max_drawdown(ts) == 70
    assert max_drawdown([trade(-10, 1), trade(-5, 2)]) == 15  # drawdown measured from 0 start
    assert max_drawdown([]) == 0
    # order of input must not matter
    assert max_drawdown(list(reversed(ts))) == 70


def test_buckets_age_and_unknown():
    ts = [trade(10, age=1), trade(-5, age=4.99), trade(7, age=5), trade(1, age=300), trade(3, bundler=None)]
    rows = {r["bucket"]: r for r in bucketize(ts, lambda t: t.entry_age_min, [0, 5, 15, 60, 240, float("inf")])}
    assert rows["0-5"]["n"] == 2 and rows["0-5"]["total_pnl"] == 5
    assert rows["5-15"]["n"] == 2 and rows["240+"]["n"] == 1
    assert rows["0-5"]["small_sample"] is True
    unk = bucketize(ts, lambda t: t.bundler_pct, [0, 10, float("inf")])
    assert unk[0]["bucket"] == "unknown" and unk[0]["n"] == 5


def test_warning_concentration_over_80pct():
    ts = [trade(1000)] + [trade(-1) for _ in range(40)] + [trade(1) for _ in range(40)]
    # total = 1000 - 40 + 40 = 1000; top10 = 1000 + 9 = 1009 -> 100.9%
    rep = compute_report(result(ts), make_cfg())
    assert rep["top10_share_of_pnl"] > 0.8
    assert any("Top-10 winners" in w for w in rep["warnings"])
    assert "WARNING: Top-10 winners" in render_markdown(rep)


def test_warning_ex_top_n_negative():
    ts = [trade(500)] + [trade(-10) for _ in range(40)]
    rep = compute_report(result(ts), make_cfg())
    assert rep["pnl_ex_top_n_usd"]["5"] < 0
    assert any("excluding the top 5" in w for w in rep["warnings"])


def test_no_warning_when_spread_out():
    ts = [trade(10) for _ in range(60)] + [trade(-5) for _ in range(40)]
    rep = compute_report(result(ts), make_cfg())
    assert rep["top10_share_of_pnl"] == pytest.approx(100 / 400)
    assert rep["warnings"] == []


def test_few_trades_warning_and_json_roundtrip():
    rep = compute_report(result([trade(1)]), make_cfg(), "SYNTHETIC")
    assert any("too few" in w for w in rep["warnings"])
    json.dumps(rep, default=str)
    md = render_markdown(rep)
    assert "SYNTHETIC" in md and "not investment advice" in md
