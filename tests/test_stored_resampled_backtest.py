"""
Botragram

Description:
    Unit tests for BacktestService execution using StoredResampledCandleProvider.

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
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import (
    Interval,
    MarketType,
    SignalType,
    StrategyType,
)
from botragram.models import BacktestRequest, Candle, Signal
from botragram.services.backtest_service import BacktestService
from botragram.services.stored_resampled_candle_provider import (
    StoredResampledCandleProvider,
)
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)
from botragram.strategies.base import BaseStrategy


# =============================================================================
# Test Doubles
# =============================================================================
class SimpleBacktestStrategy(BaseStrategy):
    """Buy on first candle and exit on profit."""

    __slots__ = ()

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        self.validate_candles(candles=candles)
        candle = candles[-1]
        return Signal(
            symbol=candle.symbol,
            signal_type=(SignalType.BUY if len(candles) == 1 else SignalType.HOLD),
            price=candle.close_price,
            confidence=Decimal("1"),
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason="Deterministic test signal",
        )


def _make_1m_candle(
    *,
    symbol: str = "BTCUSDT",
    open_time: datetime,
    price: str,
) -> Candle:
    p = Decimal(price)
    return Candle(
        symbol=symbol,
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=p,
        high_price=p + Decimal("1"),
        low_price=p - Decimal("1"),
        close_price=p,
        volume=Decimal("10.0"),
    )


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_stored_resampled_backtest_m5() -> None:
    """Run BacktestService on 5m candles resampled from local SQLite 1m candles."""
    database = SQLiteDatabase(database_path=":memory:")
    await database.connect()
    try:
        await SQLiteMigrationManager(database=database).initialize()
        sqlite_repo = SQLiteCandleRepository(database=database)

        base_time = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        # Generate 60 minutes of 1m candles (12 5m candles)
        candles = [
            _make_1m_candle(
                open_time=base_time + timedelta(minutes=i),
                price=f"{1000 + i}",
            )
            for i in range(60)
        ]
        await sqlite_repo.save_many(candles=candles)

        provider = StoredResampledCandleProvider(
            candle_repository=sqlite_repo,
            source_interval=Interval.M1,
        )

        strategy = SimpleBacktestStrategy()
        risk_settings = RiskSettings(
            stop_loss_pct=Decimal("0.05"),
            take_profit_pct=Decimal("0.10"),
            max_open_positions=1,
        )
        engine = BacktestEngine(
            strategy=strategy,
            risk_settings=risk_settings,
        )
        service = BacktestService(
            exchange_client=provider,
            engine=engine,
        )

        request = BacktestRequest(
            symbol="BTCUSDT",
            market_type=MarketType.FUTURES,
            strategy_type=StrategyType.EMA_SCALPING,
            interval=Interval.M5,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=59),
            initial_balance=Decimal("10000"),
            max_candles=100,
        )

        result = await service.run(request=request)

        assert result.request.symbol == "BTCUSDT"
        assert result.request.interval == Interval.M5
        assert result.candle_count == 12
        assert result.metrics.initial_balance == Decimal("10000")
    finally:
        await database.close()
