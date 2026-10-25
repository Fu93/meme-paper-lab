"""SYNTHETIC data generator. Everything here is invented. It is NOT a model of any real market.

Design intent: heavy-tailed outcomes (most tokens bleed/rug, a few percent pump with a Pareto-
distributed peak multiple) so the report demonstrates tail dependence. Token attributes
(holders, bundler %, ...) are drawn INDEPENDENTLY of outcomes by default, so filters carry no
information by construction: any "edge" a filter appears to show in the demo is noise.
"""
from __future__ import annotations

import math
import random

from .models import Candle, TokenLaunch

BASE_TIME = 1_735_689_600  # 2025-01-01T00:00:00Z, arbitrary


def _path(rng: random.Random, n: int, kind: str, p0: float) -> list[float]:
    """Log-price path of n points."""
    lp = [math.log(p0)]
    sigma = 0.05
    rug_at = rng.randint(2, 40)
    moon_start = rng.randint(1, 30)
    moon_len = rng.randint(3, 20)
    peak = min(500.0, 2.0 * (1 - rng.random()) ** (-1 / 1.1))  # Pareto(alpha=1.1) tail, capped
    rug_mult = rng.uniform(0.02, 0.3)
    for i in range(1, n):
        r = rng.gauss(0, sigma)
        if kind == "rug":
            drift = -0.002
            if i == rug_at:
                r += math.log(rug_mult)
            elif i > rug_at:
                drift, r = -0.003, rng.gauss(0, 0.02)
        elif kind == "bleed":
            drift = -0.006
        elif kind == "chop":
            drift = -0.0005
        else:  # moon: ramp to `peak`x, then decay
            if moon_start <= i < moon_start + moon_len:
                drift = math.log(peak) / moon_len
            elif i >= moon_start + moon_len:
                drift = -0.012
            else:
                drift = 0.0
        lp.append(lp[-1] + drift + r)
    return [math.exp(x) for x in lp]


def generate(n_tokens: int = 2000, seed: int = 7, step_min: int = 5, hours: int = 24,
             days: int = 30, moon_frac: float = 0.05) -> list[TokenLaunch]:
    rng = random.Random(seed)
    n = hours * 60 // step_min + 1
    kinds = ["rug", "bleed", "chop", "moon"]
    rest = 1.0 - moon_frac
    weights = [0.42 * rest / 0.95, 0.40 * rest / 0.95, 0.13 * rest / 0.95, moon_frac]
    platforms = ["SYNTH-launchpad-A", "SYNTH-launchpad-B", "SYNTH-agent-pad"]
    out: list[TokenLaunch] = []
    times = sorted(rng.randrange(days * 86400) for _ in range(n_tokens))
    for i in range(n_tokens):
        kind = rng.choices(kinds, weights)[0]
        mcap0 = math.exp(rng.gauss(math.log(5000), 0.5))
        supply = 1e9
        prices = _path(rng, n, kind, mcap0 / supply)
        out.append(
            TokenLaunch(
                address=f"0xSYNTH{i:035d}",
                symbol=f"SYN{i:04d}",
                launch_time=BASE_TIME + times[i],
                platform=rng.choice(platforms),
                candles=[Candle(float(j * step_min), p) for j, p in enumerate(prices)],
                total_supply=supply,
                graduation_mcap_usd=69_000.0,
                liquidity_usd=math.exp(rng.gauss(math.log(15000), 0.6)),
                holders=int(math.exp(rng.gauss(math.log(250), 0.8))),
                top10_pct=rng.uniform(10, 70),
                dev_pct=rng.uniform(0, 15),
                sniper_pct=rng.uniform(0, 40),
                insider_pct=rng.uniform(0, 30),
                bundler_pct=rng.uniform(0, 40),
                buy_tax_pct=rng.choices([0.0, rng.uniform(1, 12)], [0.85, 0.15])[0],
                sell_tax_pct=rng.choices([0.0, rng.uniform(1, 12)], [0.85, 0.15])[0],
                dev_flags=tuple(rng.choices([(), ("honeypot",), ("dev_sold",)], [0.9, 0.04, 0.06])[0]),
                synthetic=True,
            )
        )
    return out
