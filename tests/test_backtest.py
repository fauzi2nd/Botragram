"""
Botragram

Description:
    Deterministic historical backtest tests.

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
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.backtest_command import parse_backtest_request
from botragram.config.risk_settings import RiskSettings
from botragram.engine import BacktestEngine
from botragram.enums import (
    Interval,
    MarketType,
    PositionSide,
    SignalType,
    StrategyType,
)
from botragram.models import BacktestRequest, BacktestResult, Candle, Signal
from botragram.services.backtest_service import BacktestService
from botragram.strategies.base import BaseStrategy

# =============================================================================
# Constants
# =============================================================================
_START_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Test Doubles
# =============================================================================
class BuyThenHoldStrategy(BaseStrategy):
    """Open once and hold so candle protection controls the exit."""

    __slots__ = ()

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy profile used for risk levels."""
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        """Allow a signal from the first replay candle."""
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        """Buy on the first candle and hold on later candles."""
        self.validate_candles(candles=candles)
        candle = candles[-1]
        return Signal(
            symbol=candle.symbol,
            signal_type=(SignalType.BUY if len(candles) == 1 else SignalType.HOLD),
            price=candle.close_price,
            confidence=Decimal("1"),
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason="Deterministic backtest signal",
        )


@dataclass(slots=True, kw_only=True)
class HistoricalCandleStub:
    """Return deterministic pages while recording pagination cursors."""

    candles: tuple[Candle, ...]
    cursors: list[datetime]

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return the next filtered candle page."""
        del symbol, interval
        if start_time is None or end_time is None:
            raise AssertionError("Backtest pagination requires explicit boundaries")
        self.cursors.append(start_time)
        return tuple(
            candle
            for candle in self.candles
            if start_time <= candle.open_time <= end_time
        )[:limit]


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candle(
    *,
    minute: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> Candle:
    """Create one chronological one-minute candle."""
    open_time = _START_TIME + timedelta(minutes=minute)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal("1"),
    )


def _create_request() -> BacktestRequest:
    """Create a small isolated Futures backtest request."""
    return BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=2),
        initial_balance=Decimal("100"),
    )


# =============================================================================
# Engine Tests
# =============================================================================
def test_backtest_uses_stop_loss_first_when_one_candle_hits_both_exits() -> None:
    """Enforce the documented conservative SL-first OHLC policy."""
    result = asyncio.run(_run_ambiguous_candle_backtest())

    assert result.candle_count == 2
    assert result.metrics.total_trades == 1
    assert result.metrics.long_trades == 1
    assert result.metrics.losing_trades == 1
    assert result.metrics.net_pnl < 0
    assert result.trades[0].side is PositionSide.LONG
    assert result.trades[0].reason == "Paper stop-loss triggered"


async def _run_ambiguous_candle_backtest() -> BacktestResult:
    """Replay a candle whose range crosses both configured exit levels."""
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=RiskSettings(leverage=10),
    )
    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="101",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100",
            high_price="110",
            low_price="90",
            close_price="100",
        ),
    )
    return await engine.run(request=_create_request(), candles=candles)


# =============================================================================
# CLI Tests
# =============================================================================
def test_backtest_cli_parses_dates_as_an_inclusive_utc_range() -> None:
    """Normalize date-only command boundaries without local-time ambiguity."""
    request = parse_backtest_request(
        arguments=(
            "backtest",
            "--market-type",
            "spot",
            "--symbol",
            "ethusdt",
            "--interval",
            "15m",
            "--strategy",
            "ema_cross",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-02",
            "--balance",
            "1",
        )
    )

    assert request.symbol == "ETHUSDT"
    assert request.market_type is MarketType.SPOT
    assert request.start_time == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert request.end_time == datetime(
        2026,
        1,
        2,
        23,
        59,
        59,
        999999,
        tzinfo=timezone.utc,
    )
    assert request.initial_balance == Decimal("1")


def test_backtest_service_paginates_ranges_larger_than_exchange_limit() -> None:
    """Load every candle without duplication across Binance-sized pages."""
    result, provider = asyncio.run(_run_paginated_backtest())

    assert result.candle_count == 1_001
    assert len(provider.cursors) == 2
    assert provider.cursors[1] == _START_TIME + timedelta(minutes=1_000)


async def _run_paginated_backtest() -> tuple[BacktestResult, HistoricalCandleStub]:
    """Run a replay spanning two historical provider pages."""
    candles = tuple(
        _create_candle(
            minute=minute,
            open_price="100",
            high_price="100.1",
            low_price="99.9",
            close_price="100",
        )
        for minute in range(1_001)
    )
    provider = HistoricalCandleStub(candles=candles, cursors=[])
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_START_TIME,
        end_time=_START_TIME + timedelta(minutes=1_000),
        initial_balance=Decimal("100"),
    )
    service = BacktestService(
        exchange_client=provider,
        engine=BacktestEngine(
            strategy=BuyThenHoldStrategy(),
            risk_settings=RiskSettings(leverage=10),
        ),
    )
    return await service.run(request=request), provider
