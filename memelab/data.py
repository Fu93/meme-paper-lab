"""Load/save token launches from JSON or long-format CSV (one row per candle).

CSV columns: address,symbol,launch_time,platform,t_min,price[,mcap] plus optional static columns:
total_supply,graduation_mcap_usd,liquidity_usd,holders,top10_pct,dev_pct,sniper_pct,insider_pct,
bundler_pct,buy_tax_pct,sell_tax_pct,dev_flags (';'-separated),synthetic.
If `price` is empty but `mcap` is given, price = mcap / total_supply.
JSON: a list of token objects, or {"tokens": [...]}, each with the static fields and
"series": [{"t_min":..,"price":..} or {"t_min":..,"mcap":..}, ...].
launch_time may be epoch seconds or an ISO-8601 string.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Candle, TokenLaunch

STATIC_FLOAT = [
    "total_supply", "graduation_mcap_usd", "liquidity_usd", "top10_pct", "dev_pct",
    "sniper_pct", "insider_pct", "bundler_pct", "buy_tax_pct", "sell_tax_pct",
]
STATIC_COLS = STATIC_FLOAT + ["holders", "dev_flags", "synthetic"]


class DataError(ValueError):
    pass


def parse_time(v: Any) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    try:
        return int(float(s))
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataError(f"bad launch_time {v!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if v == "":
            return None
    return float(v)


def _flags(v: Any) -> tuple[str, ...]:
    if v is None or v == "":
        return ()
    if isinstance(v, str):
        return tuple(x.strip() for x in v.split(";") if x.strip())
    return tuple(str(x) for x in v)


def _boolean(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def _candle(row: dict[str, Any], supply: float) -> Candle:
    t = _num(row.get("t_min"))
    price = _num(row.get("price"))
    if price is None:
        m = _num(row.get("mcap"))
        if m is None:
            raise DataError("candle needs price or mcap")
        price = m / supply
    if t is None or price <= 0:
        raise DataError(f"bad candle {row}")
    prog = _num(row.get("progress_pct"))
    return Candle(t, price, prog)


def _build(meta: dict[str, Any], rows: list[dict[str, Any]]) -> TokenLaunch:
    supply = _num(meta.get("total_supply")) or 1e9
    candles = sorted((_candle(r, supply) for r in rows), key=lambda c: c.t_min)
    kw: dict[str, Any] = {k: _num(meta.get(k)) for k in STATIC_FLOAT}
    kw["total_supply"] = supply
    h = _num(meta.get("holders"))
    return TokenLaunch(
        address=str(meta["address"]),
        symbol=str(meta.get("symbol", "")),
        launch_time=parse_time(meta["launch_time"]),
        platform=str(meta.get("platform", "")),
        candles=candles,
        holders=int(h) if h is not None else None,
        dev_flags=_flags(meta.get("dev_flags")),
        synthetic=_boolean(meta.get("synthetic", False)),
        **kw,
    )


def load_tokens(path: str | Path) -> list[TokenLaunch]:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        groups: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
        with p.open(newline="") as f:
            for row in csv.DictReader(f):
                addr = row.get("address")
                if not addr:
                    raise DataError("CSV row without address")
                groups.setdefault(addr, (row, []))[1].append(row)
        return [_build(meta, rows) for meta, rows in groups.values()]
    raw = json.loads(p.read_text())
    items = raw["tokens"] if isinstance(raw, dict) else raw
    return [_build(it, it.get("series", [])) for it in items]


def tokens_to_json(tokens: list[TokenLaunch], path: str | Path) -> None:
    out = []
    for t in tokens:
        d: dict[str, Any] = {
            "address": t.address, "symbol": t.symbol, "launch_time": t.launch_time,
            "platform": t.platform, "holders": t.holders, "dev_flags": list(t.dev_flags),
            "synthetic": t.synthetic,
        }
        for k in STATIC_FLOAT:
            d[k] = getattr(t, k)
        d["series"] = [{"t_min": c.t_min, "price": c.price,
                        **({"progress_pct": c.progress_pct} if c.progress_pct is not None else {})}
                       for c in t.candles]
        out.append(d)
    Path(path).write_text(json.dumps({"tokens": out}))


def tokens_to_csv(tokens: list[TokenLaunch], path: str | Path) -> None:
    cols = ["address", "symbol", "launch_time", "platform", "t_min", "price"] + STATIC_COLS
    with Path(path).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in tokens:
            base = {
                "address": t.address, "symbol": t.symbol, "launch_time": t.launch_time,
                "platform": t.platform, "holders": t.holders, "dev_flags": ";".join(t.dev_flags),
                "synthetic": int(t.synthetic),
            }
            for k in STATIC_FLOAT:
                v = getattr(t, k)
                base[k] = "" if v is None else v
            if base["holders"] is None:
                base["holders"] = ""
            for c in t.candles:
                w.writerow({**base, "t_min": c.t_min, "price": repr(c.price)})
