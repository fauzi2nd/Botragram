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
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.services import OpportunityDiscoveryService
from botragram.strategies.trend import EMACrossStrategy

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
    candles_by_symbol: dict[str, tuple[Candle, ...]] = field(
        default_factory=dict[str, tuple[Candle, ...]]
    )
    failing_symbol: str | None = None
    block_candles: bool = False
    requested_symbols: list[str] = field(default_factory=list[str])
    requested_limits: list[int] = field(default_factory=list[int])
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
        """Return deterministic candles for one symbol."""
        assert interval is Interval.M15
        self.requested_symbols.append(symbol)
        self.requested_limits.append(limit)
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
            return self.candles_by_symbol.get(
                symbol,
                (_create_candle(symbol=symbol),),
            )
        finally:
            self.active_candle_requests -= 1


@dataclass(slots=True)
class FakeStrategyService:
    """Generate configured signals and record persistence calls."""

    signals: dict[str, Signal]
    saved_symbols: list[str] = field(default_factory=list[str])
    saved_candles: list[tuple[Candle, ...]] = field(
        default_factory=list[tuple[Candle, ...]]
    )
    strategy_types: list[StrategyType | None] = field(
        default_factory=list[StrategyType | None]
    )

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Return and record the signal for the candle symbol."""
        symbol = candles[0].symbol
        self.saved_symbols.append(symbol)
        self.saved_candles.append(tuple(candles))
        self.strategy_types.append(strategy_type)
        return self.signals[symbol]


@dataclass(slots=True)
class EmaCrossStrategyService:
    """Generate real EMA-cross signals while recording strategy input."""

    strategy: EMACrossStrategy = field(default_factory=EMACrossStrategy)
    saved_candles: tuple[Candle, ...] = ()

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Generate one EMA-cross signal without persistence side effects."""
        if strategy_type is not None and strategy_type is not StrategyType.EMA_CROSS:
            raise AssertionError("EMA-cross fake received the wrong strategy context")
        self.saved_candles = tuple(candles)
        return self.strategy.generate_signal(candles=candles)


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candle(
    *,
    symbol: str,
    interval: Interval = Interval.M15,
    open_time: datetime = _NOW,
    close_time: datetime = _NOW,
    close_price: Decimal = Decimal("100"),
) -> Candle:
    """Create a minimal valid candle for one symbol."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        close_time=close_time,
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        volume=Decimal("1"),
    )


def _create_signal(
    *,
    symbol: str,
    signal_type: SignalType,
    confidence: str,
    generated_at: datetime = _NOW,
    strategy_name: str = "test_strategy",
) -> Signal:
    """Create one deterministic strategy signal."""
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=Decimal("100"),
        confidence=Decimal(confidence),
        strategy_name=strategy_name,
        generated_at=generated_at,
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
        utc_now=lambda: _NOW,
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
    assert market_service.requested_limits == [101, 101, 101, 101]
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
        utc_now=lambda: _NOW,
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
        utc_now=lambda: _NOW,
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
        utc_now=lambda: _NOW,
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
        utc_now=lambda: _NOW,
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
        utc_now=lambda: _NOW,
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


def test_discovery_excludes_a_current_open_candle() -> None:
    """Never pass a candle whose close is later than the decision time."""
    asyncio.run(_run_open_candle_exclusion_test())


async def _run_open_candle_exclusion_test() -> None:
    """Filter the currently-open candle before strategy evaluation."""
    closed = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW - timedelta(milliseconds=1),
    )
    open_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW,
        close_time=_NOW + timedelta(minutes=15) - timedelta(milliseconds=1),
        close_price=Decimal("120"),
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (closed, open_candle)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.HOLD,
                confidence="1",
                generated_at=closed.close_time,
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    opportunities = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=1,
        max_symbols=1,
        top_n=1,
    )

    assert opportunities == ()
    assert market_service.requested_limits == [2]
    assert strategy_service.saved_candles == [(closed,)]


def test_discovery_includes_a_candle_closing_exactly_at_as_of() -> None:
    """Treat a candle closing exactly at the decision time as closed."""
    asyncio.run(_run_exact_close_boundary_test())


async def _run_exact_close_boundary_test() -> None:
    """Include the inclusive close-time boundary."""
    boundary_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (boundary_candle,)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.HOLD,
                confidence="1",
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=1,
        max_symbols=1,
        top_n=1,
    )

    assert strategy_service.saved_candles == [(boundary_candle,)]


def test_discovery_requests_one_extra_candle_to_preserve_closed_window() -> None:
    """Request one extra venue candle before removing the current open bar."""
    asyncio.run(_run_extra_candle_window_test())


async def _run_extra_candle_window_test() -> None:
    """Retain the requested count of closed candles when one open bar exists."""
    first = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=30),
        close_time=_NOW - timedelta(minutes=15, milliseconds=1),
    )
    second = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    open_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW,
        close_time=_NOW + timedelta(minutes=15) - timedelta(milliseconds=1),
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (first, second, open_candle)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.HOLD,
                confidence="1",
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=2,
        max_symbols=1,
        top_n=1,
    )

    assert market_service.requested_limits == [3]
    assert strategy_service.saved_candles == [(first, second)]


def test_open_candle_ema_crossover_cannot_create_an_opportunity() -> None:
    """Prove a crossover that exists only on the open bar cannot drive entry."""
    asyncio.run(_run_open_candle_ema_crossover_test())


async def _run_open_candle_ema_crossover_test() -> None:
    """Use the real EMA-cross strategy on a closed flat window plus open spike."""
    symbol = "BTCUSDT"
    start = _NOW - timedelta(minutes=22 * 15)
    closed_candles = tuple(
        _create_candle(
            symbol=symbol,
            open_time=start + timedelta(minutes=index * 15),
            close_time=(
                start + timedelta(minutes=(index + 1) * 15) - timedelta(milliseconds=1)
            ),
        )
        for index in range(22)
    )
    open_candle = _create_candle(
        symbol=symbol,
        open_time=_NOW,
        close_time=_NOW + timedelta(minutes=15) - timedelta(milliseconds=1),
        close_price=Decimal("120"),
    )

    raw_signal = EMACrossStrategy().generate_signal(
        candles=(*closed_candles, open_candle),
    )
    assert raw_signal.signal_type is SignalType.BUY

    market_service = FakeMarketService(
        symbols=(symbol,),
        candles_by_symbol={symbol: (*closed_candles, open_candle)},
    )
    strategy_service = EmaCrossStrategyService()
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    opportunities = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=22,
        max_symbols=1,
        top_n=1,
    )

    assert opportunities == ()
    assert market_service.requested_limits == [23]
    assert strategy_service.saved_candles == closed_candles
    assert (
        strategy_service.strategy.generate_signal(
            candles=strategy_service.saved_candles,
        ).signal_type
        is SignalType.HOLD
    )


def test_discovery_rejects_a_future_dated_generated_signal() -> None:
    """Fail closed if a strategy returns a signal later than discovery as-of."""
    asyncio.run(_run_future_dated_signal_test())


async def _run_future_dated_signal_test() -> None:
    """Reject a future actionable signal even after candle filtering."""
    candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (candle,)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="1",
                generated_at=_NOW + timedelta(microseconds=1),
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(
        RuntimeError,
        match="after the discovery decision time",
    ):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
        )


def test_explicit_strategy_provenance_accepts_exact_closed_candle_context() -> None:
    """Forward explicit strategy context and return only an exact-bound signal."""
    asyncio.run(_run_exact_provenance_test())


async def _run_exact_provenance_test() -> None:
    candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    signal = _create_signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence="1",
        generated_at=candle.close_time,
        strategy_name=StrategyType.EMA_CROSS.value,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (candle,)},
    )
    strategy_service = FakeStrategyService(signals={"BTCUSDT": signal})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    opportunities = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=1,
        max_symbols=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )

    assert opportunities == (signal,)
    assert strategy_service.strategy_types == [StrategyType.EMA_CROSS]


def test_explicit_provenance_rejects_wrong_closed_candle_symbol() -> None:
    """Reject venue candle data that does not belong to the scanned symbol."""
    asyncio.run(_run_wrong_candle_symbol_test())


async def _run_wrong_candle_symbol_test() -> None:
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                _create_candle(
                    symbol="ETHUSDT",
                    open_time=_NOW - timedelta(minutes=15),
                    close_time=_NOW,
                ),
            )
        },
    )
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="Closed-candle symbol"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_wrong_closed_candle_interval() -> None:
    """Reject venue candle data from an interval other than the LIVE context."""
    asyncio.run(_run_wrong_candle_interval_test())


async def _run_wrong_candle_interval_test() -> None:
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                _create_candle(
                    symbol="BTCUSDT",
                    interval=Interval.H1,
                    open_time=_NOW - timedelta(hours=1),
                    close_time=_NOW,
                ),
            )
        },
    )
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="Closed-candle interval"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_wrong_signal_symbol() -> None:
    """Reject a strategy result that changes the scanned symbol identity."""
    asyncio.run(_run_wrong_signal_symbol_test())


async def _run_wrong_signal_symbol_test() -> None:
    candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (candle,)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                confidence="1",
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="Strategy signal symbol"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )


def test_explicit_provenance_rejects_wrong_signal_strategy_name() -> None:
    """Reject a signal that was not produced by the authoritative strategy."""
    asyncio.run(_run_wrong_signal_strategy_test())


async def _run_wrong_signal_strategy_test() -> None:
    candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (candle,)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="1",
                strategy_name=StrategyType.SUPERTREND.value,
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="Strategy signal name"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )


def test_explicit_provenance_rejects_non_latest_signal_timestamp() -> None:
    """Require generated_at to identify the exact latest closed candle."""
    asyncio.run(_run_non_latest_signal_timestamp_test())


async def _run_non_latest_signal_timestamp_test() -> None:
    previous_close = _NOW - timedelta(minutes=15)
    latest = _create_candle(
        symbol="BTCUSDT",
        open_time=previous_close,
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (latest,)},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="1",
                generated_at=previous_close,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="latest closed candle"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )
