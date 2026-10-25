import pytest

from conftest import make_cfg, make_token
from memelab.simulator import run_backtest, simulate_trade

# All hand-computed cases: size 100, price 1.0 at the fill candle => 100 tokens.


def sim(prices, **kw):
    return simulate_trade(make_token(prices), 0, make_cfg(**kw))


def test_partial_take_profit_then_data_end():
    t = sim([1, 1.5, 2.0, 1.2, 1.0], tps=[(100, 0.5)], stop=50)
    # 50 tokens @2.0 = 100 ; remaining 50 tokens @1.0 (end of data) = 50
    assert t.proceeds_usd == pytest.approx(150) and t.pnl_usd == pytest.approx(50)
    assert t.exit_reason == "data_end"
    assert [f.kind for f in t.fills] == ["buy", "tp_100", "data_end"]


def test_stop_loss_exact_boundary():
    t = sim([1, 0.8, 0.5, 0.9], stop=50)
    assert t.exit_reason == "stop_loss"
    assert t.pnl_usd == pytest.approx(-50)  # 100 tokens @ 0.5


def test_stop_loss_not_triggered_just_above():
    t = sim([1, 0.8, 0.51, 0.9], stop=50)
    assert t.exit_reason == "data_end" and t.pnl_usd == pytest.approx(-10)


def test_trailing_stop_sells_rest():
    t = sim([1, 2, 3, 4, 2.0, 1.0], trailing=(200, 50))
    # activates at 3 (peak 3), peak 4, sells at 2.0 = 4*0.5 : 100 tokens * 2 = 200
    assert t.exit_reason == "trailing_stop" and t.pnl_usd == pytest.approx(100)


def test_trailing_does_not_fire_on_activation_candle():
    t = sim([1, 3.0, 3.0, 3.0], trailing=(200, 10))
    assert t.exit_reason == "data_end"


def test_full_ladder_tp_trailing_combo():
    t = sim([1, 2, 3, 5, 2.5, 1], tps=[(100, 0.5)], stop=50, trailing=(200, 50))
    # tp: 50 tokens @2 = 100 ; trailing peak 5 -> trigger 2.5: 50 tokens @2.5 = 125
    assert t.proceeds_usd == pytest.approx(225) and t.pnl_usd == pytest.approx(125)
    assert t.exit_reason == "trailing_stop"


def test_two_take_profit_rungs_in_one_candle_gap():
    t = sim([1, 4.0, 4.0], tps=[(100, 0.25), (200, 0.25)])
    # gap to 4.0 hits both rungs: 25@4 + 25@4 = 200, remaining 50 @4 at end = 200 -> 400
    assert t.proceeds_usd == pytest.approx(400)


def test_full_take_profit_closes_position():
    t = sim([1, 2, 0.1], tps=[(100, 1.0)])
    assert t.exit_reason == "take_profit_full" and t.pnl_usd == pytest.approx(100)


def test_time_stop():
    t = sim([1, 1.1, 1.2, 1.3, 1.4], time_stop=10)
    assert t.exit_reason == "time_stop" and t.pnl_usd == pytest.approx(20)  # sold at idx2 (10 min)


def test_stop_takes_priority_over_tp_in_same_candle_logic():
    # price can't be both <=stop and >=tp in one candle; check stop wins when it fires first
    t = sim([1, 0.4, 3.0], tps=[(100, 0.5)], stop=50)
    assert t.exit_reason == "stop_loss" and t.pnl_usd == pytest.approx(-60)


def test_latency_delays_entry_and_exit_fill():
    tok = make_token([9, 1, 1, 0.5, 0.25, 0.25])
    t = simulate_trade(tok, 0, make_cfg(stop=50, latency=1))
    # decision idx0 -> fill idx1 (ref 1.0). stop decision idx3 (0.5) -> fill idx4 @0.25 -> 25
    assert t.entry_price == 1.0 and t.pnl_usd == pytest.approx(-75)
    assert t.fills[-1].fill_price == pytest.approx(0.25)


def test_fees_and_taxes_per_side():
    tok = make_token([1, 2, 2], buy_tax_pct=2.0, sell_tax_pct=3.0)
    t = simulate_trade(tok, 0, make_cfg(fee=1.0))
    # buy: 100*(1-.01-.02)=97 tokens @1 ; sell 97*2=194*(1-.01-.03)=186.24
    assert t.proceeds_usd == pytest.approx(186.24) and t.pnl_usd == pytest.approx(86.24)


def test_slippage_applied_both_sides():
    tok = make_token([1, 2, 2], liquidity=10_000)
    t = simulate_trade(tok, 0, make_cfg(slip=1.0))
    # R=5000. buy impact .02 -> fill 1.02, tokens 98.0392157. sell value 196.0784, impact .0392157,
    # sell price 2/1.0392157=1.9245283 -> proceeds 188.67925
    assert t.fills[0].fill_price == pytest.approx(1.02)
    assert t.proceeds_usd == pytest.approx(188.67925, abs=1e-4)


def test_deterministic():
    tok = make_token([1, 2, 3, 0.4, 5, 1])
    cfg = make_cfg(tps=[(100, 0.5)], stop=50, trailing=(200, 35), fee=1, slip=1)
    a, b = simulate_trade(tok, 0, cfg), simulate_trade(tok, 0, cfg)
    assert a == b


def test_no_room_raises():
    with pytest.raises(ValueError):
        simulate_trade(make_token([1, 1]), 0, make_cfg(latency=1))


# ---- portfolio constraints -------------------------------------------------

def _tok(addr, launch, prices):
    return make_token(prices, addr=addr, launch=launch)


def test_max_concurrent_skips_overlapping_entry():
    a = _tok("0xA", 0, [1, 1, 1, 1, 1])  # open 0..20min (data_end)
    b = _tok("0xB", 600, [1, 1, 1, 1, 1])  # fill at t=600s, A exits at 1200s -> overlap
    c = _tok("0xC", 5000, [1, 1, 1, 1, 1])  # after both
    res = run_backtest([a, b, c], make_cfg(max_conc=1))
    assert [t.address for t in res.trades] == ["0xA", "0xC"]
    assert res.funnel["skipped_max_concurrent"] == 1


def test_unlimited_concurrency_by_default():
    toks = [_tok(f"0x{i}", i * 60, [1, 1, 1, 1]) for i in range(3)]
    assert len(run_backtest(toks, make_cfg()).trades) == 3


def test_daily_loss_stop_blocks_same_day_only():
    loser = _tok("0xA", 0, [1, 0.4, 0.4])  # stop-loss -> -60
    same_day = _tok("0xB", 3600, [1, 1, 1])  # after A closed (A closes at 5 min)
    next_day = _tok("0xC", 86400 + 3600, [1, 1, 1])
    res = run_backtest([loser, same_day, next_day], make_cfg(stop=50, daily=50))
    assert [t.address for t in res.trades] == ["0xA", "0xC"]
    assert res.funnel["skipped_daily_loss_stop"] == 1


def test_daily_loss_stop_ignores_unrealised_and_small_losses():
    loser = _tok("0xA", 0, [1, 0.4, 0.4])  # -60
    later = _tok("0xB", 3600, [1, 1, 1])
    assert len(run_backtest([loser, later], make_cfg(stop=50, daily=61)).trades) == 2


def test_missing_liquidity_skipped_not_crashed():
    tok = make_token([1, 1, 1, 1], liquidity=None)
    res = run_backtest([tok], make_cfg())
    assert res.trades == [] and res.funnel["skipped_no_liquidity_data"] == 1


def test_daily_loss_stop_boundary_is_inclusive():
    loser = _tok("0xA", 0, [1, 0.5, 0.5])  # stop at 0.5 -> exactly -50
    later = _tok("0xB", 3600, [1, 1, 1])
    assert len(run_backtest([loser, later], make_cfg(stop=50, daily=50)).trades) == 1
    assert len(run_backtest([loser, later], make_cfg(stop=50, daily=50.01)).trades) == 2
