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
import logging
from dataclasses import replace
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
    StrategyType,
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
    assert updated.current_bar == 1


def test_bearish_setup_retest_without_wick_rejection_does_not_trigger() -> None:
    """Candle slicing downward from above target without upper wick does not trigger."""
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
    # Target retest is 96.
    # Bar 1 opens at 99 (above target), reaches high 100, closes at 94 with tiny wick
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("99"),
        high_price=Decimal("100"),
        low_price=Decimal("94"),
        close_price=Decimal("94"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    # Must NOT trigger because it opened above target without testing from below
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


def test_duplicate_closed_candle_calls_do_not_advance_bar() -> None:
    """Duplicate calls with the same closed candle must preserve bar and state."""
    service = SetupStalkingService(default_max_bars=7)
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

    # Calling with setup candle (index 0) must be ignored and stay bar 0
    for _ in range(5):
        res0 = service.on_candle_update(candle0)
        assert res0 is not None
        assert res0.current_bar == 0
        assert res0.status is StalkingStatus.STALKING

    # First subsequent bar (index 1) advances bar to 1
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("95"),
        low_price=Decimal("92"),
        close_price=Decimal("94"),
    )
    res1 = service.on_candle_update(candle1)
    assert res1 is not None
    assert res1.current_bar == 1
    assert res1.status is StalkingStatus.STALKING

    # 10 duplicate calls of candle1 must NOT advance bar or change state
    for _ in range(10):
        dup = service.on_candle_update(candle1)
        assert dup is not None
        assert dup.current_bar == 1
        assert dup.status is StalkingStatus.STALKING


def test_retest_trigger_called_multiple_times_only_triggers_once() -> None:
    """Retest trigger on the same closed candle only transitions once."""
    service = SetupStalkingService(default_max_bars=7)
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

    # Candle 1 touches retest target 96 (high 97) with rejection confirmation
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("97"),
        low_price=Decimal("92"),
        close_price=Decimal("95"),
    )
    triggered = service.on_candle_update(candle1)
    assert triggered is not None
    assert triggered.status is StalkingStatus.TRIGGERED
    assert triggered.current_bar == 1

    # Repeated calls on the same candle do not re-trigger (returns None)
    for _ in range(5):
        dup = service.on_candle_update(candle1)
        assert dup is None

    # Stalking setup in service remains TRIGGERED
    final_setup = service.get_setup("BTCUSDT")
    assert final_setup is not None
    assert final_setup.status is StalkingStatus.TRIGGERED
    assert final_setup.current_bar == 1


def test_invalidation_called_multiple_times_only_invalidates_once() -> None:
    """Invalidation on the same closed candle only transitions once."""
    service = SetupStalkingService(default_max_bars=7)
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

    # Candle 1 breaches peak (high 111 > invalidation 110)
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("111"),
        low_price=Decimal("91"),
        close_price=Decimal("105"),
    )
    invalidated = service.on_candle_update(candle1)
    assert invalidated is not None
    assert invalidated.status is StalkingStatus.INVALIDATED
    assert invalidated.current_bar == 1

    # Repeated calls on the same candle do not re-invalidate
    for _ in range(5):
        assert service.on_candle_update(candle1) is None

    final_setup = service.get_setup("BTCUSDT")
    assert final_setup is not None
    assert final_setup.status is StalkingStatus.INVALIDATED
    assert final_setup.current_bar == 1


def test_expiry_requires_distinct_closed_candles() -> None:
    """Expiry occurs strictly after max_bars distinct closed candles."""
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

    # Bar 1 called 5 times
    c1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("95"),
        low_price=Decimal("92"),
        close_price=Decimal("94"),
    )
    for _ in range(5):
        u1 = service.on_candle_update(c1)
        assert u1 is not None
        assert u1.current_bar == 1
        assert u1.status is StalkingStatus.STALKING

    # Bar 2 called 5 times
    c2 = _make_candle(
        index=2,
        open_price=Decimal("93"),
        high_price=Decimal("95"),
        low_price=Decimal("92"),
        close_price=Decimal("94"),
    )
    for _ in range(5):
        u2 = service.on_candle_update(c2)
        assert u2 is not None
        assert u2.current_bar == 2
        assert u2.status is StalkingStatus.STALKING

    # Bar 3 (3rd distinct bar) reaches max_bars (3) -> EXPIRED
    c3 = _make_candle(
        index=3,
        open_price=Decimal("94"),
        high_price=Decimal("95"),
        low_price=Decimal("93"),
        close_price=Decimal("94"),
    )
    u3 = service.on_candle_update(c3)
    assert u3 is not None
    assert u3.status is StalkingStatus.EXPIRED
    assert u3.current_bar == 3

    # Subsequent calls on c3 do not re-expire
    for _ in range(5):
        assert service.on_candle_update(c3) is None


def test_setup_stalking_paused_and_cleanup_when_capacity_full(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When position slots are full, stalking pauses and clears all setups."""
    service = SetupStalkingService(max_candidates=5, default_max_bars=7)
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
    reg = service.register_candidate(signal=signal, setup_candle=candle0)
    assert reg is not None
    assert len(service.get_active_stalking_setups()) == 1
    assert service.get_active_stalking_symbols() == ("BTCUSDT",)
    assert not service.is_paused

    with caplog.at_level(logging.INFO):
        # Pause stalking (simulating position capacity reached)
        service.set_paused(True)
        assert service.is_paused
        # Active setups must be completely cleaned up (clean radar)
        assert service.get_active_stalking_setups() == ()
        assert service.get_active_stalking_symbols() == ()

        # Calling set_paused(True) again must be an idempotent no-op (no log spam)
        for _ in range(10):
            service.set_paused(True)

    pause_logs = [
        r.message for r in caplog.records if "Setup stalking paused" in r.message
    ]
    assert len(pause_logs) == 1

    # Any new registration attempt while paused must be rejected
    signal2 = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("2000"),
        confidence=Decimal("0.80"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BULLISH PINBAR",
    )
    reg2 = service.register_candidate(signal=signal2, setup_candle=candle0)
    assert reg2 is None
    assert service.get_active_stalking_setups() == ()

    # Candle updates while paused must be ignored
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("95"),
        low_price=Decimal("92"),
        close_price=Decimal("94"),
    )
    assert service.on_candle_update(candle1) is None

    caplog.clear()
    with caplog.at_level(logging.INFO):
        # Resume stalking (simulating position slot becoming available)
        service.set_paused(False)
        assert not service.is_paused
        # Repeated resume calls must also be idempotent without duplicate logging
        for _ in range(10):
            service.set_paused(False)

    resume_logs = [
        r.message for r in caplog.records if "Setup stalking resumed" in r.message
    ]
    assert len(resume_logs) == 1

    reg3 = service.register_candidate(signal=signal2, setup_candle=candle0)
    assert reg3 is not None
    assert len(service.get_active_stalking_setups()) == 1
    assert service.get_active_stalking_symbols() == ("ETHUSDT",)


def test_setup_stalking_clear_all(caplog: pytest.LogCaptureFixture) -> None:
    """clear_all explicitly empties all tracked setups and history."""
    service = SetupStalkingService(max_candidates=5)
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
    assert len(service.get_active_stalking_setups()) == 1

    with caplog.at_level(logging.INFO):
        service.clear_all()
        assert service.get_active_stalking_setups() == ()
        assert service.get_active_stalking_symbols() == ()
        assert service.get_setup("BTCUSDT") is None

        # Redundant clear_all when already empty must not spam logs
        for _ in range(5):
            service.clear_all()

    clear_logs = [
        r.message
        for r in caplog.records
        if "Cleared all setup stalking candidates" in r.message
    ]
    assert len(clear_logs) == 1


def test_build_triggered_signal_risk_reward_preservation() -> None:
    """When entry price causes reward to compress, TP is projected for >= 1.5R."""
    service = SetupStalkingService()

    # Anchor at 100, SL at 90 (risk=10), TP at 120 (reward=20, planned 2R)
    setup = StalkingSetup(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        pattern_name="PINBAR",
        anchor_price=Decimal("100"),
        invalidation_price=Decimal("89"),
        target_retest_price=Decimal("95"),
        htf_zone_label="15m Lower Band",
        current_bar=1,
        max_bars=7,
        started_at=_START_TIME,
        updated_at=_START_TIME,
        status=StalkingStatus.TRIGGERED,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
        confidence=Decimal("0.85"),
    )

    # Trigger candle closes at 115 (close to old TP 120, actual reward 5 vs 25 risk)
    trigger_candle = _make_candle(
        index=1,
        open_price=Decimal("95"),
        high_price=Decimal("116"),
        low_price=Decimal("94"),
        close_price=Decimal("115"),
    )

    sig = service.build_triggered_signal(setup=setup, trigger_candle=trigger_candle)
    assert sig.price == Decimal("115")
    assert sig.stop_loss == Decimal("90")
    # Actual risk = 115 - 90 = 25. With 2R projected: TP = 115 + (25 * 2.0) = 165
    assert sig.take_profit is not None
    assert sig.take_profit == Decimal("165")
    # Verify reward >= 1.5R
    reward = sig.take_profit - sig.price
    risk = sig.price - (sig.stop_loss or Decimal("0"))
    assert reward >= risk * Decimal("1.5")


def test_stalking_funnel_tracking_end_to_end() -> None:
    """Telemetry funnel tracks stages from scan to trigger and expiration."""
    service = SetupStalkingService(max_candidates=2, default_max_bars=3)

    # 1. Simulate Scans & Rejections before register
    service.record_scan(count=10)
    service.record_rejection(reason="HTF extreme", count=5)
    service.record_rejection(reason="Trend distance", count=3)
    service.record_rejection(reason="Key level", count=2)

    # 2. Register Candidate 1 (which will be TRIGGERED)
    service.record_scan(count=1)
    service.record_zone_candidate(count=1)
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("95"),
        close_price=Decimal("96"),  # Bearish rejection
    )
    sig1 = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("96"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH_REJECTION",
    )
    reg1 = service.register_candidate(signal=sig1, setup_candle=candle0)
    assert reg1 is not None

    # Bar 1 for BTCUSDT: Retest touched & triggered!
    c_trigger = _make_candle(
        index=1,
        open_price=Decimal("96"),
        high_price=Decimal("104"),
        low_price=Decimal("95"),
        close_price=Decimal("97"),
    )
    up1 = service.on_candle_update(c_trigger)
    assert up1 is not None
    assert up1.status is StalkingStatus.TRIGGERED

    # 3. Register Candidate 2 (which will be INVALIDATED)
    service.record_scan(count=1)
    service.record_zone_candidate(count=1)
    sig2 = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("96"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH_REJECTION",
    )
    reg2 = service.register_candidate(
        signal=sig2, setup_candle=replace(candle0, symbol="ETHUSDT")
    )
    assert reg2 is not None

    # Bar 1 for ETHUSDT: Breaches invalidation high (110.0)
    c_inval = _make_candle(
        index=1,
        open_price=Decimal("96"),
        high_price=Decimal("115"),
        low_price=Decimal("96"),
        close_price=Decimal("112"),
    )
    up2 = service.on_candle_update(replace(c_inval, symbol="ETHUSDT"))
    assert up2 is not None
    assert up2.status is StalkingStatus.INVALIDATED

    # 4. Register Candidate 3 (which will EXPIRE)
    service.record_scan(count=1)
    service.record_zone_candidate(count=1)
    sig3 = Signal(
        symbol="SOLUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("96"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH_REJECTION",
    )
    reg3 = service.register_candidate(
        signal=sig3, setup_candle=replace(candle0, symbol="SOLUSDT"), max_bars=2
    )
    assert reg3 is not None

    # Bar 1 for SOLUSDT: neutral candle
    c_neut1 = _make_candle(
        index=1,
        open_price=Decimal("96"),
        high_price=Decimal("97"),
        low_price=Decimal("95"),
        close_price=Decimal("96"),
    )
    service.on_candle_update(replace(c_neut1, symbol="SOLUSDT"))

    # Bar 2 for SOLUSDT: neutral candle, hits max_bars=2 -> EXPIRED
    c_neut2 = _make_candle(
        index=2,
        open_price=Decimal("96"),
        high_price=Decimal("97"),
        low_price=Decimal("95"),
        close_price=Decimal("96"),
    )
    up3 = service.on_candle_update(replace(c_neut2, symbol="SOLUSDT"))
    assert up3 is not None
    assert up3.status is StalkingStatus.EXPIRED

    # Verify Funnel Report
    report = service.get_funnel_report()
    assert report.scanned_count == 13
    assert report.zone_candidates == 3
    assert report.rejected_before_register == 10
    assert report.registered == 3
    assert report.retest_touched == 1
    assert report.triggered == 1
    assert report.invalidated == 1
    assert report.expired == 1
    assert report.candidate_to_entry_conversion_pct == Decimal("33.3")
    assert report.invalidated_pct == Decimal("33.3")
    assert report.expired_pct == Decimal("33.3")
    assert report.rejections_by_reason == {
        "HTF extreme": 5,
        "Trend distance": 3,
        "Key level": 2,
    }

    summary = service.format_funnel_summary()
    assert "PIER STALKING FUNNEL" in summary
    assert "Scanned                  : 13" in summary
    assert "Zone candidates          : 3" in summary
    assert "Rejected before register : 10" in summary
    assert "Triggered                : 1" in summary
    assert "Invalidated              : 1" in summary
    assert "Expired                  : 1" in summary
    assert "HTF extreme" in summary

    # Reset test
    service.reset_funnel_telemetry()
    reset_report = service.get_funnel_report()
    assert reset_report.scanned_count == 0
    assert reset_report.zone_candidates == 0
    assert reset_report.rejections_by_reason == {}
