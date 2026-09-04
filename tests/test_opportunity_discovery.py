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
    expected_interval: Interval = Interval.M15
    requested_symbols: list[str] = field(default_factory=list[str])
    requested_limits: list[int] = field(default_factory=list[int])
    persist_values: list[bool] = field(default_factory=list[bool])
    candle_started: asyncio.Event = field(default_factory=asyncio.Event)
    active_candle_requests: int = 0
    maximum_active_candle_requests: int = 0
    trading_symbol_requests: int = 0

    async def get_trading_symbols(self, *, quote_asset: str) -> tuple[str, ...]:
        """Return the configured exchange universe."""
        assert quote_asset == "USDT"
        self.trading_symbol_requests += 1
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
        assert interval is self.expected_interval
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
    """Generate configured signals and record generation/persistence calls."""

    signals: dict[str, Signal]
    generated_symbols: list[str] = field(default_factory=list[str])
    saved_symbols: list[str] = field(default_factory=list[str])
    saved_candles: list[tuple[Candle, ...]] = field(
        default_factory=list[tuple[Candle, ...]]
    )
    strategy_types: list[StrategyType | None] = field(
        default_factory=list[StrategyType | None]
    )
    minimum_candles_by_strategy: dict[StrategyType, int] = field(
        default_factory=dict[StrategyType, int]
    )

    def get_minimum_candles(
        self,
        *,
        strategy_type: StrategyType | None = None,
    ) -> int:
        """Return the mocked candle requirement."""
        if (
            strategy_type is not None
            and strategy_type in self.minimum_candles_by_strategy
        ):
            return self.minimum_candles_by_strategy[strategy_type]
        return 1

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Generate and record one configured signal without persistence."""
        symbol = candles[0].symbol
        self.generated_symbols.append(symbol)
        self.saved_candles.append(tuple(candles))
        self.strategy_types.append(strategy_type)
        return self.signals[symbol]

    async def save_signal(
        self,
        *,
        signal: Signal,
    ) -> None:
        """Record one explicit persistence call."""
        self.saved_symbols.append(signal.symbol)

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Generate and persist one configured signal."""
        signal = self.generate_signal(
            candles=candles,
            strategy_type=strategy_type,
        )
        await self.save_signal(
            signal=signal,
        )
        return signal


@dataclass(slots=True)
class EmaCrossStrategyService:
    """Generate real EMA-cross signals while recording strategy input."""

    strategy: EMACrossStrategy = field(default_factory=EMACrossStrategy)
    saved_candles: tuple[Candle, ...] = ()
    saved_signals: list[Signal] = field(default_factory=list[Signal])

    def generate_signal(
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

    async def save_signal(
        self,
        *,
        signal: Signal,
    ) -> None:
        """Record one signal persistence call."""
        self.saved_signals.append(signal)

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Generate and persist one EMA-cross signal."""
        signal = self.generate_signal(
            candles=candles,
            strategy_type=strategy_type,
        )
        await self.save_signal(
            signal=signal,
        )
        return signal


# =============================================================================
# Test Helpers
# =============================================================================
def _create_candle(
    *,
    symbol: str,
    interval: Interval = Interval.M15,
    open_time: datetime = _NOW,
    close_time: datetime = _NOW,
    open_price: Decimal | None = None,
    high_price: Decimal | None = None,
    low_price: Decimal | None = None,
    close_price: Decimal = Decimal("100"),
) -> Candle:
    """Create a minimal candle for one symbol with optional OHLC overrides."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        close_time=close_time,
        open_price=close_price if open_price is None else open_price,
        high_price=close_price if high_price is None else high_price,
        low_price=close_price if low_price is None else low_price,
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
    price: Decimal = Decimal("100"),
) -> Signal:
    """Create one deterministic strategy signal."""
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=price,
        confidence=Decimal(confidence),
        strategy_name=strategy_name,
        generated_at=generated_at,
    )


# =============================================================================
# Service Tests
# =============================================================================
def test_explicit_batch_preserves_input_order_without_universe_lookup() -> None:
    """Analyze each normalized explicit symbol once in first-occurrence order."""
    asyncio.run(_run_explicit_batch_order_test())


async def _run_explicit_batch_order_test() -> None:
    symbols = ("ETHUSDT", "BTCUSDT", "SOLUSDT")
    candles_by_symbol: dict[str, tuple[Candle, ...]] = {
        symbol: (
            _create_candle(
                symbol=symbol,
                open_time=_NOW - timedelta(minutes=15),
                close_time=_NOW,
            ),
        )
        for symbol in symbols
    }
    signals = {
        "ETHUSDT": _create_signal(
            symbol="ETHUSDT",
            signal_type=SignalType.BUY,
            confidence="0.7",
            strategy_name=StrategyType.EMA_CROSS.value,
        ),
        "BTCUSDT": _create_signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            confidence="0.9",
            strategy_name=StrategyType.EMA_CROSS.value,
        ),
        "SOLUSDT": _create_signal(
            symbol="SOLUSDT",
            signal_type=SignalType.HOLD,
            confidence="1",
            strategy_name=StrategyType.EMA_CROSS.value,
        ),
    }
    market_service = FakeMarketService(
        symbols=("IGNOREDUSDT",),
        candles_by_symbol=candles_by_symbol,
    )
    strategy_service = FakeStrategyService(signals=signals)
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    opportunities = await service.discover_symbols(
        symbols=(" ethusdt ", "BTCUSDT", "ETHUSDT", "solusdt"),
        interval=Interval.M15,
        candle_limit=1,
        top_n=2,
        strategy_type=StrategyType.EMA_CROSS,
    )

    assert market_service.trading_symbol_requests == 0
    assert market_service.requested_symbols == list(symbols)
    assert market_service.maximum_active_candle_requests == 1
    assert strategy_service.generated_symbols == list(symbols)
    assert strategy_service.saved_symbols == list(symbols)
    assert tuple(signal.symbol for signal in opportunities) == (
        "BTCUSDT",
        "ETHUSDT",
    )


@pytest.mark.parametrize(
    "symbols",
    (
        (),
        ("   ",),
        ("BTC/USDT",),
    ),
)
def test_explicit_batch_rejects_empty_or_invalid_symbols(
    symbols: tuple[str, ...],
) -> None:
    """Reject unusable explicit batches before any discovery market access."""
    market_service = FakeMarketService(symbols=("IGNOREDUSDT",))
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=FakeStrategyService(signals={}),
        utc_now=lambda: _NOW,
    )

    with pytest.raises(ValueError):
        asyncio.run(
            service.discover_symbols(
                symbols=symbols,
                interval=Interval.M15,
                candle_limit=1,
                top_n=1,
                strategy_type=StrategyType.EMA_CROSS,
            )
        )

    assert market_service.trading_symbol_requests == 0
    assert market_service.requested_symbols == []


def test_explicit_batches_use_the_same_latest_closed_candle_before_next_close() -> None:
    """Use 14:10 for separate batches at 14:10:25 while 14:10 remains open."""
    asyncio.run(_run_cross_batch_closed_candle_test())


async def _run_cross_batch_closed_candle_test() -> None:
    decision_time = datetime(2026, 8, 17, 14, 10, 25, tzinfo=UTC)
    latest_closed_time = datetime(2026, 8, 17, 14, 10, tzinfo=UTC)
    current_close_time = datetime(2026, 8, 17, 14, 11, tzinfo=UTC)
    symbols = ("BTCUSDT", "ETHUSDT")
    market_service = FakeMarketService(
        symbols=("IGNOREDUSDT",),
        expected_interval=Interval.M1,
        candles_by_symbol={
            symbol: (
                _create_candle(
                    symbol=symbol,
                    interval=Interval.M1,
                    open_time=latest_closed_time - timedelta(minutes=1),
                    close_time=latest_closed_time,
                ),
                _create_candle(
                    symbol=symbol,
                    interval=Interval.M1,
                    open_time=latest_closed_time,
                    close_time=current_close_time,
                ),
            )
            for symbol in symbols
        },
    )
    strategy_service = FakeStrategyService(
        signals={
            symbol: _create_signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence="0.9",
                generated_at=latest_closed_time,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
            for symbol in symbols
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: decision_time,
    )

    for symbol in symbols:
        opportunities = await service.discover_symbols(
            symbols=(symbol,),
            interval=Interval.M1,
            candle_limit=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )
        assert opportunities[0].generated_at == latest_closed_time

    assert market_service.trading_symbol_requests == 0
    assert tuple(
        candles[-1].close_time for candles in strategy_service.saved_candles
    ) == (
        latest_closed_time,
        latest_closed_time,
    )


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
    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == ["BTCUSDT"]
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


@pytest.mark.parametrize(
    ("candle", "error_match"),
    (
        pytest.param(
            _create_candle(
                symbol="BTCUSDT",
                open_time=_NOW - timedelta(minutes=15),
                close_time=_NOW,
                high_price=Decimal("Infinity"),
            ),
            "OHLC prices must be finite",
            id="non-finite",
        ),
        pytest.param(
            _create_candle(
                symbol="BTCUSDT",
                open_time=_NOW - timedelta(minutes=15),
                close_time=_NOW,
                low_price=Decimal("0"),
            ),
            "OHLC prices must be greater than zero",
            id="non-positive",
        ),
        pytest.param(
            _create_candle(
                symbol="BTCUSDT",
                open_time=_NOW - timedelta(minutes=15),
                close_time=_NOW,
                high_price=Decimal("100"),
                low_price=Decimal("101"),
            ),
            "low_price must not exceed high_price",
            id="low-above-high",
        ),
        pytest.param(
            _create_candle(
                symbol="BTCUSDT",
                open_time=_NOW - timedelta(minutes=15),
                close_time=_NOW,
                open_price=Decimal("120"),
                high_price=Decimal("110"),
                low_price=Decimal("90"),
                close_price=Decimal("100"),
            ),
            "open_price must be within low/high range",
            id="open-outside-range",
        ),
        pytest.param(
            _create_candle(
                symbol="BTCUSDT",
                open_time=_NOW - timedelta(minutes=15),
                close_time=_NOW,
                open_price=Decimal("100"),
                high_price=Decimal("110"),
                low_price=Decimal("90"),
                close_price=Decimal("120"),
            ),
            "close_price must be within low/high range",
            id="close-outside-range",
        ),
    ),
)
def test_explicit_provenance_rejects_invalid_closed_candle_prices(
    candle: Candle,
    error_match: str,
) -> None:
    """Reject malformed OHLC provenance before strategy generation or save."""
    asyncio.run(
        _run_invalid_closed_candle_price_test(
            candle=candle,
            error_match=error_match,
        )
    )


async def _run_invalid_closed_candle_price_test(
    *,
    candle: Candle,
    error_match: str,
) -> None:
    """Require explicit discovery candles to have a valid OHLC price shape."""
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (candle,)},
    )
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match=error_match):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.generated_symbols == []
    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_invalid_closed_candle_window() -> None:
    """Reject a closed candle whose open time is not before its close time."""
    asyncio.run(_run_invalid_closed_candle_window_test())


async def _run_invalid_closed_candle_window_test() -> None:
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                _create_candle(
                    symbol="BTCUSDT",
                    open_time=_NOW,
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

    with pytest.raises(RuntimeError, match="open_time must be before close_time"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_non_increasing_candle_open_time() -> None:
    """Reject duplicate or reversed open-time identities before strategy use."""
    asyncio.run(_run_non_increasing_candle_open_time_test())


async def _run_non_increasing_candle_open_time_test() -> None:
    duplicate_open = _NOW - timedelta(minutes=30)
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                _create_candle(
                    symbol="BTCUSDT",
                    open_time=duplicate_open,
                    close_time=_NOW - timedelta(minutes=15),
                ),
                _create_candle(
                    symbol="BTCUSDT",
                    open_time=duplicate_open,
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

    with pytest.raises(RuntimeError, match="open_time sequence"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_non_increasing_candle_close_time() -> None:
    """Reject duplicate or reversed close-time identities before strategy use."""
    asyncio.run(_run_non_increasing_candle_close_time_test())


async def _run_non_increasing_candle_close_time_test() -> None:
    duplicate_close = _NOW - timedelta(minutes=15)
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                _create_candle(
                    symbol="BTCUSDT",
                    open_time=_NOW - timedelta(minutes=30),
                    close_time=duplicate_close,
                ),
                _create_candle(
                    symbol="BTCUSDT",
                    open_time=_NOW - timedelta(minutes=20),
                    close_time=duplicate_close,
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

    with pytest.raises(RuntimeError, match="close_time sequence"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_overlapping_closed_candles() -> None:
    """Reject overlapping candle windows before strategy generation."""
    asyncio.run(_run_overlapping_closed_candles_test())


async def _run_overlapping_closed_candles_test() -> None:
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                _create_candle(
                    symbol="BTCUSDT",
                    open_time=_NOW - timedelta(minutes=30),
                    close_time=_NOW - timedelta(minutes=10),
                ),
                _create_candle(
                    symbol="BTCUSDT",
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

    with pytest.raises(RuntimeError, match="windows must not overlap"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.generated_symbols == []
    assert strategy_service.saved_symbols == []


def test_explicit_provenance_accepts_touching_closed_candle_boundaries() -> None:
    """Allow consecutive candle windows to meet at one exact boundary."""
    asyncio.run(_run_touching_closed_candle_boundaries_test())


async def _run_touching_closed_candle_boundaries_test() -> None:
    previous_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=30),
        close_time=_NOW - timedelta(minutes=15),
    )
    latest_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=previous_candle.close_time,
        close_time=_NOW,
    )
    signal = _create_signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence="1",
        generated_at=latest_candle.close_time,
        strategy_name=StrategyType.EMA_CROSS.value,
        price=latest_candle.close_price,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={
            "BTCUSDT": (
                previous_candle,
                latest_candle,
            )
        },
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
        candle_limit=2,
        max_symbols=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )

    assert opportunities == (signal,)
    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == ["BTCUSDT"]
    assert strategy_service.saved_candles == [
        (
            previous_candle,
            latest_candle,
        )
    ]


def test_explicit_provenance_rejects_stale_latest_closed_candle() -> None:
    """Reject a latest candle once the next interval close is due."""
    asyncio.run(_run_stale_latest_closed_candle_test())


async def _run_stale_latest_closed_candle_test() -> None:
    stale_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=30),
        close_time=_NOW - timedelta(minutes=15),
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (stale_candle,)},
    )
    strategy_service = FakeStrategyService(signals={})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="stale for discovery interval"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.generated_symbols == []
    assert strategy_service.saved_symbols == []


def test_explicit_provenance_accepts_latest_candle_before_freshness_boundary() -> None:
    """Accept the latest candle immediately before the next close is due."""
    asyncio.run(_run_latest_candle_before_freshness_boundary_test())


async def _run_latest_candle_before_freshness_boundary_test() -> None:
    latest_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=30),
        close_time=_NOW - timedelta(minutes=15),
    )
    decision_time = _NOW - timedelta(microseconds=1)
    signal = _create_signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence="1",
        generated_at=latest_candle.close_time,
        strategy_name=StrategyType.EMA_CROSS.value,
        price=latest_candle.close_price,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (latest_candle,)},
    )
    strategy_service = FakeStrategyService(signals={"BTCUSDT": signal})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: decision_time,
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
    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == ["BTCUSDT"]


def test_explicit_provenance_uses_calendar_month_freshness() -> None:
    """Preserve month-end freshness instead of using the 30-day approximation."""
    asyncio.run(_run_calendar_month_freshness_test())


async def _run_calendar_month_freshness_test() -> None:
    latest_close_time = datetime(
        2026,
        2,
        28,
        23,
        59,
        59,
        999000,
        tzinfo=UTC,
    )
    decision_time = latest_close_time + timedelta(days=30)
    latest_candle = _create_candle(
        symbol="BTCUSDT",
        interval=Interval.MN1,
        open_time=datetime(
            2026,
            1,
            31,
            23,
            59,
            59,
            999000,
            tzinfo=UTC,
        ),
        close_time=latest_close_time,
    )
    signal = _create_signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence="1",
        generated_at=latest_close_time,
        strategy_name=StrategyType.EMA_CROSS.value,
        price=latest_candle.close_price,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (latest_candle,)},
        expected_interval=Interval.MN1,
    )
    strategy_service = FakeStrategyService(signals={"BTCUSDT": signal})
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: decision_time,
    )

    opportunities = await service.discover(
        quote_asset="USDT",
        interval=Interval.MN1,
        candle_limit=1,
        max_symbols=1,
        top_n=1,
        strategy_type=StrategyType.EMA_CROSS,
    )

    assert opportunities == (signal,)
    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == ["BTCUSDT"]


def test_interval_monthly_next_close_preserves_end_of_month_across_leap_year() -> None:
    """Keep monthly freshness calendar-aware for successive month ends."""
    january_close = datetime(2024, 1, 31, 23, 59, 59, tzinfo=UTC)
    february_close = Interval.MN1.next_close_time(close_time=january_close)
    march_close = Interval.MN1.next_close_time(close_time=february_close)

    assert february_close == datetime(2024, 2, 29, 23, 59, 59, tzinfo=UTC)
    assert march_close == datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC)


def test_legacy_discovery_preserves_stale_candle_behavior() -> None:
    """Keep non-explicit discovery backward compatible with stale source data."""
    asyncio.run(_run_legacy_stale_candle_test())


async def _run_legacy_stale_candle_test() -> None:
    stale_candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=30),
        close_time=_NOW - timedelta(minutes=15),
    )
    signal = _create_signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence="1",
        generated_at=stale_candle.close_time,
        price=stale_candle.close_price,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": (stale_candle,)},
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
    )

    assert opportunities == (signal,)
    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == ["BTCUSDT"]


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

    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == []


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

    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == []


def test_explicit_provenance_rejects_wrong_signal_price() -> None:
    """Reject a signal whose price does not match the latest closed candle."""
    asyncio.run(_run_wrong_signal_price_test())


async def _run_wrong_signal_price_test() -> None:
    candle = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
        close_price=Decimal("100"),
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
                generated_at=candle.close_time,
                strategy_name=StrategyType.EMA_CROSS.value,
                price=Decimal("101"),
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match="Strategy signal price"):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == []


@pytest.mark.parametrize(
    ("confidence", "error_match"),
    (
        pytest.param(
            "NaN",
            "confidence must be finite",
            id="nan",
        ),
        pytest.param(
            "Infinity",
            "confidence must be finite",
            id="infinity",
        ),
        pytest.param(
            "-0.01",
            "confidence must be between zero and one",
            id="negative",
        ),
        pytest.param(
            "1.01",
            "confidence must be between zero and one",
            id="above-one",
        ),
    ),
)
def test_explicit_provenance_rejects_invalid_signal_confidence(
    confidence: str,
    error_match: str,
) -> None:
    """Reject non-finite or out-of-range confidence before signal persistence."""
    asyncio.run(
        _run_invalid_signal_confidence_test(
            confidence=confidence,
            error_match=error_match,
        )
    )


async def _run_invalid_signal_confidence_test(
    *,
    confidence: str,
    error_match: str,
) -> None:
    """Require explicit-strategy confidence to stay within normalized bounds."""
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
                confidence=confidence,
                generated_at=candle.close_time,
                strategy_name=StrategyType.EMA_CROSS.value,
                price=candle.close_price,
            )
        }
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(RuntimeError, match=error_match):
        await service.discover(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=1,
            max_symbols=1,
            top_n=1,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == []


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

    assert strategy_service.generated_symbols == ["BTCUSDT"]
    assert strategy_service.saved_symbols == []


def test_explicit_discovery_expands_candle_limit_to_strategy_minimum() -> None:
    """Verify discovery fetches enough candles when strategy requires more."""
    asyncio.run(_run_discovery_expands_candle_limit_test())


async def _run_discovery_expands_candle_limit_test() -> None:
    # 25 candles
    candles = tuple(
        _create_candle(
            symbol="BTCUSDT",
            open_time=_NOW - timedelta(minutes=15 * (25 - i)),
            close_time=_NOW - timedelta(minutes=15 * (24 - i)),
        )
        for i in range(25)
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT",),
        candles_by_symbol={"BTCUSDT": candles},
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="0.85",
                generated_at=_NOW,
                strategy_name=StrategyType.HIGH_CONFLUENCE_EXHAUSTION.value,
            )
        },
        minimum_candles_by_strategy={
            StrategyType.HIGH_CONFLUENCE_EXHAUSTION: 20,
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    # Caller requests candle_limit=5, but strategy needs 20
    opportunities = await service.discover_symbols(
        symbols=("BTCUSDT",),
        interval=Interval.M15,
        candle_limit=5,
        top_n=1,
        strategy_type=StrategyType.HIGH_CONFLUENCE_EXHAUSTION,
    )

    assert len(opportunities) == 1
    # Market service was asked for effective_candle_limit + 1 = 20 + 1 = 21
    assert market_service.requested_limits == [21]
    # Strategy was provided with 20 candles, not 5
    assert len(strategy_service.saved_candles[0]) == 20


def test_discovery_skips_symbols_with_insufficient_candles_for_strategy() -> None:
    """Ensure candidate symbols lacking the strategy's minimum candles are skipped."""
    asyncio.run(_run_skip_insufficient_candles_test())


async def _run_skip_insufficient_candles_test() -> None:
    short_candles = tuple(
        _create_candle(
            symbol="NEWCOIN",
            open_time=_NOW - timedelta(minutes=15 * (10 - index)),
            close_time=_NOW - timedelta(minutes=15 * (9 - index)),
        )
        for index in range(10)
    )
    sufficient_candles = tuple(
        _create_candle(
            symbol="BTCUSDT",
            open_time=_NOW - timedelta(minutes=15 * (25 - index)),
            close_time=_NOW - timedelta(minutes=15 * (24 - index)),
        )
        for index in range(25)
    )
    market_service = FakeMarketService(
        symbols=("NEWCOIN", "BTCUSDT"),
        candles_by_symbol={
            "NEWCOIN": short_candles,
            "BTCUSDT": sufficient_candles,
        },
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="0.9",
                generated_at=_NOW,
                strategy_name=StrategyType.HIGH_CONFLUENCE_EXHAUSTION.value,
            )
        },
        minimum_candles_by_strategy={
            StrategyType.HIGH_CONFLUENCE_EXHAUSTION: 20,
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    opportunities = await service.discover_symbols(
        symbols=("NEWCOIN", "BTCUSDT"),
        interval=Interval.M15,
        candle_limit=5,
        top_n=2,
        strategy_type=StrategyType.HIGH_CONFLUENCE_EXHAUSTION,
    )

    # NEWCOIN had only 10 candles (< 20 required), so it was skipped
    assert len(opportunities) == 1
    assert opportunities[0].symbol == "BTCUSDT"
    assert "NEWCOIN" not in strategy_service.generated_symbols
    assert "BTCUSDT" in strategy_service.generated_symbols


def test_discovery_skips_symbols_raising_value_error_in_strategy() -> None:
    """Ensure candidate symbols raising ValueError during evaluation are skipped."""
    asyncio.run(_run_skip_value_error_test())


async def _run_skip_value_error_test() -> None:
    candle_btc = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    candle_eth = _create_candle(
        symbol="ETHUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("ETHUSDT", "BTCUSDT"),
        candles_by_symbol={
            "ETHUSDT": (candle_eth,),
            "BTCUSDT": (candle_btc,),
        },
    )

    class FailingStrategyService(FakeStrategyService):
        def generate_signal(
            self,
            *,
            candles: Sequence[Candle],
            strategy_type: StrategyType | None = None,
        ) -> Signal:
            if candles[0].symbol == "ETHUSDT":
                raise ValueError("Strategy rejected ETHUSDT candles")
            return super().generate_signal(candles=candles, strategy_type=strategy_type)

    strategy_service = FailingStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="0.9",
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            )
        },
        minimum_candles_by_strategy={
            StrategyType.EMA_CROSS: 1,
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        utc_now=lambda: _NOW,
    )

    opportunities = await service.discover_symbols(
        symbols=("ETHUSDT", "BTCUSDT"),
        interval=Interval.M15,
        candle_limit=1,
        top_n=2,
        strategy_type=StrategyType.EMA_CROSS,
    )

    assert len(opportunities) == 1
    assert opportunities[0].symbol == "BTCUSDT"


def test_discovery_applies_candle_pacing_delay() -> None:
    """Ensure sequential candle fetches apply the configured pacing delay."""
    asyncio.run(_run_candle_pacing_delay_test())


async def _run_candle_pacing_delay_test() -> None:
    from unittest.mock import patch

    candle_btc = _create_candle(
        symbol="BTCUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    candle_eth = _create_candle(
        symbol="ETHUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    candle_sol = _create_candle(
        symbol="SOLUSDT",
        open_time=_NOW - timedelta(minutes=15),
        close_time=_NOW,
    )
    market_service = FakeMarketService(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        candles_by_symbol={
            "BTCUSDT": (candle_btc,),
            "ETHUSDT": (candle_eth,),
            "SOLUSDT": (candle_sol,),
        },
    )
    strategy_service = FakeStrategyService(
        signals={
            "BTCUSDT": _create_signal(
                symbol="BTCUSDT",
                signal_type=SignalType.BUY,
                confidence="0.9",
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            ),
            "ETHUSDT": _create_signal(
                symbol="ETHUSDT",
                signal_type=SignalType.BUY,
                confidence="0.8",
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            ),
            "SOLUSDT": _create_signal(
                symbol="SOLUSDT",
                signal_type=SignalType.BUY,
                confidence="0.7",
                generated_at=_NOW,
                strategy_name=StrategyType.EMA_CROSS.value,
            ),
        },
        minimum_candles_by_strategy={
            StrategyType.EMA_CROSS: 1,
        },
    )
    service = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        candle_request_delay_seconds=0.05,
        utc_now=lambda: _NOW,
    )

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        if seconds > 0:
            sleep_calls.append(seconds)

    with patch(
        "botragram.services.opportunity_discovery_service.asyncio.sleep",
        side_effect=fake_sleep,
    ):
        await service.discover_symbols(
            symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            interval=Interval.M15,
            candle_limit=1,
            top_n=3,
            strategy_type=StrategyType.EMA_CROSS,
        )

    assert sleep_calls == [0.05, 0.05]
