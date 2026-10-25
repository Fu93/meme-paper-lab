"""CLI: python -m memelab {run,demo,synth,fetch,snapshot,snapshot-export}. Paper-only; nothing here can trade."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ConfigError, load_config
from .data import DataError, load_tokens, tokens_to_csv, tokens_to_json
from .report import compute_report, render_markdown
from .simulator import run_backtest

SYNTH_LABEL = "SYNTHETIC (invented random data, not market data; results mean nothing about real markets)"


def _write_reports(rep: dict, out: str) -> tuple[Path, Path]:
    md = Path(out)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_markdown(rep))
    js = md.with_suffix(".json")
    js.write_text(json.dumps(rep, indent=2, default=str))
    return md, js


def cmd_run(a: argparse.Namespace) -> int:
    cfg = load_config(a.config)
    tokens = load_tokens(a.data)
    label = SYNTH_LABEL if tokens and all(t.synthetic for t in tokens) else a.label or ""
    rep = compute_report(run_backtest(tokens, cfg), cfg, label)
    md, js = _write_reports(rep, a.out)
    print(f"wrote {md} and {js}; trades={rep['n_trades']} total_pnl={rep['total_pnl_usd']:+.2f} USD (simulated)")
    for w in rep["warnings"]:
        print("WARNING:", w)
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    from .synth import generate

    cfg = load_config(a.config)
    tokens = generate(a.n, a.seed, moon_frac=a.moon_frac)
    rep = compute_report(run_backtest(tokens, cfg), cfg, SYNTH_LABEL)
    md, js = _write_reports(rep, a.out)
    print(f"[SYNTHETIC DATA] wrote {md} and {js}; trades={rep['n_trades']} "
          f"total_pnl={rep['total_pnl_usd']:+.2f} USD (simulated)")
    for w in rep["warnings"]:
        print("WARNING:", w)
    return 0


def cmd_synth(a: argparse.Namespace) -> int:
    from .synth import generate

    toks = generate(a.n, a.seed, moon_frac=a.moon_frac)
    (tokens_to_csv if a.out.endswith(".csv") else tokens_to_json)(toks, a.out)
    print(f"wrote {len(toks)} SYNTHETIC tokens to {a.out}")
    return 0


def cmd_fetch(a: argparse.Namespace) -> int:
    from .fetch_public import fetch_recent_tokens

    if a.pool:
        from .fetch_public import fetch_pool

        t = fetch_pool(a.pool)
        toks = [t] if t else []
    else:
        toks = fetch_recent_tokens(a.max_tokens)
    if not toks:
        print("no data fetched (network failure or empty listing); nothing written")
        return 1
    tokens_to_json(toks, a.out)
    print(f"wrote {len(toks)} tokens to {a.out} (public read-only data; survivorship-biased; many fields unknown)")
    return 0


def cmd_snapshot(a: argparse.Namespace) -> int:
    from .fetch_meme_rush import run_snapshots

    sums = run_snapshots(a.interval, a.count, a.out, chains=a.chains, ranks=a.ranks, limit=a.limit,
                         raw_dir=None if a.no_raw else a.raw_dir, delay_s=a.delay)
    n = sum(len(s.records) for s in sums)
    print(f"appended {n} snapshot rows over {len(sums)} poll(s) to {a.out} (public read-only data; snapshots, not history)")
    if any(s.blocked_auth for s in sums):
        return 3
    return 0 if n else 1


def cmd_snapshot_export(a: argparse.Namespace) -> int:
    from .fetch_meme_rush import build_tokens, load_snapshots

    toks, st = build_tokens(load_snapshots(a.inp))
    if not toks:
        print("no usable tokens in the snapshot file; nothing written")
        return 1
    tokens_to_json(toks, a.out)
    print(f"wrote {st.n_tokens} tokens ({st.n_tokens_multi_candle} with >1 candle) from {st.n_snapshots} snapshot rows to {a.out}")
    print(f"static fields first seen AFTER the first candle (look-ahead risk), token counts: {st.late_static or 'none'}")
    print(f"static fields never known (filters on them fail closed), token counts: {st.never_known or 'none'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memelab", description="PAPER-ONLY meme launch simulator. Not advice.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="simulate on a CSV/JSON dataset")
    r.add_argument("--data", required=True)
    r.add_argument("--config", help="YAML/JSON config (default: built-in illustrative config)")
    r.add_argument("--out", default="report.md")
    r.add_argument("--label", help="free-text data label shown in the report header")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("demo", help="run on SYNTHETIC data")
    d.add_argument("--config")
    d.add_argument("--n", type=int, default=2000)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--moon-frac", type=float, default=0.05, help="share of synthetic tokens that pump (invented)")
    d.add_argument("--out", default="demo_report.md")
    d.set_defaults(fn=cmd_demo)
    s = sub.add_parser("synth", help="write a SYNTHETIC dataset (.csv or .json)")
    s.add_argument("--out", required=True)
    s.add_argument("--n", type=int, default=2000)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--moon-frac", type=float, default=0.05)
    s.set_defaults(fn=cmd_synth)
    f = sub.add_parser("fetch", help="best-effort read-only public price history (GeckoTerminal)")
    f.add_argument("--out", required=True)
    f.add_argument("--max-tokens", type=int, default=5)
    f.add_argument("--pool", help="fetch one BSC pool address instead of scanning new pools")
    f.set_defaults(fn=cmd_fetch)
    sn = sub.add_parser("snapshot", help="poll the public Binance meme-rush feed and append snapshots to a JSONL (read-only)")
    sn.add_argument("--interval", type=float, default=300.0, help="seconds between polls (>= 60)")
    sn.add_argument("--count", type=int, required=True, help="number of polls")
    sn.add_argument("--out", default="out/meme_rush_snapshots.jsonl")
    sn.add_argument("--raw-dir", default="out/meme_rush_raw", help="cache raw responses here")
    sn.add_argument("--no-raw", action="store_true", help="do not cache raw responses")
    sn.add_argument("--chains", nargs="+", default=["56"], help="chain ids: 56 (BSC), CT_501 (Solana), 8453 (Base)")
    sn.add_argument("--ranks", nargs="+", type=int, default=[10, 20, 30], help="10 new, 20 finalizing, 30 migrated")
    sn.add_argument("--limit", type=int, default=50, help="rows per request (1..100)")
    sn.add_argument("--delay", type=float, default=2.0, help="seconds between requests within a poll (>= 1)")
    sn.set_defaults(fn=cmd_snapshot)
    se = sub.add_parser("snapshot-export", help="turn a snapshot JSONL into a dataset JSON that `run` can load")
    se.add_argument("--in", dest="inp", default="out/meme_rush_snapshots.jsonl")
    se.add_argument("--out", default="out/meme_rush_tokens.json")
    se.set_defaults(fn=cmd_snapshot_export)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, DataError, OSError, KeyError) as exc:
        print(f"error: {exc}")
        return 2
