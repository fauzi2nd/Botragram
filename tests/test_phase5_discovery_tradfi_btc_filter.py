"""
Botragram

Description:
    Unit and regression tests for Phase 5: BTC trend benchmark filtering
    restricted exclusively to crypto assets, bypassing TradFi/CFD.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

import pytest

from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.services import OpportunityDiscoveryService

_NOW: Final[datetime] = datetime(2026, 9, 24, 0, 0, 0, tzinfo=UTC)


class FakeMarketService:
    def __init__(self, candles_by_symbol: dict[str, Sequence[Candle]]) -> None:
        self.candles_by_symbol = candles_by_symbol

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
        return self.candles_by_symbol.get(symbol, ())


class FakeStrategyService:
    def __init__(
        self,
        signals: dict[str, Signal],
        minimum_candles: int = 1,
    ) -> None:
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

    async def save_signal(
        self,
        *,
        signal: Signal,
    ) -> None:
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


@pytest.mark.asyncio
async def test_btc_filter_bypasses_tradfi_symbols() -> None:
    """Verify TradFi symbols bypass BTC trend filter while Crypto is filtered."""
    # Generate BTC candles with strong UPTREND (closing prices rising: 50k -> 60k)
    btc_candles = [
        _make_candle(
            "BTCUSDT",
            Decimal(50000 + i * 1000),
            _NOW - timedelta(minutes=15 * (10 - i)),
        )
        for i in range(11)
    ]

    # Target symbols:
    # 1. ETHUSDT (Crypto): SELL signal conflicts with BTC uptrend -> REJECTED
    # 2. XAUUSD (Commodity): SELL signal (TradFi) -> ACCEPTED despite BTC uptrend
    eth_candles = [_make_candle("ETHUSDT", Decimal("3000"), _NOW)]
    gold_candles = [_make_candle("XAUUSD", Decimal("2650"), _NOW)]

    market_service = FakeMarketService(
        candles_by_symbol={
            "BTCUSDT": btc_candles,
            "ETHUSDT": eth_candles,
            "XAUUSD": gold_candles,
        }
    )

    strategy_service = FakeStrategyService(
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
            ),
            "XAUUSD": Signal(
                symbol="XAUUSD",
                signal_type=SignalType.SELL,
                price=Decimal("2650"),
                stop_loss=Decimal("2670"),
                take_profit=Decimal("2610"),
                confidence=Decimal("0.85"),
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            ),
        }
    )

    discovery_service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        btc_trend_filter_enabled=True,
        btc_trend_interval=Interval.M15,
        btc_trend_ema_period=10,
        utc_now=lambda: _NOW,
    )

    signals = await discovery_service.discover_symbols(
        symbols=("ETHUSDT", "XAUUSD"),
        interval=Interval.M15,
        candle_limit=1,
        top_n=2,
        strategy_type=StrategyType.EMA_CROSS,
    )

    # ETHUSDT was rejected by BTC trend filter
    # XAUUSD bypassed BTC filter and was returned
    assert len(signals) == 1
    assert signals[0].symbol == "XAUUSD"
    assert signals[0].signal_type is SignalType.SELL
