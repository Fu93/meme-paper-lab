"""OPTIONAL, best-effort, READ-ONLY public data fetcher (GeckoTerminal public API, BSC).

Separate from the core engine; nothing else imports this module. No API key, no wallet, no
writes. Requests are throttled (default >= 3 s apart) and every failure returns None/[].

Caveats: only pools the API still lists (survivorship bias); holder/bundler/sniper/insider/
dev/tax fields are NOT available from this source and are left as None, so any filter on
them fails closed; liquidity is a single snapshot taken at fetch time, not at launch.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .data import parse_time
from .models import Candle, TokenLaunch

BASE = "https://api.geckoterminal.com/api/v2"
UA = "memelab-paper/0.1 (read-only research script)"


def _get(url: str, timeout: float = 15.0) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def parse_ohlcv(payload: dict[str, Any] | None, launch_ts: int) -> list[Candle]:
    """GeckoTerminal ohlcv_list rows are [ts, o, h, l, c, v], newest first."""
    try:
        rows = payload["data"]["attributes"]["ohlcv_list"]  # type: ignore[index]
    except (KeyError, TypeError):
        return []
    pts = sorted((int(r[0]), float(r[4])) for r in rows if float(r[4]) > 0)
    return [Candle((ts - launch_ts) / 60.0, price) for ts, price in pts if ts >= launch_ts - 60]


def parse_pool(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        a = item["attributes"]
        price = float(a["base_token_price_usd"])
        fdv = float(a["fdv_usd"]) if a.get("fdv_usd") else None
        return {
            "pool": a["address"],
            "name": a["name"],
            "created": parse_time(a["pool_created_at"]),
            "liquidity_usd": float(a["reserve_in_usd"]) if a.get("reserve_in_usd") else None,
            "supply": (fdv / price) if fdv and price > 0 else 1e9,
            "dex": item["relationships"]["dex"]["data"]["id"],
        }
    except (KeyError, TypeError, ValueError):
        return None


def _history(pool: dict[str, Any], aggregate_min: int) -> TokenLaunch | None:
    url = (f"{BASE}/networks/bsc/pools/{pool['pool']}/ohlcv/minute"
           f"?aggregate={aggregate_min}&limit=288&currency=usd")
    candles = parse_ohlcv(_get(url), pool["created"])
    if len(candles) < 3:
        return None
    return TokenLaunch(
        address=pool["pool"], symbol=pool["name"].split(" / ")[0], launch_time=pool["created"],
        platform=pool["dex"], candles=candles, total_supply=pool["supply"],
        liquidity_usd=pool["liquidity_usd"],
    )


def fetch_recent_tokens(max_tokens: int = 5, aggregate_min: int = 5, delay_s: float = 3.0,
                        max_requests: int = 8, sleep=time.sleep) -> list[TokenLaunch]:
    """Walk the newest BSC pools, keeping those with >= 3 candles of history. Brand-new pools
    usually have 1 candle, so this may legitimately return []. Hard cap: max_requests OHLCV calls."""
    listing = _get(f"{BASE}/networks/bsc/new_pools?page=1")
    if not listing:
        return []
    out: list[TokenLaunch] = []
    for item in listing.get("data", [])[: max(0, max_requests)]:
        if len(out) >= max_tokens:
            break
        pool = parse_pool(item)
        if pool is None:
            continue
        sleep(delay_s)
        tok = _history(pool, aggregate_min)
        if tok:
            out.append(tok)
    return out


def fetch_pool(pool_address: str, aggregate_min: int = 5, delay_s: float = 3.0,
               sleep=time.sleep) -> TokenLaunch | None:
    """Fetch one named pool (2 requests). launch_time = pool_created_at from the API."""
    detail = _get(f"{BASE}/networks/bsc/pools/{pool_address}")
    pool = parse_pool(detail["data"]) if detail and "data" in detail else None
    if pool is None:
        return None
    sleep(delay_s)
    return _history(pool, aggregate_min)
