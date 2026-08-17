"""
Botragram

Description:
    Bounded market opportunity discovery service tests.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType
from botragram.models import Candle, Signal
from botragram.services import OpportunityDiscoveryService

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 8, 17, tzinfo=UTC)


# =============================================================================
# Test Fakes
# =============================================================================
@dataclass(slots=True)
class FakeMarketService:
    """Provide a deterministic and unordered market universe."""

    symbols: tuple[str, ...]
    failing_symbol: str | None = None
    block_candles: bool = False
    requested_symbols: list[str] = field(default_factory=list[str])
    persist_values: list[bool] = field(default_factory=list[bool])
    candle_started: asyncio.Event = field(default_factory=asyncio.Event)
    active_candle_requests: int = 0
    maximum_active_candle_requests: int = 0

    async def get_trading_symbols(self, *, quote_asset: str) -> tuple[str, ...]:
        """Return the configured exchange universe."""
        assert quote_asset == "USDT"
        return self.symbols

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        persist: bool = True,
    ) -> tuple[Candle, ...]:
        """Return one symbol-identifying candle."""
        assert interval is Interval.M15
        assert limit == 100
        self.requested_symbols.append(symbol)
        self.persist_values.append(persist)
        self.active_candle_requests += 1
        self.maximum_active_candle_requests = max(
            self.maximum_active_candle_requests,
            self.active_candle_requests,
        )

        try:
            self.candle_started.set()

            if symbol == self.failing_symbol:
                raise RuntimeError(f"Candle retrieval failed for {symbol}")

            if self.block_candles:
                await asyncio.Event().wait()

            await asyncio.sleep(0)
            return (_create_candle(symbol=symbol),)
        finally:
            self.active_candle_requests -= 1


@dataclass(slots=True)
class FakeStrategyService:
    """Generate configured signals and record persistence calls."""

    signals: dict[str, Signal]
    saved_symbols: list[str] = field(default_factory=list[str])

    async def generate_and_save(self, *, candles: Sequence[Candle]) -> Signal:
        """Return and record the signal for the candle symbol."""
        symbol = candles[0].symbol
        self.saved_symbols.append(symbol)
        return self.signals[symbol]


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candle(*, symbol: str) -> Candle:
    """Create a minimal valid candle for one symbol."""
    return Candle(
        symbol=symbol,
        interval=Interval.M15,
        open_time=_NOW,
        close_time=_NOW,
        open_price=Decimal("100"),
        high_price=Decimal("100"),
        low_price=Decimal("100"),
        close_price=Decimal("100"),
        volume=Decimal("1"),
    )


def _create_signal(
    *,
    symbol: str,
    signal_type: SignalType,
    confidence: str,
) -> Signal:
    """Create one deterministic strategy signal."""
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=Decimal("100"),
        confidence=Decimal(confidence),
        strategy_name="test_strategy",
        generated_at=_NOW,
    )


# =============================================================================
# Service Tests
# =============================================================================
def test_discovery_bounds_analysis_and_ranks_actionable_signals() -> None:
    """Analyze a bounded sorted universe and return confidence-ranked entries."""
    asyncio.run(_run_discovery_test())


async def _run_discovery_test() -> None:
    """Execute bounded discovery with HOLD and unsupported close signals."""
    market_service = FakeMarketService(
        symbols=(
            "ethusdt",
            "BTCUSDT",
            "",
            "ADAUSDT",
            "BTCUSDT",
            "XRPUSDT",
        ),
    )
    strategy_service = FakeStrategyService(
        signals={
            "ADAUSDT": _create_signal(
                symbol="ADAUSDT",
                signal_type=SignalType.BUY,
                confidence="0.8",
            ),
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.HOLD,
                confidence="1",
            ),
            "ETHUSDT": _create_signal(
                symbol="ETHUSDT",
                signal_type=SignalType.SELL,
                confidence="0.8",
            ),
            "XRPUSDT": _create_signal(
                symbol="XRPUSDT",
                signal_type=SignalType.CLOSE_LONG,
                confidence="1",
            ),
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
    )

    opportunities = await service.discover(
        quote_asset=" usdt ",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=4,
        top_n=2,
    )

    assert market_service.requested_symbols == [
        "ADAUSDT",
        "BTCUSDT",
        "ETHUSDT",
        "XRPUSDT",
    ]
    assert strategy_service.saved_symbols == [
        "ADAUSDT",
        "BTCUSDT",
        "ETHUSDT",
        "XRPUSDT",
    ]
    assert market_service.persist_values == [False, False, False, False]
    assert market_service.maximum_active_candle_requests == 1
    assert [signal.symbol for signal in opportunities] == ["ADAUSDT", "ETHUSDT"]


def test_discovery_rejects_invalid_bounds_before_market_access() -> None:
    """Reject invalid scanning bounds without performing market I/O."""
    asyncio.run(_run_invalid_bounds_test())


async def _run_invalid_bounds_test() -> None:
    """Attempt discovery with an invalid maximum symbol count."""
    market_service = FakeMarketService(symbols=("BTCUSDT",))
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
    )

    try:
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=100,
            max_symbols=0,
            top_n=1,
        )
    except ValueError as error:
        assert str(error) == "Maximum symbols must be greater than zero"
    else:
        raise AssertionError("Expected invalid discovery bounds to be rejected")

    assert market_service.requested_symbols == []


def test_discovery_returns_no_opportunities_for_an_empty_universe() -> None:
    """Return an empty result without generating signals for no symbols."""
    asyncio.run(_run_empty_universe_test())


async def _run_empty_universe_test() -> None:
    """Discover from an exchange response with no active symbols."""
    market_service = FakeMarketService(symbols=())
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
    )

    opportunities = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=1,
        top_n=1,
    )

    assert opportunities == ()
    assert market_service.requested_symbols == []
    assert strategy_service.saved_symbols == []


def test_discovery_filters_all_hold_signals_after_persisting_them() -> None:
    """Keep the existing signal audit trail while excluding HOLD candidates."""
    asyncio.run(_run_all_hold_signals_test())


async def _run_all_hold_signals_test() -> None:
    """Analyze one symbol whose strategy returns HOLD."""
    market_service = FakeMarketService(symbols=("BTCUSDT",))
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.HOLD,
                confidence="1",
            ),
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
    )

    opportunities = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=1,
        top_n=1,
    )

    assert opportunities == ()
    assert strategy_service.saved_symbols == ["BTCUSDT"]


def test_discovery_fails_closed_on_one_symbol_analysis_failure() -> None:
    """Propagate a symbol failure and stop before later symbols are analyzed."""
    asyncio.run(_run_symbol_failure_test())


async def _run_symbol_failure_test() -> None:
    """Fail while scanning the middle symbol of a sorted universe."""
    market_service = FakeMarketService(
        symbols=("ETHUSDT", "BTCUSDT", "ADAUSDT"),
        failing_symbol="BTCUSDT",
    )
    strategy_service = FakeStrategyService(
        signals={
            "ADAUSDT": _create_signal(
                symbol="ADAUSDT",
                signal_type=SignalType.BUY,
                confidence="1",
            ),
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
    )

    with pytest.raises(RuntimeError, match="BTCUSDT"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=100,
            max_symbols=3,
            top_n=3,
        )

    assert market_service.requested_symbols == ["ADAUSDT", "BTCUSDT"]
    assert strategy_service.saved_symbols == ["ADAUSDT"]


def test_discovery_propagates_cancellation_without_background_work() -> None:
    """Cancel a blocked market request without leaving discovery work active."""
    asyncio.run(_run_cancellation_test())


async def _run_cancellation_test() -> None:
    """Cancel discovery while its only candle retrieval is blocked."""
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        block_candles=True,
    )
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
    )
    task = asyncio.create_task(
        service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=100,
            max_symbols=1,
            top_n=1,
        ),
    )
    await market_service.candle_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert market_service.active_candle_requests == 0
    assert strategy_service.saved_symbols == []
