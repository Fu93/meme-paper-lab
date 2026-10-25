import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memelab.config import Config, ExecConfig, ExitConfig, PortfolioConfig, TakeProfit, Trailing  # noqa: E402
from memelab.filters import FilterConfig  # noqa: E402
from memelab.models import Candle, TokenLaunch  # noqa: E402


def make_token(prices, *, addr="0xA", launch=1_000_000, step=5, liquidity=1e9, **kw):
    return TokenLaunch(
        address=addr, symbol="T", launch_time=launch, platform="P",
        candles=[Candle(float(i * step), p) for i, p in enumerate(prices)],
        total_supply=1000.0, liquidity_usd=liquidity, **kw,
    )


def make_cfg(*, tps=(), stop=None, trailing=None, time_stop=None, fee=0.0, slip=0.0, latency=0,
             size=100.0, max_conc=None, daily=None, filters=None):
    return Config(
        filters=filters or FilterConfig(),
        exits=ExitConfig(
            take_profits=[TakeProfit(*t) for t in tps], stop_loss_pct=stop,
            trailing=Trailing(*trailing) if trailing else None, time_stop_min=time_stop,
        ),
        execution=ExecConfig(position_size_usd=size, fee_pct=fee, slippage_multiplier=slip, latency_candles=latency),
        portfolio=PortfolioConfig(max_concurrent=max_conc, daily_loss_stop_usd=daily),
    )
