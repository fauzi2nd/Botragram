"""
Botragram

Description:
    Immutable backtest request and result models.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, MarketType, PositionSide, StrategyType

__all__ = [
    "BacktestMetrics",
    "BacktestRequest",
    "BacktestResult",
    "BacktestTrade",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestRequest:
    """Define one deterministic historical strategy simulation."""

    symbol: str
    interval: Interval
    strategy_type: StrategyType
    market_type: MarketType
    start_time: datetime
    end_time: datetime
    initial_balance: Decimal
    fee_rate: Decimal = Decimal("0.001")
    slippage_rate: Decimal = Decimal("0.0005")
    max_candles: int = 100_000
    data_source: str = "auto"
    database_path: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate request boundaries."""
        normalized_symbol = self.symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Backtest symbol must not be empty")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("Backtest datetimes must be timezone-aware")
        if self.start_time >= self.end_time:
            raise ValueError("Backtest start time must be before end time")
        if self.initial_balance <= 0:
            raise ValueError("Backtest initial balance must be greater than zero")
        if not Decimal("0") <= self.fee_rate < Decimal("1"):
            raise ValueError("Backtest fee rate must be between zero and one")
        if not Decimal("0") <= self.slippage_rate < Decimal("1"):
            raise ValueError("Backtest slippage rate must be between zero and one")
        if self.max_candles <= 0:
            raise ValueError("Backtest candle limit must be greater than zero")

        normalized_data_source = self.data_source.strip().lower()
        if normalized_data_source not in ("auto", "local", "exchange"):
            raise ValueError(
                "Backtest data source must be 'auto', 'local', or 'exchange'"
            )

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "data_source", normalized_data_source)


@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestTrade:
    """Describe one completed simulated position."""

    side: PositionSide
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    fees: Decimal
    realized_pnl: Decimal
    reason: str


@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestMetrics:
    """Summarize portfolio and execution performance."""

    initial_balance: Decimal
    final_balance: Decimal
    net_pnl: Decimal
    return_pct: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: Decimal
    profit_factor: Decimal | None
    max_drawdown_pct: Decimal
    total_fees: Decimal
    long_trades: int
    short_trades: int


@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestResult:
    """Contain a complete reproducible backtest result."""

    request: BacktestRequest
    candle_count: int
    trades: tuple[BacktestTrade, ...]
    metrics: BacktestMetrics
    warnings: tuple[str, ...] = ()
    venue_name: str = "Binance Mainnet"
    data_source_description: str = "Exchange REST"
