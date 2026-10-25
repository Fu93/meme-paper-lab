"""OPTIONAL, READ-ONLY public-data source: Binance Web3 "meme-rush" launchpad feed (BSC / Solana / Base).

Nothing else in memelab imports this module (the CLI imports it lazily, only for the
`snapshot` / `snapshot-export` commands). No API key, no wallet, no signing, no session state, no auth
header, no writes to any remote system. The only network call is an unauthenticated HTTPS POST of a
small JSON filter to the public endpoint documented in binance/binance-skills-hub
(skills/binance-web3/meme-rush, SKILL.md + references/cli.md):

    POST https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/rank/list/ai
    body: {"chainId": "56", "rankType": 10|20|30, "limit": <=100}
    rankType 10 = New (bonding curve), 20 = Finalizing, 30 = Migrated to DEX.

The endpoint returns the CURRENT state of the feed only. There is no history endpoint, so a forward-looking
dataset can only be built by polling over time (`memelab snapshot`). If the endpoint ever answers 401/403
(auth required) the logger stops and reports it; it never tries to get around that.

Limits: lightweight polling (>= 1 s between requests, interval >= 60 s, 10 s timeout, one attempt per request).
Values are what the vendor reports at poll time; this module does not verify them.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .data import DataError
from .models import Candle, TokenLaunch

URL = ("https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/"
       "pulse/rank/list/ai")
UA = "memelab-paper/0.1 (read-only research script)"
TIMEOUT_S = 10.0
OK_CODE = "000000"
RATE_LIMIT_CODE = "100004"
CHAINS = ("56", "CT_501", "8453")
RANK_TYPES = {10: "new", 20: "finalizing", 30: "migrated"}
MIN_INTERVAL_S = 60.0
MIN_DELAY_S = 1.0
SOURCE = "binance_meme_rush_public"

PROTOCOLS = {
    1001: "Pump.fun", 1004: "LaunchLab", 1005: "Raydium AMM", 1006: "Raydium CPMM", 1007: "Raydium CLMM",
    1008: "Bonk", 1009: "Dynamic BC", 1010: "Moonshot", 1011: "Jupiter Studio", 1012: "Bags",
    1013: "Believer", 1014: "Meteora DAMM V2", 1015: "Meteora AMM", 1016: "Orca", 1017: "StonkFun",
    2001: "Four.meme", 2002: "Flap", 2004: "Open Four", 2005: "Virtuals", 2006: "genius.fun",
    2007: "genius.fun V2", 2008: "brew Standard", 2009: "brew Dividend", 2010: "brew Multipair",
    2012: "O1 Exchange Tax", 3001: "Clanker", 3002: "Bankr", 3003: "Zora Creator", 3004: "Zora Content",
    3006: "Flaunch", 3008: "Virtuals", 3009: "Virtuals V5", 3010: "O1 Exchange", 3011: "Flap",
    3012: "O1 Exchange V3", 3013: "O1 Exchange Tax",
}

# Per-snapshot fields copied into the JSONL record, in addition to the mapped model fields.
EXTRA_FIELDS = {
    "volume": "volume_usd", "netBuy": "net_buy_usd", "devSellPercent": "dev_sell_pct",
    "newWalletHoldingPercent": "new_wallet_pct", "bnHoldingPercent": "bn_holding_pct",
    "kolHoldingPercent": "kol_holding_pct", "smartMoneyHoldingPercent": "smart_money_holding_pct",
}
EXTRA_INTS = {
    "count": "trades_24h", "countBuy": "buys_24h", "countSell": "sells_24h", "sniperCount": "sniper_count",
    "bundlerHolders": "bundler_holders", "kolHolders": "kol_holders", "smartMoneyHolders": "smart_money_holders",
    "devPosition": "dev_position",
}


# --------------------------------------------------------------------------- parsing

def _f(v: Any) -> float | None:
    """Vendor numbers arrive as strings ('42.5'), numbers or null. Anything unusable -> None (unknown)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _i(v: Any) -> int | None:
    x = _f(v)
    return int(x) if x is not None else None


def map_token(raw: dict[str, Any], chain_id: str, rank_type: int, poll_ts: int) -> dict[str, Any] | None:
    """Map one vendor token object to a flat snapshot record (memelab units: USD, percent as 5 = 5%).

    Returns None if the row has no contract address or no usable creation time (cannot be placed on a timeline).
    Missing values stay None; a null tax is "unknown", never 0 (so tax filters fail closed).
    """
    if not isinstance(raw, dict):
        return None
    addr = raw.get("contractAddress")
    create_ms = _f(raw.get("createTime"))
    if not addr or not isinstance(addr, str) or create_ms is None or create_ms <= 0:
        return None
    protocol = _i(raw.get("protocol"))
    flags: list[str] = []
    if _i(raw.get("tagDevWashTrading")) == 1:
        flags.append("dev_wash_trading")
    if _i(raw.get("tagInsiderWashTrading")) == 1:
        flags.append("insider_wash_trading")
    price = _f(raw.get("price"))
    rec: dict[str, Any] = {
        "source": SOURCE,
        "poll_ts": int(poll_ts),
        "chain_id": str(chain_id),
        "rank_type": int(rank_type),
        "address": addr,
        "symbol": str(raw.get("symbol") or ""),
        "protocol": protocol,
        "platform": PROTOCOLS.get(protocol, f"protocol_{protocol}") if protocol is not None else "unknown",
        "create_ts": int(create_ms // 1000),
        "migrated": (_i(raw.get("migrateStatus")) == 1) if raw.get("migrateStatus") is not None else None,
        "price": price if price is not None and price > 0 else None,
        "mcap": _f(raw.get("marketCap")),
        "progress_pct": _f(raw.get("progress")),
        "liquidity_usd": _f(raw.get("liquidity")),
        "holders": _i(raw.get("holders")),
        "top10_pct": _f(raw.get("holdersTop10Percent")),
        "dev_pct": _f(raw.get("holdersDevPercent")),
        "sniper_pct": _f(raw.get("holdersSniperPercent")),
        "insider_pct": _f(raw.get("holdersInsiderPercent")),
        "bundler_pct": _f(raw.get("bundlerHoldingPercent")),
        "buy_tax_pct": _f(raw.get("taxRateBuy")),
        "sell_tax_pct": _f(raw.get("taxRateSell")),
        "dev_flags": flags,
        "token_version": raw.get("tokenVersion"),
    }
    for src, dst in EXTRA_FIELDS.items():
        rec[dst] = _f(raw.get(src))
    for src, dst in EXTRA_INTS.items():
        rec[dst] = _i(raw.get(src))
    return rec


def parse_response(payload: Any, chain_id: str, rank_type: int, poll_ts: int) -> list[dict[str, Any]]:
    """Envelope -> list of snapshot records. Raises DataError on a non-success envelope / bad shape."""
    if not isinstance(payload, dict):
        raise DataError("meme-rush response is not a JSON object")
    code = payload.get("code")
    if code != OK_CODE or payload.get("success") is False:
        raise DataError(f"meme-rush business code {code!r}: {payload.get('message')!r}")
    data = payload.get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise DataError("meme-rush 'data' is not a list")
    out = []
    for row in data:
        rec = map_token(row, chain_id, rank_type, poll_ts)
        if rec is not None:
            out.append(rec)
    return out


# --------------------------------------------------------------------------- HTTP

@dataclass
class HttpResult:
    status: int | None  # None = network failure/timeout
    payload: Any = None
    error: str | None = None


def http_post_json(url: str, body: dict[str, Any], timeout: float = TIMEOUT_S) -> HttpResult:
    """Unauthenticated JSON POST. Never raises; failures come back as HttpResult(error=...)."""
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json", "accept": "application/json",
                 "accept-encoding": "identity", "user-agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return HttpResult(r.status, json.loads(r.read().decode()))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:  # noqa: BLE001 - body is best effort
            payload = None
        return HttpResult(e.code, payload, f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return HttpResult(None, None, f"{type(e).__name__}: {e}")


HttpFn = Callable[[str, dict[str, Any], float], HttpResult]


# --------------------------------------------------------------------------- polling

@dataclass
class PollSummary:
    poll_ts: int
    records: list[dict[str, Any]] = field(default_factory=list)
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)  # "chain/rank" -> parsed rows
    blocked_auth: bool = False
    rate_limited: bool = False


def validate_params(chains: list[str], ranks: list[int], limit: int, interval_s: float | None = None,
                    count: int | None = None, delay_s: float = MIN_DELAY_S) -> None:
    for c in chains:
        if c not in CHAINS:
            raise DataError(f"unsupported chain {c!r}; supported: {', '.join(CHAINS)}")
    for r in ranks:
        if r not in RANK_TYPES:
            raise DataError(f"unsupported rank type {r!r}; use 10 (new), 20 (finalizing), 30 (migrated)")
    if not chains or not ranks:
        raise DataError("need at least one chain and one rank type")
    if not 1 <= limit <= 100:
        raise DataError("limit must be 1..100")
    if delay_s < MIN_DELAY_S:
        raise DataError(f"delay must be >= {MIN_DELAY_S:g} s (be gentle with the public endpoint)")
    if interval_s is not None and interval_s < MIN_INTERVAL_S:
        raise DataError(f"interval must be >= {MIN_INTERVAL_S:g} s")
    if count is not None and count < 1:
        raise DataError("count must be >= 1")


def poll_once(chains: list[str], ranks: list[int], limit: int = 50, raw_dir: str | Path | None = None,
              delay_s: float = 2.0, http: HttpFn = http_post_json, sleep: Callable[[float], None] = time.sleep,
              now: Callable[[], float] = time.time) -> PollSummary:
    """One pass over chains x ranks (sequential, `delay_s` apart). Graceful: errors are collected, not raised.
    Stops early on auth-required (401/403) or rate-limit (429 / code 100004). Raw responses are cached to raw_dir."""
    validate_params(chains, ranks, limit, delay_s=delay_s)
    poll_ts = int(now())
    summ = PollSummary(poll_ts)
    seen: set[tuple[str, str]] = set()
    first = True
    for chain in chains:
        for rank in ranks:
            if not first:
                sleep(delay_s)
            first = False
            body = {"chainId": chain, "rankType": rank, "limit": limit}
            res = http(URL, body, TIMEOUT_S)
            summ.requests += 1
            key = f"{chain}/{rank}"
            if raw_dir is not None:
                _cache_raw(raw_dir, poll_ts, chain, rank, body, res)
            if res.status in (401, 403):
                summ.blocked_auth = True
                summ.errors.append(f"{key}: HTTP {res.status} (authentication/authorisation required) - stopping, not working around it")
                return summ
            if res.status == 429 or (isinstance(res.payload, dict) and res.payload.get("code") == RATE_LIMIT_CODE):
                summ.rate_limited = True
                summ.errors.append(f"{key}: rate limited - stopping this poll")
                return summ
            if res.status is None or res.status >= 400:
                summ.errors.append(f"{key}: {res.error or res.status}")
                continue
            try:
                recs = parse_response(res.payload, chain, rank, poll_ts)
            except DataError as e:
                summ.errors.append(f"{key}: {e}")
                continue
            summ.counts[key] = len(recs)
            for r in recs:
                k = (r["chain_id"], r["address"])
                if k not in seen:  # same token can appear in two stages in one poll; keep the first listing
                    seen.add(k)
                    summ.records.append(r)
    return summ


def _cache_raw(raw_dir: str | Path, poll_ts: int, chain: str, rank: int, body: dict, res: HttpResult) -> None:
    try:
        d = Path(raw_dir)
        d.mkdir(parents=True, exist_ok=True)
        doc = {"url": URL, "request_body": body, "fetched_at_epoch": poll_ts, "http_status": res.status,
               "error": res.error, "response": res.payload}
        (d / f"{poll_ts}_{chain}_{rank}.json").write_text(json.dumps(doc))
    except OSError:
        pass  # caching is best effort


def append_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def run_snapshots(interval_s: float, count: int, out: str | Path, chains: list[str] | None = None,
                  ranks: list[int] | None = None, limit: int = 50, raw_dir: str | Path | None = None,
                  delay_s: float = 2.0, http: HttpFn = http_post_json,
                  sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time,
                  log: Callable[[str], None] = print) -> list[PollSummary]:
    """Poll `count` times, `interval_s` apart (measured start-to-start), appending to the JSONL at `out`."""
    chains = chains or ["56"]
    ranks = ranks or [10, 20, 30]
    validate_params(chains, ranks, limit, interval_s, count, delay_s)
    summaries: list[PollSummary] = []
    for i in range(count):
        t0 = now()
        s = poll_once(chains, ranks, limit, raw_dir, delay_s, http, sleep, now)
        summaries.append(s)
        if s.records:
            append_jsonl(out, s.records)
        log(f"poll {i + 1}/{count}: requests={s.requests} tokens={len(s.records)} by_list={s.counts}"
            + (f" errors={s.errors}" if s.errors else ""))
        if s.blocked_auth:
            log("STOP: endpoint demands authentication; nothing further attempted.")
            break
        if i < count - 1:
            sleep(max(1.0, interval_s - (now() - t0)))
    return summaries


# --------------------------------------------------------------------------- JSONL -> TokenLaunch

STATIC_KEYS = ["liquidity_usd", "holders", "top10_pct", "dev_pct", "sniper_pct", "insider_pct",
               "bundler_pct", "buy_tax_pct", "sell_tax_pct"]


def load_snapshots(path: str | Path) -> list[dict[str, Any]]:
    out = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise DataError(f"{path}:{n}: bad JSON line ({e})") from e
        if isinstance(rec, dict) and rec.get("source") == SOURCE:
            out.append(rec)
    return out


@dataclass
class BuildStats:
    n_snapshots: int = 0
    n_tokens: int = 0
    n_tokens_multi_candle: int = 0
    # tokens whose static field's first non-null value was observed after the token's first candle (look-ahead risk)
    late_static: dict[str, int] = field(default_factory=dict)
    never_known: dict[str, int] = field(default_factory=dict)


def build_tokens(records: list[dict[str, Any]]) -> tuple[list[TokenLaunch], BuildStats]:
    """Group snapshots by (chain, address) into TokenLaunch records.

    * candle t_min = minutes since the vendor's createTime; price and bonding-curve progress are per candle.
    * static fields (holders, top10/dev/sniper/insider/bundler %, liquidity, tax) are the FIRST non-null value seen.
      They are applied to the whole timeline, so if the first non-null value arrived after the first candle the
      filters see a value from the future for the early candles. BuildStats.late_static counts those cases.
    * dev_flags is the union over all snapshots (conservative; also look-ahead).
    * Unknown stays None, so filters on it fail closed.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault((r["chain_id"], r["address"]), []).append(r)
    stats = BuildStats(n_snapshots=len(records))
    tokens: list[TokenLaunch] = []
    for (chain, addr), recs in groups.items():
        recs.sort(key=lambda r: r["poll_ts"])
        by_t: dict[float, Candle] = {}
        for r in recs:
            if r.get("price") is None:
                continue
            t_min = max(0.0, (r["poll_ts"] - r["create_ts"]) / 60.0)
            by_t[t_min] = Candle(t_min, float(r["price"]), r.get("progress_pct"))
        if not by_t:
            continue
        candles = [by_t[k] for k in sorted(by_t)]
        first_poll = min(r["poll_ts"] for r in recs if r.get("price") is not None)
        static: dict[str, Any] = {}
        for k in STATIC_KEYS:
            hit = next((r for r in recs if r.get(k) is not None), None)
            if hit is None:
                static[k] = None
                stats.never_known[k] = stats.never_known.get(k, 0) + 1
            else:
                static[k] = hit[k]
                if hit["poll_ts"] > first_poll:
                    stats.late_static[k] = stats.late_static.get(k, 0) + 1
        ratios = [r["mcap"] / r["price"] for r in recs if r.get("mcap") and r.get("price")]
        supply = statistics.median(ratios) if ratios else 1e9
        flags = sorted({f for r in recs for f in r.get("dev_flags") or []})
        holders = static.pop("holders")
        tokens.append(TokenLaunch(
            address=addr if chain == "56" else f"{chain}:{addr}",
            symbol=recs[-1].get("symbol", ""), launch_time=recs[0]["create_ts"],
            platform=f"{recs[-1].get('platform', 'unknown')}/{chain}", candles=candles,
            total_supply=supply, holders=int(holders) if holders is not None else None,
            dev_flags=tuple(flags), **static,
        ))
        stats.n_tokens_multi_candle += len(candles) > 1
    stats.n_tokens = len(tokens)
    return tokens, stats
