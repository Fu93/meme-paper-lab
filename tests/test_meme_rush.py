"""Offline tests for the optional Binance meme-rush source. Fixtures in tests/fixtures are RECORDED real
responses (BSC, trimmed to 2 rows each, 2026-10-25). No test touches the network."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from memelab import fetch_meme_rush as fm
from memelab.cli import main
from memelab.data import DataError, load_tokens, tokens_to_json
from memelab.filters import FilterConfig, passes_all as passes
from memelab.models import Candle, TokenLaunch, snapshot_at

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent


def fx(name):
    return json.loads((FIX / name).read_text())


def fake_http(by_rank, calls=None):
    def http(url, body, timeout):
        if calls is not None:
            calls.append((url, body, timeout))
        v = by_rank[body["rankType"]]
        return v if isinstance(v, fm.HttpResult) else fm.HttpResult(200, v)
    return http


# ------------------------------------------------------------------ parser

def test_numeric_helpers_unknown_stays_none():
    assert fm._f("42.5") == 42.5 and fm._f(3) == 3.0
    for bad in (None, "", "abc", "nan", "inf", True, [], {}):
        assert fm._f(bad) is None
    assert fm._i("368") == 368 and fm._i(None) is None


def test_map_token_rank20_fields():
    raw = fx("meme_rush_bsc_rank20.json")["data"][0]
    r = fm.map_token(raw, "56", 20, 1_792_960_000)
    assert r["address"] == raw["contractAddress"] and r["symbol"] == "BNC Coin"
    assert r["platform"] == "Four.meme" and r["protocol"] == 2001
    assert r["create_ts"] == 1792905114 and r["migrated"] is False
    assert r["price"] == pytest.approx(0.00002510669281533315)
    assert r["mcap"] == pytest.approx(25106.7) and r["progress_pct"] == pytest.approx(86.438267)
    assert r["liquidity_usd"] == pytest.approx(12367.04625241286) and r["holders"] == 368
    assert r["top10_pct"] == pytest.approx(68.29762442851847)  # percent units, NOT multiplied by 100
    assert r["dev_pct"] == pytest.approx(66.69100873572272)
    assert r["sniper_pct"] == pytest.approx(66.69100873572299)
    assert r["bundler_pct"] == 0.0
    assert r["insider_pct"] is None  # null upstream -> unknown
    assert r["buy_tax_pct"] is None and r["sell_tax_pct"] is None  # unknown tax is NOT 0
    assert r["dev_flags"] == []  # null tags mean "not evaluated"
    assert r["trades_24h"] == 490 and r["sniper_count"] == 1


def test_map_token_migrated_and_tax():
    raw = fx("meme_rush_bsc_rank30.json")["data"][0]
    r = fm.map_token(raw, "56", 30, 1_792_960_000)
    assert r["migrated"] is True and r["progress_pct"] == 100.0
    assert r["platform"] == "Flap" and r["buy_tax_pct"] == 1.0 and r["sell_tax_pct"] == 1.0
    assert r["insider_pct"] == pytest.approx(0.001196142037293602)


def test_map_token_new_launch_tax_and_tiny_values():
    r = fm.map_token(fx("meme_rush_bsc_rank10.json")["data"][0], "56", 10, 1_792_958_300)
    assert r["holders"] == 1 and r["buy_tax_pct"] == 10.0
    assert r["progress_pct"] == pytest.approx(0.000047)


def test_wash_trading_tags_become_flags():
    raw = dict(fx("meme_rush_bsc_rank20.json")["data"][0], tagDevWashTrading=1, tagInsiderWashTrading=1)
    assert fm.map_token(raw, "56", 20, 1)["dev_flags"] == ["dev_wash_trading", "insider_wash_trading"]
    raw["tagDevWashTrading"] = 0
    assert fm.map_token(raw, "56", 20, 1)["dev_flags"] == ["insider_wash_trading"]


@pytest.mark.parametrize("patch", [{"contractAddress": None}, {"createTime": None}, {"createTime": 0}, {"createTime": "x"}])
def test_map_token_rejects_unplaceable_rows(patch):
    raw = dict(fx("meme_rush_bsc_rank20.json")["data"][0], **patch)
    assert fm.map_token(raw, "56", 20, 1) is None
    assert fm.map_token("junk", "56", 20, 1) is None


def test_null_price_kept_as_unknown_not_zero():
    raw = dict(fx("meme_rush_bsc_rank20.json")["data"][0], price=None, marketCap=None, holders=None)
    r = fm.map_token(raw, "56", 20, 1)
    assert r["price"] is None and r["mcap"] is None and r["holders"] is None
    assert fm.map_token(dict(raw, price="0"), "56", 20, 1)["price"] is None


def test_parse_response_envelope():
    recs = fm.parse_response(fx("meme_rush_bsc_rank20.json"), "56", 20, 5)
    assert len(recs) == 2
    assert fm.parse_response({"code": "000000", "data": None, "success": True}, "56", 10, 1) == []
    with pytest.raises(DataError, match="100004"):
        fm.parse_response(fx("meme_rush_error_100004.json"), "56", 10, 1)
    with pytest.raises(DataError):
        fm.parse_response([], "56", 10, 1)
    with pytest.raises(DataError):
        fm.parse_response({"code": "000000", "data": {"a": 1}}, "56", 10, 1)


# ------------------------------------------------------------------ polling

def good_http(calls=None):
    return fake_http({r: fx(f"meme_rush_bsc_rank{r}.json") for r in (10, 20, 30)}, calls)


def test_poll_once_ok_caches_raw_and_dedups(tmp_path):
    calls, sleeps = [], []
    s = fm.poll_once(["56"], [10, 20, 30], 50, tmp_path, delay_s=2.0, http=good_http(calls), sleep=sleeps.append,
                     now=lambda: 1_792_960_000)
    assert s.requests == 3 and len(s.records) == 6 and not s.errors
    assert s.counts == {"56/10": 2, "56/20": 2, "56/30": 2}
    assert sleeps == [2.0, 2.0]  # rate limit between requests, none before the first
    assert all(c[0] == fm.URL and c[2] == fm.TIMEOUT_S for c in calls)
    assert calls[0][1] == {"chainId": "56", "rankType": 10, "limit": 50}
    raw = sorted(p.name for p in tmp_path.iterdir())
    assert raw == ["1792960000_56_10.json", "1792960000_56_20.json", "1792960000_56_30.json"]
    doc = json.loads((tmp_path / raw[1]).read_text())
    assert doc["http_status"] == 200 and doc["response"]["code"] == "000000" and doc["request_body"]["rankType"] == 20


def test_poll_once_dedups_same_token_across_lists():
    same = fx("meme_rush_bsc_rank20.json")
    s = fm.poll_once(["56"], [20, 30], 10, None, http=fake_http({20: same, 30: same}), sleep=lambda x: None)
    assert len(s.records) == 2 and {r["rank_type"] for r in s.records} == {20}


def test_poll_stops_on_auth_and_does_not_retry():
    calls = []
    http = fake_http({10: fm.HttpResult(403, {"code": "x"}, "HTTP 403")}, calls)
    s = fm.poll_once(["56"], [10, 20, 30], 5, None, http=http, sleep=lambda x: None)
    assert s.blocked_auth and len(calls) == 1 and "not working around" in s.errors[0]


def test_poll_stops_on_rate_limit():
    calls = []
    http = fake_http({10: fx("meme_rush_error_100004.json")}, calls)
    s = fm.poll_once(["56"], [10, 20], 5, None, http=http, sleep=lambda x: None)
    assert s.rate_limited and len(calls) == 1 and not s.records


def test_poll_survives_network_error_and_bad_json_shape():
    http = fake_http({10: fm.HttpResult(None, None, "TimeoutError"), 20: {"code": "000000", "data": "oops"},
                      30: fx("meme_rush_bsc_rank30.json")})
    s = fm.poll_once(["56"], [10, 20, 30], 5, None, http=http, sleep=lambda x: None)
    assert len(s.errors) == 2 and len(s.records) == 2 and s.requests == 3 and not s.blocked_auth


def test_raw_cache_failure_is_ignored(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    s = fm.poll_once(["56"], [30], 5, blocker / "sub", http=good_http(), sleep=lambda x: None)
    assert len(s.records) == 2


@pytest.mark.parametrize("kw", [
    dict(chains=["1"]), dict(ranks=[40]), dict(limit=0), dict(limit=101), dict(delay_s=0.5),
    dict(interval_s=10), dict(count=0), dict(chains=[]),
])
def test_validate_params_rejects(kw):
    args = dict(chains=["56"], ranks=[10], limit=50, interval_s=60, count=1, delay_s=1.0)
    args.update(kw)
    with pytest.raises(DataError):
        fm.validate_params(**args)


def test_run_snapshots_interval_append_and_jsonl(tmp_path):
    clock = [1_792_960_000.0]
    sleeps = []

    def sleep(x):
        sleeps.append(x)
        clock[0] += x

    out = tmp_path / "s.jsonl"
    logs = []
    sums = fm.run_snapshots(120, 3, out, raw_dir=tmp_path / "raw", http=good_http(), sleep=sleep,
                            now=lambda: clock[0], log=logs.append)
    assert len(sums) == 3 and len(logs) == 3
    lines = out.read_text().splitlines()
    assert len(lines) == 18 and all(json.loads(l)["source"] == fm.SOURCE for l in lines)
    assert [s.poll_ts for s in sums] == [1_792_960_000, 1_792_960_120, 1_792_960_240]  # start-to-start spacing
    # appending a second run keeps earlier rows
    fm.run_snapshots(60, 1, out, http=good_http(), sleep=sleep, now=lambda: clock[0], log=lambda m: None)
    assert len(out.read_text().splitlines()) == 24


def test_run_snapshots_stops_after_auth_block(tmp_path):
    http = fake_http({10: fm.HttpResult(401, None, "HTTP 401")})
    logs = []
    sums = fm.run_snapshots(60, 5, tmp_path / "s.jsonl", http=http, sleep=lambda x: None, log=logs.append)
    assert len(sums) == 1 and not (tmp_path / "s.jsonl").exists() and "authentication" in logs[-1]


def test_http_post_json_never_raises_on_bad_host():
    r = fm.http_post_json("http://127.0.0.1:9/none", {}, timeout=0.5)
    assert r.status is None and r.error


# ------------------------------------------------------------------ dataset build

def make_records():
    base = fx("meme_rush_bsc_rank20.json")["data"][0]
    create = base["createTime"] // 1000
    recs = []
    for i, (price, prog, holders, top10) in enumerate([(1e-5, 40.0, None, None), (2e-5, 50.0, 100, 30.0), (3e-5, 60.0, 120, 35.0)]):
        raw = dict(base, price=str(price), progress=str(prog), holders=holders,
                   holdersTop10Percent=None if top10 is None else str(top10), marketCap=str(price * 1e9))
        recs.append(fm.map_token(raw, "56", 20, create + 600 + 120 * i))
    return recs, create


def test_build_tokens_candles_progress_static_and_lookahead():
    recs, create = make_records()
    toks, st = fm.build_tokens(list(reversed(recs)))  # order-independent
    assert len(toks) == 1
    t = toks[0]
    assert t.launch_time == create and t.platform == "Four.meme/56"
    assert [c.t_min for c in t.candles] == [10.0, 12.0, 14.0]
    assert [c.progress_pct for c in t.candles] == [40.0, 50.0, 60.0]
    assert t.holders == 100 and t.top10_pct == 30.0  # first NON-NULL value
    assert t.total_supply == pytest.approx(1e9, rel=1e-6)
    assert t.buy_tax_pct is None  # unknown stays unknown
    assert st.late_static["holders"] == 1 and st.late_static["top10_pct"] == 1
    assert st.never_known["buy_tax_pct"] == 1 and st.n_tokens_multi_candle == 1


def test_build_tokens_skips_priceless_and_multi_chain_keys():
    recs, _ = make_records()
    for r in recs:
        r["price"] = None
    assert fm.build_tokens(recs)[0] == []
    recs, _ = make_records()
    sol = [dict(r, chain_id="CT_501") for r in recs]
    toks, _ = fm.build_tokens(recs + sol)
    assert sorted(t.address for t in toks) == sorted([recs[0]["address"], "CT_501:" + recs[0]["address"]])


def test_progress_per_candle_overrides_mcap_derivation_and_filters_pass_with_real_fields():
    recs, _ = make_records()
    t = fm.build_tokens(recs)[0][0]
    s = snapshot_at(t, 1)
    assert s.progress_pct == 50.0 and s.holders == 100 and s.top10_pct == 30.0
    cfg = FilterConfig(progress_min_pct=45, holders_min=80, top10_max_pct=55, dev_max_pct=70, sniper_max_pct=70,
                       bundler_max_pct=30, liquidity_min_usd=5000)
    assert passes(s, cfg)
    assert not passes(snapshot_at(t, 0), cfg)  # progress 40 < 45
    assert not passes(s, FilterConfig(tax_max_pct=8))  # unknown tax -> fail closed
    assert not passes(s, FilterConfig(insider_max_pct=10))  # unknown insider -> fail closed


def test_candle_progress_roundtrip_json(tmp_path):
    t = TokenLaunch("0xA", "T", 1000, "P", [Candle(1.0, 2.0, 12.5), Candle(2.0, 3.0)], holders=5)
    p = tmp_path / "t.json"
    tokens_to_json([t], p)
    back = load_tokens(p)[0]
    assert back.candles == [Candle(1.0, 2.0, 12.5), Candle(2.0, 3.0, None)]


# ------------------------------------------------------------------ CLI / isolation

def test_cli_snapshot_and_export_offline(tmp_path, monkeypatch, capsys):
    # inject the recorded-fixture HTTP function and a no-op sleep; the CLI itself never sees a network
    orig = fm.run_snapshots

    def patched(*a, **k):
        k.setdefault("http", good_http())
        k["sleep"] = lambda x: None
        return orig(*a, **k)

    monkeypatch.setattr(fm, "run_snapshots", patched)
    out = tmp_path / "s.jsonl"
    rc = main(["snapshot", "--interval", "60", "--count", "2", "--out", str(out), "--raw-dir", str(tmp_path / "raw")])
    assert rc == 0 and len(out.read_text().splitlines()) == 12
    ds = tmp_path / "d.json"
    assert main(["snapshot-export", "--in", str(out), "--out", str(ds)]) == 0
    toks = load_tokens(ds)
    assert len(toks) == 6 and all(len(t.candles) >= 1 for t in toks)
    assert main(["snapshot", "--interval", "5", "--count", "1", "--out", str(out)]) == 2  # validation error
    assert "interval must be" in capsys.readouterr().out


def test_cli_export_empty_file(tmp_path):
    f = tmp_path / "e.jsonl"
    f.write_text("")
    assert main(["snapshot-export", "--in", str(f), "--out", str(tmp_path / "o.json")]) == 1


def test_load_snapshots_rejects_garbage(tmp_path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"source":"other"}\n\nnot json\n')
    with pytest.raises(DataError, match="bad JSON"):
        fm.load_snapshots(f)


def test_nothing_else_imports_fetch_meme_rush_at_module_level():
    for p in (ROOT / "memelab").glob("*.py"):
        if p.name == "fetch_meme_rush.py":
            continue
        for line in p.read_text().splitlines():
            if re.search(r"fetch_meme_rush", line):
                assert line.startswith(" "), f"{p.name}: top-level import of optional module: {line}"


def test_module_has_no_wallet_or_auth_surface():
    src = (ROOT / "memelab" / "fetch_meme_rush.py").read_text().lower()
    for word in ("private_key", "mnemonic", "signature", "authorization", "api_key", "apikey", "cookie", "web3.eth"):
        assert word not in src.replace("authorisation", "")
