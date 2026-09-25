"""
Botragram

Description:
    Unit tests for SetupStalkingService and StalkingSetup domain invariants,
    including candidate registration, 50% retest triggers, anchor invalidation,
    expiry windows, and concurrent candidate capacity bounds.

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
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    Interval,
    PositionSide,
    SignalType,
    StalkingStatus,
)
from botragram.models import Candle, Signal
from botragram.models.stalking import StalkingSetup
from botragram.services.setup_stalking_service import SetupStalkingService

_START_TIME = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)


def _make_candle(
    *,
    symbol: str = "BTCUSDT",
    interval: Interval = Interval.M5,
    index: int = 0,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
) -> Candle:
    """Helper to generate a timestamped Candle."""
    open_time = _START_TIME + timedelta(minutes=5 * index)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=5),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=Decimal("100.0"),
    )


def test_stalking_setup_invariants() -> None:
    """Validate StalkingSetup dataclass invariant checks."""
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="Stalking symbol must not be empty"):
        StalkingSetup(
            symbol="  ",
            side=PositionSide.SHORT,
            pattern_name="ENGULFING",
            anchor_price=Decimal("100"),
            invalidation_price=Decimal("110"),
            target_retest_price=Decimal("105"),
            htf_zone_label="15m Upper Band",
            current_bar=0,
            max_bars=7,
            started_at=now,
            updated_at=now,
            status=StalkingStatus.STALKING,
        )

    with pytest.raises(ValueError, match="Max bars must be positive"):
        StalkingSetup(
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            pattern_name="ENGULFING",
            anchor_price=Decimal("100"),
            invalidation_price=Decimal("110"),
            target_retest_price=Decimal("105"),
            htf_zone_label="15m Upper Band",
            current_bar=0,
            max_bars=0,
            started_at=now,
            updated_at=now,
            status=StalkingStatus.STALKING,
        )


def test_register_bearish_candidate_and_retest_calculation() -> None:
    """Validate registering a SELL setup calculates 50% body retest target."""
    service = SetupStalkingService(max_candidates=5, default_max_bars=7)
    candle = _make_candle(
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING at HTF Extreme",
    )

    setup = service.register_candidate(
        signal=signal,
        setup_candle=candle,
        htf_zone_label="15m Upper Band",
    )
    assert setup is not None
    assert setup.symbol == "BTCUSDT"
    assert setup.side is PositionSide.SHORT
    assert setup.pattern_name == "ENGULFING"
    assert setup.invalidation_price == Decimal("110")  # Peak high
    # Body: 100 -> 92 (size = 8), 50% body retest = 92 + (8 * 0.5) = 96
    assert setup.target_retest_price == Decimal("96")
    assert setup.status is StalkingStatus.STALKING
    assert setup.current_bar == 0
    assert setup.max_bars == 7


def test_bearish_setup_invalidation_breach_peak() -> None:
    """When subsequent bar high breaches anchor high, setup is INVALIDATED (0 loss)."""
    service = SetupStalkingService()
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    service.register_candidate(signal=signal, setup_candle=candle0)

    # Subsequent bar breaches peak: high 111 > invalidation 110
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("111"),
        low_price=Decimal("91"),
        close_price=Decimal("105"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    assert updated.status is StalkingStatus.INVALIDATED
    assert updated.current_bar == 1


def test_bearish_setup_retest_trigger_with_rejection_confirmation() -> None:
    """Subsequent bar touching retest target with rejection close triggers setup."""
    service = SetupStalkingService()
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    service.register_candidate(signal=signal, setup_candle=candle0)

    # Bar 1 touches target 96 (high 97) and closes at 95 <= 96 (rejection confirmed)
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("97"),
        low_price=Decimal("92"),
        close_price=Decimal("95"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    assert updated.status is StalkingStatus.TRIGGERED
    assert updated.current_bar == 1


def test_bearish_setup_retest_without_rejection_does_not_trigger() -> None:
    """Candle closing above target (marubozu / breakout) does NOT trigger setup."""
    service = SetupStalkingService()
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    service.register_candidate(signal=signal, setup_candle=candle0)

    # Bar 1 touches target 96 (high 98) but closes at 98 > 96 (breakout against setup)
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("98"),
        low_price=Decimal("93"),
        close_price=Decimal("98"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    assert updated.status is StalkingStatus.STALKING
    assert updated.current_bar == 1


def test_bullish_setup_retest_and_rejection_confirmation() -> None:
    """Bullish setup calculates 50% body pullback and triggers on bounce."""
    service = SetupStalkingService()
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("92"),
        high_price=Decimal("105"),
        low_price=Decimal("90"),
        close_price=Decimal("100"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BULLISH ENGULFING",
    )
    setup = service.register_candidate(signal=signal, setup_candle=candle0)
    assert setup is not None
    # Body: 92 -> 100 (size = 8), 50% pullback = 100 - (8 * 0.5) = 96
    assert setup.target_retest_price == Decimal("96")
    assert setup.invalidation_price == Decimal("90")

    # Bar 1 pulls back to 95 (touches target 96) and closes at 97 (bounce confirmed)
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("98"),
        high_price=Decimal("99"),
        low_price=Decimal("95"),
        close_price=Decimal("97"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    assert updated.status is StalkingStatus.TRIGGERED
    assert updated.current_bar == 1


def test_setup_expiry_at_max_bars() -> None:
    """When setup reaches max_bars without invalidation or trigger, it EXPIRES."""
    service = SetupStalkingService(default_max_bars=3)
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    service.register_candidate(signal=signal, setup_candle=candle0)

    # Bar 1: Quiet bar below retest target
    c1 = _make_candle(
        index=1,
        open_price=Decimal("92"),
        high_price=Decimal("95"),
        low_price=Decimal("91"),
        close_price=Decimal("93"),
    )
    u1 = service.on_candle_update(c1)
    assert (
        u1 is not None and u1.status is StalkingStatus.STALKING and u1.current_bar == 1
    )

    # Bar 2: Quiet bar below retest target
    c2 = _make_candle(
        index=2,
        open_price=Decimal("93"),
        high_price=Decimal("95"),
        low_price=Decimal("92"),
        close_price=Decimal("94"),
    )
    u2 = service.on_candle_update(c2)
    assert (
        u2 is not None and u2.status is StalkingStatus.STALKING and u2.current_bar == 2
    )

    # Bar 3: Reaches max_bars (3) without retest -> EXPIRED
    c3 = _make_candle(
        index=3,
        open_price=Decimal("94"),
        high_price=Decimal("95"),
        low_price=Decimal("93"),
        close_price=Decimal("94"),
    )
    u3 = service.on_candle_update(c3)
    assert (
        u3 is not None and u3.status is StalkingStatus.EXPIRED and u3.current_bar == 3
    )


def test_capacity_limit_max_candidates() -> None:
    """SetupStalkingService strictly limits concurrent active candidates."""
    service = SetupStalkingService(max_candidates=2)

    candle = _make_candle(
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    for sym in ["BTCUSDT", "ETHUSDT"]:
        sig = Signal(
            symbol=sym,
            signal_type=SignalType.SELL,
            price=Decimal("92"),
            confidence=Decimal("0.85"),
            strategy_name="PIER",
            generated_at=_START_TIME,
            reason="BEARISH ENGULFING",
        )
        assert service.register_candidate(signal=sig, setup_candle=candle) is not None

    # Third candidate must be rejected due to capacity limit 2
    sig3 = Signal(
        symbol="SOLUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    assert service.register_candidate(signal=sig3, setup_candle=candle) is None
    assert len(service.get_active_stalking_setups()) == 2
