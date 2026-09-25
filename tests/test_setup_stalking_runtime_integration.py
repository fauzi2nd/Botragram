"""
Botragram

Description:
    Unit and integration tests for Setup Stalking runtime pipeline wiring
    (StrategyService, OpportunityDiscoveryService, and lifecycle states).

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

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import SignalEngine
from botragram.enums import (
    Interval,
    PositionSide,
    SignalType,
    StalkingStatus,
    StrategyType,
)
from botragram.models import Candle, Signal
from botragram.services.opportunity_discovery_service import (
    OpportunityDiscoveryService,
)
from botragram.services.setup_stalking_service import SetupStalkingService
from botragram.services.strategy_service import StrategyService
from botragram.storage.memory.signal_repository import MemorySignalRepository
from botragram.strategies.base.strategy import BaseStrategy

_START_TIME = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)


def _make_candle(
    *,
    symbol: str = "BTCUSDT",
    index: int = 0,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    interval: Interval = Interval.M5,
) -> Candle:
    open_time = _START_TIME + timedelta(minutes=5 * index)
    close_time = open_time + timedelta(minutes=5)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        close_time=close_time,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=Decimal("100"),
    )


class _FakeStrategy(BaseStrategy):
    """Stub strategy returning a predefined signal."""

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.PINBAR_ENGULFING_EMA_RSI

    @property
    def minimum_candles(self) -> int:
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        sym = candles[-1].symbol
        if sym == self._signal.symbol:
            return self._signal
        return Signal(
            symbol=sym,
            signal_type=SignalType.HOLD,
            price=candles[-1].close_price,
            confidence=Decimal("0"),
            strategy_name=self.strategy_type.value,
            generated_at=candles[-1].close_time,
            reason="No setup",
        )


class _FakeStrategyResolver:
    """Stub resolver mapping strategy types to fake strategy."""

    def __init__(self, strategy: BaseStrategy) -> None:
        self._strategy = strategy

    def resolve(self, *, strategy_type: StrategyType) -> BaseStrategy:
        return self._strategy


class _FakeMarketService:
    """Stub market data provider for discovery testing."""

    def __init__(self, candles_by_symbol: dict[str, Sequence[Candle]]) -> None:
        self._candles = candles_by_symbol

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        return tuple(self._candles.keys())

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        persist: bool = True,
        prefer_stored: bool = False,
        as_of: datetime | None = None,
    ) -> Sequence[Candle]:
        candles = self._candles.get(symbol, ())
        return tuple(candles[-limit:])


def test_strategy_service_registers_stalking_candidate_and_holds_entry() -> None:
    """StrategyService catches anchor pattern, registers stalking, and emits HOLD."""
    candle0 = _make_candle(
        symbol="BTCUSDT",
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    anchor_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=candle0.close_time,
        reason="BEARISH ENGULFING at HTF Upper Band",
        stop_loss=Decimal("112"),
        take_profit=Decimal("80"),
    )

    fake_strategy = _FakeStrategy(anchor_signal)
    signal_engine = SignalEngine(
        strategy_resolver=_FakeStrategyResolver(fake_strategy),  # pyright: ignore[reportArgumentType]
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_service = SetupStalkingService(
        max_candidates=5,
        default_max_bars=7,
        retest_ratio=Decimal("0.50"),
    )
    strategy_service = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_service,
        stalking_enabled=True,
    )

    # Bar 0: First detection of pattern
    sig0 = strategy_service.generate_signal(
        candles=[candle0],
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )

    # Must be HOLD to prevent premature market entry
    assert sig0.signal_type is SignalType.HOLD
    assert "[STALKING_REGISTERED]" in (sig0.reason or "")
    assert sig0.symbol == "BTCUSDT"

    # Candidate must be in SetupStalkingService
    setup = stalking_service.get_setup("BTCUSDT")
    assert setup is not None
    assert setup.status is StalkingStatus.STALKING
    assert setup.side is PositionSide.SHORT
    # 50% body retest: 92 + (8 * 0.5) = 96
    assert setup.target_retest_price == Decimal("96")
    assert setup.invalidation_price == Decimal("110")


def test_strategy_service_evaluates_retest_trigger_into_actionable_signal() -> None:
    """Active stalking setup triggers on retest rejection and emits actionable entry."""
    candle0 = _make_candle(
        symbol="BTCUSDT",
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    anchor_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=candle0.close_time,
        reason="BEARISH ENGULFING",
        stop_loss=Decimal("112"),
        take_profit=Decimal("80"),
    )

    fake_strategy = _FakeStrategy(anchor_signal)
    signal_engine = SignalEngine(
        strategy_resolver=_FakeStrategyResolver(fake_strategy),  # pyright: ignore[reportArgumentType]
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_service = SetupStalkingService()
    strategy_service = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_service,
        stalking_enabled=True,
    )

    # Bar 0: Register stalking setup
    strategy_service.generate_signal(
        candles=[candle0],
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )

    # Bar 1: Retest touches 96 (high 97) and closes at 95 (rejection confirmed)
    candle1 = _make_candle(
        symbol="BTCUSDT",
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("97"),
        low_price=Decimal("92"),
        close_price=Decimal("95"),
    )

    sig1 = strategy_service.generate_signal(
        candles=[candle0, candle1],
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )

    # Must be actionable SELL with STALKING_TRIGGERED reason
    assert sig1.signal_type is SignalType.SELL
    assert sig1.price == Decimal("95")
    assert sig1.confidence == Decimal("0.85")
    assert sig1.strategy_name == StrategyType.PINBAR_ENGULFING_EMA_RSI.value
    assert "[STALKING_TRIGGERED]" in (sig1.reason or "")
    assert sig1.stop_loss == Decimal("112")
    assert sig1.take_profit == Decimal("80")

    # Stalking setup state in service is TRIGGERED
    setup = stalking_service.get_setup("BTCUSDT")
    assert setup is not None
    assert setup.status is StalkingStatus.TRIGGERED


def test_strategy_service_invalidated_when_anchor_breached() -> None:
    """Stalking setup invalidates when price breaches anchor peak, emitting HOLD."""
    candle0 = _make_candle(
        symbol="BTCUSDT",
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    anchor_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=candle0.close_time,
        reason="BEARISH ENGULFING",
    )

    fake_strategy = _FakeStrategy(anchor_signal)
    signal_engine = SignalEngine(
        strategy_resolver=_FakeStrategyResolver(fake_strategy),  # pyright: ignore[reportArgumentType]
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_service = SetupStalkingService()
    strategy_service = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_service,
        stalking_enabled=True,
    )

    # Bar 0: Register stalking setup
    strategy_service.generate_signal(
        candles=[candle0],
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )

    # Bar 1: Breaches anchor high 110 (high 111)
    candle1 = _make_candle(
        symbol="BTCUSDT",
        index=1,
        open_price=Decimal("95"),
        high_price=Decimal("111"),
        low_price=Decimal("94"),
        close_price=Decimal("105"),
    )

    sig1 = strategy_service.generate_signal(
        candles=[candle0, candle1],
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )

    assert sig1.signal_type is SignalType.HOLD
    assert "[STALKING_INVALIDATED]" in (sig1.reason or "")

    setup = stalking_service.get_setup("BTCUSDT")
    assert setup is not None
    assert setup.status is StalkingStatus.INVALIDATED


@pytest.mark.asyncio
async def test_opportunity_discovery_evaluates_active_stalking_symbol() -> None:
    """Discovery scans include active stalking symbols even if not in original batch."""
    candle0 = _make_candle(
        symbol="ETHUSDT",
        index=0,
        open_price=Decimal("200"),
        high_price=Decimal("210"),
        low_price=Decimal("180"),
        close_price=Decimal("185"),
    )
    candle1 = _make_candle(
        symbol="ETHUSDT",
        index=1,
        open_price=Decimal("186"),
        # Body 185..200 (size 15). 50% retest = 192.5. High 193 touches, close 191.
        high_price=Decimal("193"),
        low_price=Decimal("185"),
        close_price=Decimal("191"),
    )
    anchor_signal = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("185"),
        confidence=Decimal("0.90"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=candle0.close_time,
        reason="BEAR_ENGULF",
        stop_loss=Decimal("212"),
        take_profit=Decimal("150"),
    )

    fake_strategy = _FakeStrategy(anchor_signal)
    signal_engine = SignalEngine(
        strategy_resolver=_FakeStrategyResolver(fake_strategy),  # pyright: ignore[reportArgumentType]
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_service = SetupStalkingService()
    strategy_service = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_service,
        stalking_enabled=True,
    )

    # 1. Register ETHUSDT into active stalking
    strategy_service.generate_signal(
        candles=[candle0],
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    assert "ETHUSDT" in stalking_service.get_active_stalking_symbols()

    # 2. Market service contains candle1 for ETHUSDT and candle for SOLUSDT
    sol_candle = _make_candle(
        symbol="SOLUSDT",
        index=1,
        open_price=Decimal("50"),
        high_price=Decimal("51"),
        low_price=Decimal("49"),
        close_price=Decimal("50"),
    )
    market_service = _FakeMarketService(
        {
            "ETHUSDT": [candle0, candle1],
            "SOLUSDT": [sol_candle],
        }
    )

    discovery_service = OpportunityDiscoveryService(
        market_service=market_service,  # pyright: ignore[reportArgumentType]
        strategy_service=strategy_service,
        setup_stalking_service=stalking_service,
        candle_request_delay_seconds=0.0,
        utc_now=lambda: candle1.close_time + timedelta(seconds=1),
    )

    # Discover with symbols = ("SOLUSDT",) - ETHUSDT is NOT in the batch!
    # Because ETHUSDT is in active stalking, discovery will prepend it and evaluate it!
    actionable = await discovery_service.discover_symbols(
        symbols=("SOLUSDT",),
        interval=Interval.M5,
        candle_limit=2,
        top_n=5,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )

    # ETHUSDT triggered and should be returned as actionable opportunity!
    assert len(actionable) == 1
    assert actionable[0].symbol == "ETHUSDT"
    assert actionable[0].signal_type is SignalType.SELL
    assert "[STALKING_TRIGGERED]" in (actionable[0].reason or "")
