# memelab paper report

> **DATA: SYNTHETIC (invented random data, not market data; results mean nothing about real markets)**

> Paper simulation only. Software output, not investment advice, no signal, no promise of returns. No real trades were made. You bear your own risk.

> **WARNING: PnL excluding the top 5 winners is negative (-5226.29 USD).**
> **WARNING: PnL excluding the top 10 winners is negative (-5927.33 USD).**
> **WARNING: PnL excluding the top 20 winners is negative (-6187.74 USD).**

## Summary (USD, simulated)

| metric | value |
|---|---|
| tokens in dataset | 2000 |
| trades | 135 |
| position size | 100 |
| win rate | 17.8% |
| median trade | -43.48 |
| mean trade | -20.45 |
| total PnL | -2761.15 |
| total PnL excluding top 5 winners | -5226.29 |
| total PnL excluding top 10 winners | -5927.33 |
| total PnL excluding top 20 winners | -6187.74 |
| top-10 share of total PnL | n/a (total PnL <= 0) |
| max drawdown (realised, by exit time) | 3074.76 |

## By token age at entry decision (minutes)

| bucket | n | win rate | median | total PnL | note |
|---|---|---|---|---|---|
| 5-15 | 107 | 15.0% | -48.83 | -3081.82 |  |
| 15-60 | 24 | 33.3% | -25.19 | +510.27 | small n (<30) |
| 60-240 | 4 | 0.0% | -46.71 | -189.60 | small n (<30) |

## By bundler % (supply)

| bucket | n | win rate | median | total PnL | note |
|---|---|---|---|---|---|
| 0-5 | 19 | 21.1% | -55.68 | -113.10 | small n (<30) |
| 5-10 | 26 | 7.7% | -33.41 | -1094.66 | small n (<30) |
| 10-20 | 45 | 20.0% | -36.30 | -507.67 |  |
| 20-40 | 45 | 20.0% | -43.93 | -1045.73 |  |

## By sniper % (supply)

| bucket | n | win rate | median | total PnL | note |
|---|---|---|---|---|---|
| 0-5 | 22 | 31.8% | -41.53 | -168.06 | small n (<30) |
| 5-10 | 23 | 17.4% | -46.43 | -761.99 | small n (<30) |
| 10-20 | 52 | 15.4% | -45.08 | -1430.36 |  |
| 20-40 | 38 | 13.2% | -38.00 | -400.74 |  |

## Exits and funnel

Exit reasons: stop_loss=58, time_stop=71, trailing_stop=6

Funnel: no_candle_passed_filters=1865, passed_filters=135, traded=135

Filters that never passed on any evaluated candle (tokens blocked): bundler=485, dev=658, dev_flags=87, holders=145, liquidity=69, mcap=1309, sniper=481, tax=197, top10=477

## Caveats

- Fills are idealised (close prices, static pool liquidity, no MEV, no failed txs). Real results would be worse.
- Static token attributes are snapshots applied to the whole timeline (possible look-ahead).
- Bucket tables slice a small sample many ways; differences are mostly noise.
- Built by an AI agent; not audited. Paper simulation only. Software output, not investment advice, no signal, no promise of returns. No real trades were made. You bear your own risk.
