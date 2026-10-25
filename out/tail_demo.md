# memelab paper report

> **DATA: SYNTHETIC (invented random data, not market data; results mean nothing about real markets)**

> Paper simulation only. Software output, not investment advice, no signal, no promise of returns. No real trades were made. You bear your own risk.

> **WARNING: Top-10 winners account for 425% of total PnL (> 80%): results depend on a handful of outliers.**
> **WARNING: PnL excluding the top 5 winners is negative (-34101.23 USD).**
> **WARNING: PnL excluding the top 10 winners is negative (-42928.65 USD).**
> **WARNING: PnL excluding the top 20 winners is negative (-51283.57 USD).**

## Summary (USD, simulated)

| metric | value |
|---|---|
| tokens in dataset | 2000 |
| trades | 2000 |
| position size | 100 |
| win rate | 22.7% |
| median trade | -46.10 |
| mean trade | +6.60 |
| total PnL | +13194.49 |
| total PnL excluding top 5 winners | -34101.23 |
| total PnL excluding top 10 winners | -42928.65 |
| total PnL excluding top 20 winners | -51283.57 |
| top-10 share of total PnL | 425.4% |
| max drawdown (realised, by exit time) | 11650.06 |

## By token age at entry decision (minutes)

| bucket | n | win rate | median | total PnL | note |
|---|---|---|---|---|---|
| 5-15 | 2000 | 22.7% | -46.10 | +13194.49 |  |

## By bundler % (supply)

| bucket | n | win rate | median | total PnL | note |
|---|---|---|---|---|---|
| 0-5 | 257 | 18.3% | -48.56 | -6606.82 |  |
| 5-10 | 227 | 27.3% | -45.49 | +4159.04 |  |
| 10-20 | 494 | 23.5% | -39.63 | +13293.63 |  |
| 20-40 | 1022 | 22.4% | -50.09 | +2348.64 |  |

## By sniper % (supply)

| bucket | n | win rate | median | total PnL | note |
|---|---|---|---|---|---|
| 0-5 | 252 | 23.4% | -42.38 | -4212.21 |  |
| 5-10 | 247 | 22.3% | -49.21 | -2469.10 |  |
| 10-20 | 503 | 24.5% | -39.59 | -1189.51 |  |
| 20-40 | 998 | 21.7% | -50.31 | +21065.31 |  |

## Exits and funnel

Exit reasons: stop_loss=972, time_stop=978, trailing_stop=50

Funnel: passed_filters=2000, traded=2000

## Caveats

- Fills are idealised (close prices, static pool liquidity, no MEV, no failed txs). Real results would be worse.
- Static token attributes are snapshots applied to the whole timeline (possible look-ahead).
- Bucket tables slice a small sample many ways; differences are mostly noise.
- Built by an AI agent; not audited. Paper simulation only. Software output, not investment advice, no signal, no promise of returns. No real trades were made. You bear your own risk.
