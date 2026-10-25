# memelab: PAPER-ONLY meme launch simulator (v1 prototype)

**Software only. Simulation only. No advice, no signals, no promise of returns. You bear your own risk.**
Nothing here connects to a wallet, holds keys, signs, or sends transactions. It reads files you give it
and (optionally) a public read-only price API. It does not claim any trading edge; its purpose is to make
the *absence* of one (or the dependence on a few outliers) easy to see.

**Disclosure:** this tool was built by an AI agent (Grok Bot) for its user. It has been tested only with
the unit tests in `tests/` and on synthetic data. It has not been audited or reviewed by an independent person.

**Not financial advice. Simulation only. All numbers in `out/` (and in the demo command) are SYNTHETIC: randomly generated, not market data,
and they show no trading edge (in the synthetic set, token attributes are independent of outcomes by construction).
No backtest on real data is claimed to prove anything.** Licensed MIT (see `LICENSE`), provided as is, no warranty.

Committed example outputs: `out/demo_report.*` and `out/tail_demo.*` (synthetic, small). Everything else under `out/` is git-ignored.
Test fixtures in `tests/fixtures/` are samples of a public API response, used only to test the parser.

## What it does
1. Loads token-launch records (CSV/JSON): address, symbol, launch time, platform, price or market-cap
   series, holders, bundler/sniper/insider/dev/top10 %, dev flags, buy/sell tax, liquidity.
2. Applies configurable entry filters (Binance meme-rush style vocabulary: progress, token age, holders,
   liquidity, top10/dev/sniper/insider/bundler %, tax, market-cap range, dev flags).
3. Simulates exits: take-profit ladder, stop loss, trailing drawdown, time stop, fixed position size,
   max concurrent positions, daily loss stop, per-side fees/tax, slippage vs pool liquidity, latency in candles.
4. Reports (Markdown + JSON): win rate, median, mean, total PnL, PnL excluding top 5/10/20 winners,
   top-10 concentration, max drawdown, buckets by entry age and by bundler/sniper %, funnel of skipped tokens.
   A prominent WARNING appears if top-10 winners > 80% of PnL or any ex-top-N PnL is negative.

## Setup / run
```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml   # Python 3.11+
.venv/bin/python -m pytest -q
.venv/bin/python -m memelab demo --out out/demo_report.md                 # SYNTHETIC data
.venv/bin/python -m memelab demo --moon-frac 0.10 \
    --config configs/tail_demo_frictionless.yaml --out out/tail_demo.md   # tail-dependence illustration
.venv/bin/python -m memelab synth --out out/synth.csv                     # write a SYNTHETIC dataset
.venv/bin/python -m memelab run --data out/synth.csv --config configs/example.yaml --out out/report.md
.venv/bin/python tools/mutation_check.py                                  # mutation sanity check
```
Optional, best-effort, read-only public data (GeckoTerminal, BSC; throttled, a handful of requests):
```bash
.venv/bin/python -m memelab fetch --pool <bsc pool address> --out out/pool.json
.venv/bin/python -m memelab fetch --max-tokens 3 --out out/new.json      # often returns nothing: brand-new pools have ~1 candle
```
GeckoTerminal data lacks holders/bundler/sniper/dev/tax, so filters on those fail closed (no trades) unless you
disable them in the config or enrich the file yourself. The optional Binance meme-rush source below provides those fields (with caveats).

## Optional real-field source: Binance meme-rush public feed (`memelab/fetch_meme_rush.py`)
**Software only. Research tooling, not advice, not a signal, not a recommendation to buy or sell anything.**
Read-only and optional: no other module imports it (the CLI imports it lazily for the two commands below). No wallet,
no keys, no signing, no API key, no account, no transactions.

Endpoint (documented in the official `binance/binance-skills-hub` skill `binance-web3/meme-rush`; unauthenticated, no headers beyond a User-Agent):
`POST https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/rank/list/ai`
with body `{"chainId":"56","rankType":10|20|30,"limit":50}` (10 = new/bonding curve, 20 = finalizing, 30 = migrated; chains `56` BSC, `CT_501` Solana, `8453` Base).
If it ever answers 401/403 the logger stops and says so; it does not try to get around it.

```bash
.venv/bin/python -m memelab snapshot --interval 300 --count 12            # poll BSC x 3 lists every 5 min, 12 times
.venv/bin/python -m memelab snapshot-export --in out/meme_rush_snapshots.jsonl --out out/meme_rush_tokens.json
.venv/bin/python -m memelab run --data out/meme_rush_tokens.json --config configs/example.yaml --out out/meme_rush_report.md \
    --label "Binance meme-rush snapshots (tiny, survivorship/look-ahead caveats)"
```
Politeness: interval >= 60 s, >= 1 s between requests (default 2 s), 10 s timeout, one attempt per request, 3 requests per poll by default,
stop on rate-limit/auth responses. Raw responses are cached to `out/meme_rush_raw/<epoch>_<chain>_<rank>.json` (`--no-raw` to skip);
parsed rows are appended to `out/meme_rush_snapshots.jsonl` (one line per token per poll; safe to run repeatedly, it only appends).

Field mapping: `price`, `marketCap`, `progress` (per candle) and `holders`, `liquidity`, `holdersTop10/Dev/Sniper/InsiderPercent`, `bundlerHoldingPercent`,
`taxRateBuy/Sell` (static, see below). Percent fields are already in percent units. `dev_flags` gets `dev_wash_trading` / `insider_wash_trading`
only when the vendor tags equal 1. Extra snapshot columns kept in the JSONL only: volume, net buy, 24h trade counts, sniper count, bundler holders,
KOL/smart-money/BN holding, dev sell %, dev position, token version.
Not available from this source: `honeypot` flag (so `exclude_dev_flags: [honeypot]` never excludes anything from this data), a graduation market cap
(progress is taken directly instead), any history before you started polling. Unknown values stay unknown: `null` tax is NOT 0, `null` insider % is NOT 0, null tags are "not evaluated", not "safe";
filters on unknown fields still fail closed.

**Data limitations (read before trusting any number):**
- **Snapshots, not history.** The endpoint shows only the feed's current state (up to 100 rows per list). Price series are your own polls (`--interval` apart),
  not candles, and only for tokens that were in a list when polled; a token that dropped out of the lists simply stops getting points. Intra-interval
  moves, stops and take-profits are invisible; "close" fills are poll-time prices.
- **Look-ahead.** Holder/top10/dev/sniper/insider/bundler/liquidity/tax are applied as static values = the *first non-null* value seen. For tokens first seen
  with nulls (brand-new ones often have null holders/liquidity), that value arrives later than the early candles, so those filters see the future for them.
  `snapshot-export` prints how many tokens/fields are affected. `dev_flags` is the union over all snapshots (also look-ahead). The vendor may also revise or
  back-fill values; this tool does not verify them.
- **Selection / survivorship.** What you capture depends on which list a token is in at poll time (new / finalizing / migrated, top 50 by the vendor's ordering),
  and tokens that were rugged or removed may disappear before you see them. Dev wash-trade/insider tags are mostly null (not evaluated).
- **Tiny samples.** A few polls give a few dozen tokens with 2-5 points each; any backtest on that is a smoke test of the plumbing, not evidence of anything.
- **Semantics of vendor fields are the vendor's** (e.g. liquidity units on bonding-curve tokens, `progress` definition) and can change without notice.
- This is a third-party public endpoint intended for the Binance skill; it may change, throttle, or require auth at any time.

## Data format
CSV, long format (one row per candle, static columns repeated): `address,symbol,launch_time,platform,t_min,price`
plus optional `mcap`, `total_supply`, `graduation_mcap_usd`, `liquidity_usd`, `holders`, `top10_pct`, `dev_pct`,
`sniper_pct`, `insider_pct`, `bundler_pct`, `buy_tax_pct`, `sell_tax_pct`, `dev_flags` (`;`-separated), `synthetic`, and per-candle `progress_pct` (vendor bonding-curve progress; overrides the mcap-derived progress when present).
JSON: `{"tokens":[{...static fields..., "series":[{"t_min":0,"price":1e-6}, ...]}]}`.
`launch_time`: epoch seconds or ISO-8601. If `price` is missing, `mcap / total_supply` is used.

## Config example (`configs/example.yaml`)
```yaml
filters: {age_min_min: 5, age_max_min: 60, holders_min: 80, liquidity_min_usd: 5000, top10_max_pct: 55,
          dev_max_pct: 10, sniper_max_pct: 30, bundler_max_pct: 30, tax_max_pct: 8,
          mcap_min_usd: 7000, mcap_max_usd: 40000, exclude_dev_flags: [honeypot]}
exits:
  take_profits: [{at_gain_pct: 100, sell_fraction: 0.5}]   # fraction of the original position
  stop_loss_pct: 50
  trailing: {activate_gain_pct: 200, drawdown_pct: 35}
  time_stop_min: 240
execution: {position_size_usd: 100, fee_pct: 1.0, slippage_multiplier: 1.0, latency_candles: 1}
portfolio: {max_concurrent: 10, daily_loss_stop_usd: 500}
```
Unknown keys are rejected (typos do not pass silently). These values are illustrative, untuned, not recommendations.

## Simulation rules (so you can check them)
- Entry: first candle where all filters pass; fill `latency_candles` later at that candle's close.
- Triggers use candle **close** prices only. Order within a candle: stop loss, take-profit rungs, trailing, time stop.
- Slippage: constant-product estimate, `impact = mult * size / (liquidity/2)`; buy at `spot*(1+impact)`,
  sell at `spot/(1+impact)`. Fee and token tax are deducted per side.
- Max concurrent / daily loss stop (UTC day of realised PnL) gate new entries only.
- Missing data on a configured filter fails that filter (fail closed).
- PnL excluding top-N is only shown when there are more than N trades. Top-10 share is only shown when total PnL > 0.

## Limitations (read these)
- **No real-data guarantees.** Output is only as good as the file you feed it. Synthetic data is invented and says nothing about real markets.
  In the synthetic set, token attributes are independent of outcomes, so any filter "edge" there is noise by construction.
- **Idealised fills even with slippage.** Close-price fills, static pool liquidity (snapshot, not time-varying), no MEV/sandwiching,
  no failed or reverted transactions, no gas, no rugs that block sells (honeypots only via tax/flag fields), no sells that move the pool for the next sell.
  Real results would be worse.
- **Survivorship bias.** Public APIs list tokens that still exist; delisted/dead pools vanish. Any dataset built from them overstates outcomes.
- **Look-ahead risk.** Holder/bundler/sniper/liquidity values are single snapshots applied to the whole timeline; if they were measured after the entry time, filters see the future.
- **Small samples.** Bucket tables slice few trades many ways; the report flags n < 30 but multiple-comparison noise remains. No significance tests or confidence intervals in v1.
- Position sizing is fixed; no compounding, no bankroll, no capital-at-risk limits beyond the portfolio gates.
- Platform-specific mechanics (bonding-curve graduation, launchpad fees) are not modelled beyond the generic fee/tax fields.
- Not advice and not a signal generator. Do not trade based on this output.
