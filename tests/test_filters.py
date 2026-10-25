import pytest

from conftest import make_token
from memelab.filters import (FilterConfig, at_least, at_most, f_age, f_bundler, f_dev_flags, f_holders,
                             f_liquidity, f_mcap, f_progress, f_tax, failed_filters, find_entry_index, passes_all)
from memelab.models import snapshot_at


def snap(prices=(1.0, 2.0), idx=0, **kw):
    return snapshot_at(make_token(list(prices), **kw), idx)


def test_at_least_at_most_boundaries_and_missing():
    assert at_least(5, 5) and not at_least(4.99, 5) and at_least(None, None)
    assert at_most(5, 5) and not at_most(5.01, 5) and at_most(None, None)
    assert not at_least(None, 1) and not at_most(None, 1)  # fail closed


def test_empty_config_passes_everything():
    assert passes_all(snap(), FilterConfig())


def test_age_window():
    c = FilterConfig(age_min_min=5, age_max_min=10)
    assert not f_age(snap(idx=0), c)  # age 0
    assert f_age(snap(prices=(1, 1, 1), idx=1), c)  # age 5
    assert f_age(snap(prices=(1, 1, 1), idx=2), c)  # age 10
    assert not f_age(snap(prices=(1, 1, 1, 1), idx=3), c)  # age 15


def test_holders_liquidity():
    assert f_holders(snap(holders=100), FilterConfig(holders_min=100))
    assert not f_holders(snap(holders=99), FilterConfig(holders_min=100))
    assert not f_holders(snap(), FilterConfig(holders_min=1))  # missing -> fail
    assert f_liquidity(snap(liquidity=5000), FilterConfig(liquidity_min_usd=5000))
    assert not f_liquidity(snap(liquidity=4999), FilterConfig(liquidity_min_usd=5000))


def test_holding_pct_filters():
    c = FilterConfig(bundler_max_pct=20)
    assert f_bundler(snap(bundler_pct=20.0), c)
    assert not f_bundler(snap(bundler_pct=20.1), c)
    assert not f_bundler(snap(), c)
    for field, attr in [("top10_max_pct", "top10_pct"), ("dev_max_pct", "dev_pct"),
                        ("sniper_max_pct", "sniper_pct"), ("insider_max_pct", "insider_pct")]:
        cfg = FilterConfig(**{field: 10})
        assert passes_all(snap(**{attr: 10.0}), cfg)
        assert not passes_all(snap(**{attr: 10.5}), cfg)


def test_tax_uses_max_of_known_sides():
    c = FilterConfig(tax_max_pct=5)
    assert f_tax(snap(buy_tax_pct=1.0, sell_tax_pct=5.0), c)
    assert not f_tax(snap(buy_tax_pct=1.0, sell_tax_pct=5.5), c)
    assert f_tax(snap(buy_tax_pct=3.0), c)  # only one side known
    assert not f_tax(snap(), c)  # nothing known -> fail closed


def test_mcap_and_progress_derived():
    # supply 1000, price 2.0 -> mcap 2000; graduation 4000 -> progress 50
    s = snap(prices=(2.0, 2.0), graduation_mcap_usd=4000.0)
    assert s.mcap_usd == 2000.0 and s.progress_pct == 50.0
    assert f_mcap(s, FilterConfig(mcap_min_usd=2000, mcap_max_usd=2000))
    assert not f_mcap(s, FilterConfig(mcap_min_usd=2001))
    assert f_progress(s, FilterConfig(progress_min_pct=50, progress_max_pct=60))
    assert not f_progress(s, FilterConfig(progress_max_pct=49.9))
    assert not f_progress(snap(), FilterConfig(progress_min_pct=1))  # no graduation mcap -> unknown


def test_progress_capped_at_100():
    assert snap(prices=(100.0, 1.0), graduation_mcap_usd=10.0).progress_pct == 100.0


def test_dev_flags_case_insensitive():
    c = FilterConfig(exclude_dev_flags=["Honeypot"])
    assert not f_dev_flags(snap(dev_flags=("honeypot",)), c)
    assert f_dev_flags(snap(dev_flags=("dev_sold",)), c)


def test_failed_filters_names():
    c = FilterConfig(holders_min=100, bundler_max_pct=10)
    assert failed_filters(snap(holders=5, bundler_pct=50.0), c) == ["holders", "bundler"]


def test_find_entry_first_passing_candle_and_room():
    tok = make_token([1, 1, 1, 1, 1], holders=10)
    assert find_entry_index(tok, FilterConfig(age_min_min=10))[0] == 2
    # latency 2: decision idx must satisfy idx+2 < last(4) -> idx<=1; age 10 is idx 2 -> none
    idx, _ = find_entry_index(tok, FilterConfig(age_min_min=10), latency_candles=2)
    assert idx is None


def test_find_entry_reports_blockers():
    tok = make_token([1, 1, 1], holders=10)
    idx, blockers = find_entry_index(tok, FilterConfig(holders_min=100, liquidity_min_usd=1))
    assert idx is None and blockers == {"holders"}


def test_age_max_stops_search():
    tok = make_token([1, 1, 1, 1], holders=10)
    idx, _ = find_entry_index(tok, FilterConfig(age_max_min=5, mcap_min_usd=1e9))
    assert idx is None
