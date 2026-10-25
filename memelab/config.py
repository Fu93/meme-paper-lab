"""Config loading (YAML or JSON) with strict key validation (typos raise, never silently ignored)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .filters import FilterConfig


@dataclass
class TakeProfit:
    at_gain_pct: float
    sell_fraction: float  # fraction of the ORIGINAL position


@dataclass
class Trailing:
    activate_gain_pct: float
    drawdown_pct: float


@dataclass
class ExitConfig:
    take_profits: list[TakeProfit] = field(default_factory=list)
    stop_loss_pct: float | None = None
    trailing: Trailing | None = None
    time_stop_min: float | None = None  # minutes after the fill


@dataclass
class ExecConfig:
    position_size_usd: float = 100.0
    fee_pct: float = 1.0  # per side
    slippage_multiplier: float = 1.0  # 0 disables slippage; 1 = constant-product estimate
    latency_candles: int = 0


@dataclass
class PortfolioConfig:
    max_concurrent: int | None = None
    daily_loss_stop_usd: float | None = None


@dataclass
class Config:
    filters: FilterConfig = field(default_factory=FilterConfig)
    exits: ExitConfig = field(default_factory=ExitConfig)
    execution: ExecConfig = field(default_factory=ExecConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)


class ConfigError(ValueError):
    pass


def _build(cls, data: dict[str, Any] | None, where: str):
    data = data or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected a mapping")
    allowed = {f.name for f in fields(cls)}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}; allowed {sorted(allowed)}")
    return cls(**data)


def config_from_dict(d: dict[str, Any] | None) -> Config:
    d = d or {}
    unknown = set(d) - {"filters", "exits", "execution", "portfolio"}
    if unknown:
        raise ConfigError(f"top level: unknown keys {sorted(unknown)}")
    filters = _build(FilterConfig, d.get("filters"), "filters")
    ex = dict(d.get("exits") or {})
    tps = [_build(TakeProfit, t, "exits.take_profits[]") for t in ex.pop("take_profits", []) or []]
    trailing = ex.pop("trailing", None)
    trailing = _build(Trailing, trailing, "exits.trailing") if trailing else None
    exits = _build(ExitConfig, ex, "exits")
    exits.take_profits = sorted(tps, key=lambda t: t.at_gain_pct)
    exits.trailing = trailing
    execution = _build(ExecConfig, d.get("execution"), "execution")
    portfolio = _build(PortfolioConfig, d.get("portfolio"), "portfolio")
    cfg = Config(filters, exits, execution, portfolio)
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    e, x = cfg.exits, cfg.execution
    total = sum(t.sell_fraction for t in e.take_profits)
    if any(not (0 < t.sell_fraction <= 1) for t in e.take_profits) or total > 1 + 1e-9:
        raise ConfigError("exits.take_profits: each sell_fraction in (0,1] and sum <= 1")
    if any(t.at_gain_pct <= 0 for t in e.take_profits):
        raise ConfigError("exits.take_profits: at_gain_pct must be > 0")
    if e.stop_loss_pct is not None and not (0 < e.stop_loss_pct <= 100):
        raise ConfigError("exits.stop_loss_pct must be in (0,100]")
    if e.trailing and not (0 < e.trailing.drawdown_pct < 100 and e.trailing.activate_gain_pct > 0):
        raise ConfigError("exits.trailing: activate_gain_pct > 0 and 0 < drawdown_pct < 100")
    if e.time_stop_min is not None and e.time_stop_min <= 0:
        raise ConfigError("exits.time_stop_min must be > 0")
    if x.position_size_usd <= 0 or x.fee_pct < 0 or x.fee_pct >= 100:
        raise ConfigError("execution: position_size_usd > 0 and 0 <= fee_pct < 100")
    if x.slippage_multiplier < 0 or x.latency_candles < 0:
        raise ConfigError("execution: slippage_multiplier >= 0 and latency_candles >= 0")
    if cfg.portfolio.max_concurrent is not None and cfg.portfolio.max_concurrent < 1:
        raise ConfigError("portfolio.max_concurrent must be >= 1")


def default_config() -> Config:
    """Illustrative defaults. They are NOT recommendations and are not tuned on anything."""
    return config_from_dict(
        {
            "filters": {
                "age_min_min": 5,
                "age_max_min": 60,
                "holders_min": 80,
                "liquidity_min_usd": 5000,
                "top10_max_pct": 55,
                "dev_max_pct": 10,
                "sniper_max_pct": 30,
                "bundler_max_pct": 30,
                "tax_max_pct": 8,
                "mcap_min_usd": 7000,
                "mcap_max_usd": 40000,
                "exclude_dev_flags": ["honeypot"],
            },
            "exits": {
                "take_profits": [{"at_gain_pct": 100, "sell_fraction": 0.5}],
                "stop_loss_pct": 50,
                "trailing": {"activate_gain_pct": 200, "drawdown_pct": 35},
                "time_stop_min": 240,
            },
            "execution": {"position_size_usd": 100, "fee_pct": 1.0, "slippage_multiplier": 1.0, "latency_candles": 1},
            "portfolio": {"max_concurrent": 10, "daily_loss_stop_usd": 500},
        }
    )


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return default_config()
    p = Path(path)
    text = p.read_text()
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise ConfigError("PyYAML not installed; use a JSON config or `pip install pyyaml`") from exc
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    return config_from_dict(raw)


def config_to_dict(cfg: Config) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(cfg)
