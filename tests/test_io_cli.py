import json

import pytest

from memelab import cli
from memelab.config import ConfigError, config_from_dict, default_config, load_config
from memelab.data import load_tokens, parse_time, tokens_to_csv, tokens_to_json
from memelab.fetch_public import parse_ohlcv, parse_pool
from memelab.synth import generate


def test_synth_deterministic_and_labelled():
    a, b = generate(20, seed=1), generate(20, seed=1)
    assert [t.candles[-1].price for t in a] == [t.candles[-1].price for t in b]
    assert all(t.synthetic and t.address.startswith("0xSYNTH") for t in a)
    assert generate(20, seed=2)[0].candles[-1].price != a[0].candles[-1].price


def test_synth_is_heavy_tailed():
    peaks = sorted((max(c.price for c in t.candles) / t.candles[0].price for t in generate(600, seed=3)), reverse=True)
    assert peaks[0] > 20 and peaks[len(peaks) // 2] < 3  # a few giants, typical token is not


def test_csv_json_roundtrip(tmp_path):
    toks = generate(5, seed=4)
    tokens_to_csv(toks, tmp_path / "t.csv")
    tokens_to_json(toks, tmp_path / "t.json")
    for p in ("t.csv", "t.json"):
        back = load_tokens(tmp_path / p)
        assert len(back) == 5
        assert back[0].address == toks[0].address and back[0].synthetic
        assert back[0].candles[3].price == pytest.approx(toks[0].candles[3].price)
        assert back[0].holders == toks[0].holders and back[0].dev_flags == toks[0].dev_flags


def test_mcap_series_and_iso_time(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps([{"address": "0x1", "symbol": "A", "launch_time": "2025-01-01T00:00:00Z",
                              "total_supply": 1000, "series": [{"t_min": 0, "mcap": 5000}, {"t_min": 5, "mcap": 10000}]}]))
    t = load_tokens(p)[0]
    assert t.candles[1].price == 10.0 and t.launch_time == parse_time("2025-01-01T00:00:00+00:00") == 1735689600


def test_config_unknown_key_rejected():
    with pytest.raises(ConfigError):
        config_from_dict({"filters": {"holder_min": 5}})  # typo
    with pytest.raises(ConfigError):
        config_from_dict({"exits": {"stop_loss_pct": 150}})
    with pytest.raises(ConfigError):
        config_from_dict({"exits": {"take_profits": [{"at_gain_pct": 100, "sell_fraction": 0.7}, {"at_gain_pct": 200, "sell_fraction": 0.7}]}})


def test_yaml_example_loads_and_matches_default():
    from dataclasses import asdict
    assert asdict(load_config("configs/example.yaml")) == asdict(default_config())


def test_fetch_parsers_offline():
    payload = {"data": {"attributes": {"ohlcv_list": [[1300, 1, 1, 1, 3.0, 0], [1000, 1, 1, 1, 2.0, 0], [700, 1, 1, 1, 9.0, 0]]}}}
    cs = parse_ohlcv(payload, 1000)
    assert [(c.t_min, c.price) for c in cs] == [(0.0, 2.0), (5.0, 3.0)]  # sorted, pre-launch dropped
    assert parse_ohlcv(None, 0) == [] and parse_ohlcv({"x": 1}, 0) == []
    item = {"attributes": {"address": "0xp", "name": "AB / BNB", "base_token_price_usd": "0.5", "fdv_usd": "500",
                           "pool_created_at": "2026-01-01T00:00:00Z", "reserve_in_usd": "1000"},
            "relationships": {"dex": {"data": {"id": "four-meme"}}}}
    p = parse_pool(item)
    assert p["supply"] == 1000 and p["dex"] == "four-meme" and p["liquidity_usd"] == 1000
    assert parse_pool({"attributes": {}}) is None


def test_fetch_failure_returns_empty(monkeypatch):
    import memelab.fetch_public as fp
    monkeypatch.setattr(fp, "_get", lambda *a, **k: None)
    assert fp.fetch_recent_tokens(3, sleep=lambda s: None) == []


def test_cli_demo_and_run(tmp_path, capsys):
    out = tmp_path / "d.md"
    assert cli.main(["demo", "--n", "200", "--out", str(out)]) == 0
    assert "SYNTHETIC" in out.read_text() and out.with_suffix(".json").exists()
    data = tmp_path / "s.csv"
    assert cli.main(["synth", "--n", "100", "--out", str(data)]) == 0
    out2 = tmp_path / "r.md"
    assert cli.main(["run", "--data", str(data), "--config", "configs/example.yaml", "--out", str(out2)]) == 0
    assert json.loads(out2.with_suffix(".json").read_text())["n_trades"] >= 0


def test_cli_bad_config_returns_error(tmp_path):
    bad = tmp_path / "c.json"
    bad.write_text('{"nope": 1}')
    assert cli.main(["demo", "--n", "10", "--config", str(bad), "--out", str(tmp_path / "x.md")]) == 2


def test_fetch_pool_mocked(monkeypatch):
    import memelab.fetch_public as fp
    item = {"attributes": {"address": "0xp", "name": "AB / BNB", "base_token_price_usd": "0.5", "fdv_usd": "500",
                           "pool_created_at": "2026-01-01T00:00:00Z", "reserve_in_usd": "1000"},
            "relationships": {"dex": {"data": {"id": "four-meme"}}}}
    created = 1767225600
    oh = {"data": {"attributes": {"ohlcv_list": [[created + 600, 0, 0, 0, 3.0, 0], [created + 300, 0, 0, 0, 2.0, 0], [created, 0, 0, 0, 1.0, 0]]}}}
    monkeypatch.setattr(fp, "_get", lambda url, *a, **k: {"data": item} if "ohlcv" not in url else oh)
    t = fp.fetch_pool("0xp", sleep=lambda s: None)
    assert t.symbol == "AB" and [c.t_min for c in t.candles] == [0.0, 5.0, 10.0] and t.liquidity_usd == 1000
    assert t.holders is None and not t.synthetic
