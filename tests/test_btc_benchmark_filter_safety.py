"""
Botragram

Description:
    Regression tests verifying the BTC benchmark trend filter fails closed
    when data is insufficient or unavailable, and allows bypass only when disabled.

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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType, StrategyType
from botragram.indicators.trend.mtf_trend_filter import (
    TrendDirection,
    evaluate_mtf_trend,
)
from botragram.models import Candle, Signal
from botragram.services import OpportunityDiscoveryService

# =============================================================================
# Constants & Test Fixtures
# =============================================================================
_NOW: Final[datetime] = datetime(2026, 9, 24, 0, 0, 0, tzinfo=UTC)


class FakeMarketService:
    """Fake MarketService with controllable candle responses or error injection."""

    def __init__(
        self,
        candles_by_symbol: dict[str, Sequence[Candle]],
        raise_on_btc: bool = False,
    ) -> None:
        self.candles_by_symbol = candles_by_symbol
        self.raise_on_btc = raise_on_btc

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        del quote_asset
        return tuple(self.candles_by_symbol.keys())

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        persist: bool = True,
        prefer_stored: bool = True,
        as_of: datetime | None = None,
    ) -> Sequence[Candle]:
        del interval, limit, persist, prefer_stored, as_of
        if symbol == "BTCUSDT" and self.raise_on_btc:
            raise ConnectionError("Network failure fetching BTC candles")
        return self.candles_by_symbol.get(symbol, ())


class FakeStrategyService:
    """Fake StrategyService returning predefined signals."""

    def __init__(self, signals: dict[str, Signal], minimum_candles: int = 1) -> None:
        self.signals = signals
        self.minimum_candles = minimum_candles

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        del strategy_type
        sym = candles[0].symbol if candles else ""
        signal = self.signals.get(sym)
        if signal is None:
            raise ValueError(f"No signal configured for {sym}")
        return signal

    def get_minimum_candles(self, strategy_type: StrategyType) -> int:
        del strategy_type
        return self.minimum_candles

    async def save_signal(self, *, signal: Signal) -> None:
        del signal

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        return self.generate_signal(candles=candles, strategy_type=strategy_type)


def _make_candle(symbol: str, close: Decimal, timestamp: datetime) -> Candle:
    return Candle(
        symbol=symbol,
        interval=Interval.M15,
        open_time=timestamp - timedelta(minutes=15),
        close_time=timestamp,
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
        volume=Decimal("100"),
    )


# =============================================================================
# Tests
# =============================================================================
def test_evaluate_mtf_trend_fail_closed_on_insufficient_data() -> None:
    """When fail_closed=True and data < ema_period, both buy and sell are denied."""
    candles = [_make_candle("BTCUSDT", Decimal("60000"), _NOW)]

    # Default fail_closed=False permits neutral alignment
    open_result = evaluate_mtf_trend(candles, ema_period=50, fail_closed=False)
    assert open_result.direction is TrendDirection.NEUTRAL
    assert open_result.is_aligned_with_buy is True
    assert open_result.is_aligned_with_sell is True

    # fail_closed=True denies both buy and sell
    closed_result = evaluate_mtf_trend(candles, ema_period=50, fail_closed=True)
    assert closed_result.direction is TrendDirection.NEUTRAL
    assert closed_result.is_aligned_with_buy is False
    assert closed_result.is_aligned_with_sell is False


@pytest.mark.asyncio
async def test_btc_benchmark_bullish_allows_buy_denies_sell() -> None:
    """Bullish BTC trend allows BUY and rejects SELL for crypto assets."""
    # 55 ascending candles (50k -> 60k)
    btc_candles = [
        _make_candle(
            "BTCUSDT",
            Decimal(50000 + i * 200),
            _NOW - timedelta(minutes=15 * (55 - i)),
        )
        for i in range(55)
    ]
    eth_candles = [_make_candle("ETHUSDT", Decimal("3000"), _NOW)]

    market_service = FakeMarketService(
        candles_by_symbol={"BTCUSDT": btc_candles, "ETHUSDT": eth_candles}
    )

    # 1. Test BUY signal on ETHUSDT -> ACCEPTED
    buy_strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                price=Decimal("3000"),
                stop_loss=Decimal("2900"),
                take_profit=Decimal("3200"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=buy_strategy,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )
    buy_signals = await discovery.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(buy_signals) == 1
    assert buy_signals[0].signal_type is SignalType.BUY

    # 2. Test SELL signal on ETHUSDT -> REJECTED
    sell_strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.SELL,
                price=Decimal("3000"),
                stop_loss=Decimal("3100"),
                take_profit=Decimal("2800"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery_sell = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=sell_strategy,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )
    sell_signals = await discovery_sell.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(sell_signals) == 0


@pytest.mark.asyncio
async def test_btc_benchmark_bearish_allows_sell_denies_buy() -> None:
    """Bearish BTC trend allows SELL and rejects BUY for crypto assets."""
    # 55 descending candles (60k -> 50k)
    btc_candles = [
        _make_candle(
            "BTCUSDT",
            Decimal(60000 - i * 200),
            _NOW - timedelta(minutes=15 * (55 - i)),
        )
        for i in range(55)
    ]
    eth_candles = [_make_candle("ETHUSDT", Decimal("3000"), _NOW)]

    market_service = FakeMarketService(
        candles_by_symbol={"BTCUSDT": btc_candles, "ETHUSDT": eth_candles}
    )

    # 1. Test BUY signal on ETHUSDT -> REJECTED
    buy_strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                price=Decimal("3000"),
                stop_loss=Decimal("2900"),
                take_profit=Decimal("3200"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=buy_strategy,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )
    buy_signals = await discovery.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(buy_signals) == 0

    # 2. Test SELL signal on ETHUSDT -> ACCEPTED
    sell_strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.SELL,
                price=Decimal("3000"),
                stop_loss=Decimal("3100"),
                take_profit=Decimal("2800"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery_sell = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=sell_strategy,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )
    sell_signals = await discovery_sell.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(sell_signals) == 1
    assert sell_signals[0].signal_type is SignalType.SELL


@pytest.mark.asyncio
async def test_btc_benchmark_insufficient_data_fails_closed() -> None:
    """When BTC candles are insufficient (< 50), all crypto signals are rejected."""
    # Only 10 candles available
    btc_candles = [
        _make_candle(
            "BTCUSDT",
            Decimal("60000"),
            _NOW - timedelta(minutes=15 * (10 - i)),
        )
        for i in range(10)
    ]
    eth_candles = [_make_candle("ETHUSDT", Decimal("3000"), _NOW)]

    market_service = FakeMarketService(
        candles_by_symbol={"BTCUSDT": btc_candles, "ETHUSDT": eth_candles}
    )
    strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                price=Decimal("3000"),
                stop_loss=Decimal("2900"),
                take_profit=Decimal("3200"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )

    signals = await discovery.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(signals) == 0


@pytest.mark.asyncio
async def test_btc_benchmark_fetch_error_fails_closed() -> None:
    """When BTC candles fetch raises an error, all crypto signals are rejected."""
    eth_candles = [_make_candle("ETHUSDT", Decimal("3000"), _NOW)]

    market_service = FakeMarketService(
        candles_by_symbol={"ETHUSDT": eth_candles},
        raise_on_btc=True,
    )
    strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                price=Decimal("3000"),
                stop_loss=Decimal("2900"),
                take_profit=Decimal("3200"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )

    signals = await discovery.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(signals) == 0


@pytest.mark.asyncio
async def test_btc_benchmark_filter_disabled_bypasses() -> None:
    """When btc_trend_filter_enabled=False, signals are accepted without BTC check."""
    # No BTC candles even in market service
    eth_candles = [_make_candle("ETHUSDT", Decimal("3000"), _NOW)]

    market_service = FakeMarketService(
        candles_by_symbol={"ETHUSDT": eth_candles},
        raise_on_btc=True,  # Would fail if checked
    )
    strategy = FakeStrategyService(
        signals={
            "ETHUSDT": Signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                price=Decimal("3000"),
                stop_loss=Decimal("2900"),
                take_profit=Decimal("3200"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    discovery = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy,
        btc_trend_filter_enabled=False,  # Disabled
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=50,
        utc_now=lambda: _NOW,
    )

    signals = await discovery.discover_symbols(
        symbols=("ETHUSDT",),
        interval=Interval.M15,
        candle_limit=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(signals) == 1
    assert signals[0].symbol == "ETHUSDT"
