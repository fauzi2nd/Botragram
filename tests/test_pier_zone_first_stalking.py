"""
Botragram

Description:
    Deterministic unit tests validating the complete lifecycle of PIER
    Zone-First Stalking architecture:
    ZONE -> STALK -> REJECTION -> RETEST -> ENTRY

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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

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
from botragram.models.stalking import StalkingSetup
from botragram.repositories import SignalRepository
from botragram.services.setup_stalking_service import SetupStalkingService
from botragram.services.strategy_service import StrategyService
from botragram.storage import MemorySignalRepository
from botragram.strategies.factory import StrategyResolver
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)

_START_TIME: Final[datetime] = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)


# =============================================================================
# Test Helpers
# =============================================================================
def _make_candle(
    *,
    symbol: str = "BTCUSDT",
    interval: Interval = Interval.M5,
    index: int = 0,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
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
        volume=volume,
    )


def _build_downtrend_candles(
    *,
    count: int = 60,
    symbol: str = "BTCUSDT",
) -> list[Candle]:
    """Generate deterministic synthetic candles establishing an EMA downtrend."""
    candles: list[Candle] = []
    base_price = Decimal("200.0")
    for i in range(count):
        price = base_price - (Decimal(str(i)) * Decimal("0.3"))
        candles.append(
            _make_candle(
                symbol=symbol,
                index=i,
                open_price=price,
                high_price=price + Decimal("1.0"),
                low_price=price - Decimal("1.0"),
                close_price=price - Decimal("0.2"),
                volume=Decimal("100.0"),
            )
        )
    return candles


def _build_uptrend_candles(
    *,
    count: int = 60,
    symbol: str = "BTCUSDT",
) -> list[Candle]:
    """Generate deterministic synthetic candles establishing an EMA uptrend."""
    candles: list[Candle] = []
    base_price = Decimal("100.0")
    for i in range(count):
        price = base_price + (Decimal(str(i)) * Decimal("0.3"))
        candles.append(
            _make_candle(
                symbol=symbol,
                index=i,
                open_price=price,
                high_price=price + Decimal("1.0"),
                low_price=price - Decimal("1.0"),
                close_price=price + Decimal("0.2"),
                volume=Decimal("100.0"),
            )
        )
    return candles


class _InMemorySignalRepository(SignalRepository):
    """In-memory stub repository for signal persistence."""

    def __init__(self) -> None:
        self.saved: list[Signal] = []

    async def save(self, *, signal: Signal) -> None:
        self.saved.append(signal)

    async def save_many(self, *, signals: Sequence[Signal]) -> None:
        self.saved.extend(signals)

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        filtered = self.saved
        if symbol is not None:
            filtered = [s for s in filtered if s.symbol == symbol]
        if signal_type is not None:
            filtered = [s for s in filtered if s.signal_type is signal_type]
        if strategy_name is not None:
            filtered = [s for s in filtered if s.strategy_name == strategy_name]
        return tuple(filtered[-limit:])

    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        filtered = [s for s in self.saved if start_time <= s.generated_at <= end_time]
        if symbol is not None:
            filtered = [s for s in filtered if s.symbol == symbol]
        if signal_type is not None:
            filtered = [s for s in filtered if s.signal_type is signal_type]
        if strategy_name is not None:
            filtered = [s for s in filtered if s.strategy_name == strategy_name]
        return tuple(filtered)

    async def get_latest_for_symbol(
        self,
        *,
        symbol: str,
        strategy_name: str | None = None,
    ) -> Signal | None:
        for s in reversed(self.saved):
            if s.symbol == symbol:
                if strategy_name is None or s.strategy_name == strategy_name:
                    return s
        return None

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        before_count = len(self.saved)
        self.saved = [
            s
            for s in self.saved
            if not (s.generated_at < before and (symbol is None or s.symbol == symbol))
        ]
        return before_count - len(self.saved)

    async def count(
        self,
        *,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> int:
        filtered = self.saved
        if symbol is not None:
            filtered = [s for s in filtered if s.symbol == symbol]
        if signal_type is not None:
            filtered = [s for s in filtered if s.signal_type is signal_type]
        if strategy_name is not None:
            filtered = [s for s in filtered if s.strategy_name == strategy_name]
        return len(filtered)


class _DirectStrategyResolver(StrategyResolver):
    """Resolver that returns a fixed strategy instance."""

    def __init__(self, strategy: PinbarEngulfingEmaRsiStrategy) -> None:
        self._strategy = strategy

    def resolve(self, *, strategy_type: StrategyType) -> PinbarEngulfingEmaRsiStrategy:
        return self._strategy


# =============================================================================
# Unit Tests (1 - 20)
# =============================================================================
def test_1_short_zone_candidate_enters_stalking_without_pinbar_engulfing() -> None:
    """1. SHORT zone candidate enters STALKING without candlestick pattern."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
        require_trend_filter=True,
    )
    candles = _build_downtrend_candles(count=60)
    # Pushes into EMA5 resistance without reversal pattern
    last = candles[-1]
    candles[-1] = _make_candle(
        index=59,
        open_price=last.close_price,
        high_price=last.close_price + Decimal("2.0"),
        low_price=last.close_price - Decimal("0.5"),
        close_price=last.close_price + Decimal("1.5"),
    )

    zone_sig = strategy.detect_zone_candidate(candles=candles)
    assert zone_sig is not None
    assert zone_sig.signal_type is SignalType.HOLD
    assert zone_sig.reason is not None and "[STALKING_ZONE_SHORT]" in zone_sig.reason

    stalking_svc = SetupStalkingService(max_candidates=5)
    setup = stalking_svc.register_candidate(
        signal=zone_sig,
        setup_candle=candles[-1],
    )
    assert setup is not None
    assert setup.status is StalkingStatus.STALKING
    assert setup.side is PositionSide.SHORT
    assert setup.pattern_name == "ZONE_SHORT"
    assert setup.reversal_confirmed is False


def test_2_long_zone_candidate_enters_stalking_without_pinbar_engulfing() -> None:
    """2. LONG zone candidate enters STALKING without candlestick pattern."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
        require_trend_filter=True,
    )
    candles = _build_uptrend_candles(count=60)
    last = candles[-1]
    candles[-1] = _make_candle(
        index=59,
        open_price=last.close_price,
        high_price=last.close_price + Decimal("0.5"),
        low_price=last.close_price - Decimal("2.0"),
        close_price=last.close_price - Decimal("1.5"),
    )

    zone_sig = strategy.detect_zone_candidate(candles=candles)
    assert zone_sig is not None
    assert zone_sig.signal_type is SignalType.HOLD
    assert zone_sig.reason is not None and "[STALKING_ZONE_LONG]" in zone_sig.reason

    stalking_svc = SetupStalkingService(max_candidates=5)
    setup = stalking_svc.register_candidate(
        signal=zone_sig,
        setup_candle=candles[-1],
    )
    assert setup is not None
    assert setup.status is StalkingStatus.STALKING
    assert setup.side is PositionSide.LONG
    assert setup.pattern_name == "ZONE_LONG"
    assert setup.reversal_confirmed is False


def test_3_price_in_middle_of_range_does_not_make_stalking() -> None:
    """3. Price in the middle of range (far from resistance/support) does not stalk."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
        pullback_proximity_pct=Decimal("0.001"),
        location_tolerance_pct=Decimal("0.001"),
    )
    candles = _build_downtrend_candles(count=60)
    # Price plummets far below EMA pullback and resistance
    last = candles[-1]
    candles[-1] = _make_candle(
        index=59,
        open_price=last.close_price - Decimal("10.0"),
        high_price=last.close_price - Decimal("9.5"),
        low_price=last.close_price - Decimal("11.0"),
        close_price=last.close_price - Decimal("10.5"),
    )

    zone_sig = strategy.detect_zone_candidate(candles=candles)
    assert zone_sig is None


def test_4_short_zone_requires_htf_extreme_and_local_resistance() -> None:
    """4. SHORT zone requires HTF upper extreme + local resistance."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=True,
    )
    # Insufficient HTF candles -> fail-closed
    candles = _build_downtrend_candles(count=40)
    zone_sig = strategy.detect_zone_candidate(candles=candles)
    assert zone_sig is None


def test_5_long_zone_requires_htf_lower_extreme_and_local_support() -> None:
    """5. LONG zone requires HTF lower extreme + local support."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=True,
    )
    # Insufficient HTF candles -> fail-closed
    candles = _build_uptrend_candles(count=40)
    zone_sig = strategy.detect_zone_candidate(candles=candles)
    assert zone_sig is None


def test_6_zone_candidate_does_not_immediately_enter() -> None:
    """6. Zone candidate does NOT produce an immediate BUY/SELL actionable entry."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
    )
    resolver = _DirectStrategyResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_svc = SetupStalkingService(max_candidates=5)
    repo = _InMemorySignalRepository()
    service = StrategyService(
        signal_engine=engine,
        signal_repository=repo,
        setup_stalking_service=stalking_svc,
        stalking_enabled=True,
    )
    candles = _build_downtrend_candles(count=60)

    sig = service.generate_signal(candles=candles)
    assert sig.signal_type is SignalType.HOLD
    assert sig.signal_type not in {SignalType.BUY, SignalType.SELL}


def test_7_invalid_reversal_does_not_trigger() -> None:
    """7. Non-reversal candle in Stage 2 does not confirm reversal or trigger entry."""
    service = SetupStalkingService()
    candle0 = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("98"),
        close_price=Decimal("104"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.HOLD,
        price=Decimal("104"),
        confidence=Decimal("0.70"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="[STALKING_ZONE_SHORT] Zone candidate",
    )
    service.register_candidate(signal=signal, setup_candle=candle0)

    # Bar 1 is a strong green candle continuing up (no rejection, no pinbar)
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("104"),
        high_price=Decimal("105"),
        low_price=Decimal("103"),
        close_price=Decimal("105"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    assert updated.status is StalkingStatus.STALKING
    assert updated.reversal_confirmed is False
    assert updated.current_bar == 1


def test_8_retest_without_rejection_does_not_trigger() -> None:
    """8. Retest touch without rejection does not trigger entry."""
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

    # Retest target is 96. Bar 1 breaks above target 96 without rejection
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


def test_9_retest_plus_rejection_valid_triggers() -> None:
    """9. Retest touch with rejection confirmation validly triggers entry."""
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

    # Bar 1 touches target 96 (high 97) and closes below at 95 (rejection confirmed)
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


def test_10_invalidation_stops_setup() -> None:
    """10. Peak/valley breach invalidates setup with zero capital loss."""
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

    # High breaches peak 110 (high 112)
    candle1 = _make_candle(
        index=1,
        open_price=Decimal("93"),
        high_price=Decimal("112"),
        low_price=Decimal("93"),
        close_price=Decimal("105"),
    )
    updated = service.on_candle_update(candle1)
    assert updated is not None
    assert updated.status is StalkingStatus.INVALIDATED


def test_11_expiry_stops_setup() -> None:
    """11. Reaching max_bars window without trigger expires setup."""
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

    updated: StalkingSetup | None = None
    # Bars 1, 2, 3 do not touch target 96
    for b in range(1, 4):
        c = _make_candle(
            index=b,
            open_price=Decimal("92"),
            high_price=Decimal("93"),
            low_price=Decimal("91"),
            close_price=Decimal("92"),
        )
        updated = service.on_candle_update(c)
        assert updated is not None

    assert updated is not None
    assert updated.status is StalkingStatus.EXPIRED
    assert updated.current_bar == 3


def test_12_duplicate_closed_candle_does_not_advance_current_bar() -> None:
    """12. Duplicate closed candle is skipped and current_bar does not advance."""
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

    candle1 = _make_candle(
        index=1,
        open_price=Decimal("92"),
        high_price=Decimal("93"),
        low_price=Decimal("91"),
        close_price=Decimal("92"),
    )
    up1 = service.on_candle_update(candle1)
    assert up1 is not None
    assert up1.current_bar == 1

    # Same candle passed again
    up2 = service.on_candle_update(candle1)
    assert up2 is not None
    assert up2.current_bar == 1


def test_13_discovery_cadence_faster_than_interval_does_not_corrupt_stalking() -> None:
    """13. Discovery running faster than interval does not corrupt stalking state."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
    )
    resolver = _DirectStrategyResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_svc = SetupStalkingService()
    repo = _InMemorySignalRepository()
    service = StrategyService(
        signal_engine=engine,
        signal_repository=repo,
        setup_stalking_service=stalking_svc,
        stalking_enabled=True,
    )
    candles = _build_downtrend_candles(count=60)

    # First evaluation registers stalking
    sig1 = service.generate_signal(candles=candles)
    assert sig1.signal_type is SignalType.HOLD
    setup1 = stalking_svc.get_setup("BTCUSDT")
    assert setup1 is not None
    assert setup1.current_bar == 0

    # Rapid re-evaluation with same candle window does not increment bar
    sig2 = service.generate_signal(candles=candles)
    assert sig2.signal_type is SignalType.HOLD
    setup2 = stalking_svc.get_setup("BTCUSDT")
    assert setup2 is not None
    assert setup2.current_bar == 0


def test_14_active_stalking_symbol_prioritized_by_discovery() -> None:
    """14. Active stalking symbol is prioritized to front of discovery scans."""
    stalking_svc = SetupStalkingService()
    candle = _make_candle(
        symbol="ETHUSDT",
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    sig = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    stalking_svc.register_candidate(signal=sig, setup_candle=candle)

    symbols = stalking_svc.get_active_stalking_symbols()
    assert "ETHUSDT" in symbols


def test_15_max_candidate_capacity_enforced() -> None:
    """15. Maximum concurrent candidates capacity is strictly enforced."""
    service = SetupStalkingService(max_candidates=2)
    candle_a = _make_candle(
        symbol="BTCUSDT",
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    sig_a = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    candle_b = _make_candle(
        symbol="ETHUSDT",
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    sig_b = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    assert service.register_candidate(signal=sig_a, setup_candle=candle_a) is not None
    assert service.register_candidate(signal=sig_b, setup_candle=candle_b) is not None

    # 3rd symbol exceeds capacity limit
    candle_c = _make_candle(
        symbol="SOLUSDT",
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("92"),
    )
    sig_c = Signal(
        symbol="SOLUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("92"),
        confidence=Decimal("0.85"),
        strategy_name="PIER",
        generated_at=_START_TIME,
        reason="BEARISH ENGULFING",
    )
    assert service.register_candidate(signal=sig_c, setup_candle=candle_c) is None


def test_16_triggered_signal_preserves_sl_tp_and_protection() -> None:
    """16. Triggered signal retains SL, TP, confidence, and protection fields."""
    service = SetupStalkingService()
    now = datetime.now(UTC)
    setup = StalkingSetup(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        pattern_name="BEARISH_ENGULFING",
        anchor_price=Decimal("100"),
        invalidation_price=Decimal("105"),
        target_retest_price=Decimal("102"),
        htf_zone_label="HTF Extreme SHORT",
        current_bar=2,
        max_bars=7,
        started_at=now,
        updated_at=now,
        status=StalkingStatus.TRIGGERED,
        stop_loss=Decimal("106"),
        take_profit=Decimal("92"),
        confidence=Decimal("0.85"),
    )
    trigger_candle = _make_candle(
        index=2,
        open_price=Decimal("101"),
        high_price=Decimal("103"),
        low_price=Decimal("100"),
        close_price=Decimal("101.5"),
    )

    sig = service.build_triggered_signal(setup=setup, trigger_candle=trigger_candle)
    assert sig.symbol == "BTCUSDT"
    assert sig.signal_type is SignalType.SELL
    assert sig.stop_loss == Decimal("106")
    assert sig.take_profit == Decimal("92")
    # Base confidence 0.85 + 0.05 bonus for decisive BEARISH_PINBAR pattern
    assert sig.confidence == Decimal("0.90")
    assert sig.reason is not None and "[STALKING_TRIGGERED]" in sig.reason

    # Generic rejection without decisive pattern does not get the bonus
    generic_setup = replace(setup, pattern_name="BEARISH_REJECTION")
    generic_sig = service.build_triggered_signal(
        setup=generic_setup,
        trigger_candle=trigger_candle,
    )
    assert generic_sig.confidence == Decimal("0.85")


def test_17_pier_stalking_disabled_preserves_legacy_behavior() -> None:
    """17. When PIER_STALKING_ENABLED=False, legacy direct execution is preserved."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
    )
    resolver = _DirectStrategyResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_svc = SetupStalkingService()
    repo = _InMemorySignalRepository()
    service = StrategyService(
        signal_engine=engine,
        signal_repository=repo,
        setup_stalking_service=stalking_svc,
        stalking_enabled=False,  # Disabled
    )
    candles = _build_downtrend_candles(count=60)
    _ = service.generate_signal(candles=candles)
    # Stalking service was never engaged
    assert stalking_svc.get_setup("BTCUSDT") is None


def test_18_htf_data_missing_fails_closed_when_htf_required() -> None:
    """18. When HTF extreme gate is required and HTF data is missing, fail-closed."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=True,
    )
    candles = _build_downtrend_candles(count=40)  # Insufficient for HTF BB
    candidate = strategy.detect_zone_candidate(candles=candles)
    assert candidate is None


def test_19_long_and_short_are_exact_semantic_mirrors() -> None:
    """19. LONG and SHORT zone definitions, bounds, and retests are exact mirrors."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
    )
    downtrend_candles = _build_downtrend_candles(count=60)
    uptrend_candles = _build_uptrend_candles(count=60)

    short_cand = strategy.detect_zone_candidate(candles=downtrend_candles)
    long_cand = strategy.detect_zone_candidate(candles=uptrend_candles)

    assert short_cand is not None
    assert long_cand is not None
    assert (
        short_cand.reason is not None and "[STALKING_ZONE_SHORT]" in short_cand.reason
    )
    assert long_cand.reason is not None and "[STALKING_ZONE_LONG]" in long_cand.reason
    assert short_cand.stop_loss is not None and short_cand.stop_loss > short_cand.price
    assert long_cand.stop_loss is not None and long_cand.stop_loss < long_cand.price


def test_20_no_direct_actionable_pier_entry_when_stalking_active() -> None:
    """20. When stalking is active, direct immediate BUY/SELL entry is never emitted."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        atr_period=5,
        require_htf_extreme_zone=False,
    )
    resolver = _DirectStrategyResolver(strategy)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_svc = SetupStalkingService()
    repo = _InMemorySignalRepository()
    service = StrategyService(
        signal_engine=engine,
        signal_repository=repo,
        setup_stalking_service=stalking_svc,
        stalking_enabled=True,
    )
    candles = _build_downtrend_candles(count=60)

    # First candle in zone -> enters stalking (HOLD)
    sig1 = service.generate_signal(candles=candles)
    assert sig1.signal_type is SignalType.HOLD

    # Second candle in zone -> still stalking or waiting for retest (HOLD)
    candles.append(
        _make_candle(
            index=60,
            open_price=candles[-1].close_price,
            high_price=candles[-1].close_price + Decimal("1.0"),
            low_price=candles[-1].close_price - Decimal("1.0"),
            close_price=candles[-1].close_price - Decimal("0.5"),
        )
    )
    sig2 = service.generate_signal(candles=candles)
    assert sig2.signal_type is SignalType.HOLD
    assert sig2.signal_type not in {SignalType.BUY, SignalType.SELL}


def test_22_zone_confidence_scores_higher_on_confluence() -> None:
    """22. Dynamic zone confidence scales with HTF depth, volume, and confluence."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        min_confidence=Decimal("0.65"),
    )
    candle = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("99"),
        close_price=Decimal("102"),
        volume=Decimal("500"),
    )

    # Base minimum confidence with 0 confluence
    score_low = strategy.compute_zone_confidence(
        side=PositionSide.SHORT,
        current_candle=candle,
        trend_distance_pct=Decimal("0.01"),
        eff_min_trend_pct=Decimal("0.02"),
        htf_extreme_depth=Decimal("0"),
        at_ema=False,
        at_swing=False,
        volume=Decimal("100"),
        volume_sma=Decimal("200"),
    )
    assert score_low == Decimal("0.65")

    # High confluence (deep HTF penetration + strong trend + EMA + swing + volume + RSI)
    score_high = strategy.compute_zone_confidence(
        side=PositionSide.SHORT,
        current_candle=candle,
        trend_distance_pct=Decimal("0.05"),
        eff_min_trend_pct=Decimal("0.02"),
        htf_extreme_depth=Decimal("0.8"),
        at_ema=True,
        at_swing=True,
        volume=Decimal("500"),
        volume_sma=Decimal("200"),
        rsi=Decimal("70"),
    )
    assert score_high > Decimal("0.85")
    assert score_high <= Decimal("0.95")


def test_pier_stalking_funnel_strategy_service_integration() -> None:
    """StrategyService tracks scans, candidates, and rejection breakdown."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        rsi_period=14,
        min_natr_threshold=Decimal("0.001"),
        require_htf_extreme_zone=False,
        require_key_level_location=False,
    )
    signal_engine = SignalEngine(
        strategy_resolver=StrategyResolver(
            strategies={StrategyType.PINBAR_ENGULFING_EMA_RSI: strategy}
        ),
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_svc = SetupStalkingService(max_candidates=5)
    strategy_svc = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_svc,
        stalking_enabled=True,
    )

    # 1. Provide flat dead candles (fails NATR)
    dead_candles = [
        _make_candle(
            index=i,
            open_price=Decimal("100"),
            high_price=Decimal("100.001"),
            low_price=Decimal("99.999"),
            close_price=Decimal("100"),
        )
        for i in range(40)
    ]
    sig_hold = strategy_svc.generate_signal(
        candles=dead_candles,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    assert sig_hold.signal_type is SignalType.HOLD

    report = strategy_svc.get_stalking_funnel_report()
    assert report is not None
    assert report.scanned_count == 1
    assert report.zone_candidates == 0
    assert report.rejected_before_register == 1
    assert report.rejections_by_reason.get("NATR") == 1


def test_pier_trigger_guards_bollinger_bands() -> None:
    """BB entry guard rejects LONG when near Upper Band and SHORT near Lower Band."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        rsi_period=14,
        bb_period=20,
        bb_std_dev=Decimal("2.0"),
        use_macd=False,
    )
    # Candle that pushes high into Upper Band zone and closes near high
    # Std dev of varying candles to have meaningful BB
    candles_varying = [
        _make_candle(
            index=i,
            open_price=Decimal("100") + Decimal(str(i % 5)),
            high_price=Decimal("106") + Decimal(str(i % 5)),
            low_price=Decimal("95") + Decimal(str(i % 5)),
            close_price=Decimal("100") + Decimal(str(i % 5)),
        )
        for i in range(30)
    ]
    # Compute BB on candles_varying
    from botragram.indicators import calculate_bollinger_bands

    bb = calculate_bollinger_bands(
        [c.close_price for c in candles_varying],
        period=20,
        standard_deviation=Decimal("2.0"),
    )
    assert bb is not None
    curr_upper = bb.upper[-1]
    curr_mid = bb.middle[-1]
    curr_lower = bb.lower[-1]

    # 1. Test LONG overbought (close in upper zone of BB)
    ub_pucuk_price = curr_mid + ((curr_upper - curr_mid) * Decimal("0.80"))
    pucuk_candle = _make_candle(
        index=30,
        open_price=curr_mid,
        high_price=curr_upper + Decimal("1.0"),
        low_price=curr_mid,
        close_price=ub_pucuk_price,
    )
    is_valid, reason = strategy.validate_trigger_guards(
        side=PositionSide.LONG,
        candles=candles_varying + [pucuk_candle],
    )
    assert not is_valid
    assert "BB upper zone" in reason

    # 2. Test LONG rejection from Upper Band (touched upper band, closed red)
    reject_ub_candle = _make_candle(
        index=30,
        open_price=curr_upper - Decimal("0.1"),
        high_price=curr_upper + Decimal("0.5"),
        low_price=curr_mid,
        close_price=curr_upper - Decimal("1.0"),
    )
    is_valid_ub, reason_ub = strategy.validate_trigger_guards(
        side=PositionSide.LONG,
        candles=candles_varying + [reject_ub_candle],
    )
    assert not is_valid_ub
    assert "Upper Bollinger Band" in reason_ub

    # 3. Test SHORT oversold (close in lower zone of BB)
    lb_lembah_price = curr_mid - ((curr_mid - curr_lower) * Decimal("0.80"))
    lembah_candle = _make_candle(
        index=30,
        open_price=curr_mid,
        high_price=curr_mid,
        low_price=curr_lower - Decimal("1.0"),
        close_price=lb_lembah_price,
    )
    is_valid_short, reason_short = strategy.validate_trigger_guards(
        side=PositionSide.SHORT,
        candles=candles_varying + [lembah_candle],
    )
    assert not is_valid_short
    assert "BB lower zone" in reason_short


def test_pier_trigger_guards_macd_momentum() -> None:
    """MACD momentum guard rejects LONG on decaying histogram (bar kosong)."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        rsi_period=14,
        bb_period=20,
        use_macd=True,
        macd_fast_period=12,
        macd_slow_period=26,
        macd_signal_period=9,
    )
    # Generate 50 trending candles
    candles = [
        _make_candle(
            index=i,
            open_price=Decimal("100") + (Decimal(str(i)) * Decimal("0.5")),
            high_price=Decimal("101") + (Decimal(str(i)) * Decimal("0.5")),
            low_price=Decimal("99") + (Decimal(str(i)) * Decimal("0.5")),
            close_price=Decimal("100.4") + (Decimal(str(i)) * Decimal("0.5")),
        )
        for i in range(50)
    ]
    # Now simulate momentum decaying: add small flat candles so histogram shrinks
    decaying_candles = list(candles)
    last_close = decaying_candles[-1].close_price
    for j in range(5):
        decaying_candles.append(
            _make_candle(
                index=50 + j,
                open_price=last_close,
                high_price=last_close + Decimal("0.1"),
                low_price=last_close - Decimal("0.1"),
                close_price=last_close,
            )
        )

    from botragram.indicators import calculate_macd

    macd = calculate_macd(
        [c.close_price for c in decaying_candles],
        fast_period=12,
        slow_period=26,
        signal_period=9,
    )
    assert macd is not None

    # Check that validate_trigger_guards evaluates MACD correctly
    is_valid, reason = strategy.validate_trigger_guards(
        side=PositionSide.LONG,
        candles=decaying_candles,
    )
    if macd.histogram[-1] < Decimal("0") or (
        len(macd.histogram) >= 2 and macd.histogram[-1] < macd.histogram[-2]
    ):
        assert not is_valid
        assert "MACD histogram" in reason


def test_pier_trigger_guards_strategy_service_invalidation() -> None:
    """StrategyService invalidates triggered setup when trigger guards fail."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=20,
        pullback_period=5,
        rsi_period=14,
        bb_period=20,
        use_macd=False,
        require_htf_extreme_zone=False,
        require_key_level_location=False,
    )
    signal_engine = SignalEngine(
        strategy_resolver=StrategyResolver(
            strategies={StrategyType.PINBAR_ENGULFING_EMA_RSI: strategy}
        ),
        default_strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    stalking_svc = SetupStalkingService(max_candidates=5)
    strategy_svc = StrategyService(
        signal_engine=signal_engine,
        signal_repository=MemorySignalRepository(),
        setup_stalking_service=stalking_svc,
        stalking_enabled=True,
    )

    # 1. Create a setup that triggers
    # Build 30 candles where price reaches Upper BB
    candles: list[Candle] = []
    for i in range(34):
        price = Decimal("100") + (Decimal(str(i)) * Decimal("0.8"))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("1.5"),
                low_price=price - Decimal("0.5"),
                close_price=price + Decimal("0.7"),
            )
        )

    # Register candidate manually in stalking service
    cand = candles[-1]
    stalking_svc.register_candidate(
        signal=Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=cand.close_price,
            confidence=Decimal("0.75"),
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
            generated_at=cand.close_time,
            reason="Test Long Setup",
            stop_loss=cand.low_price - Decimal("1.0"),
            take_profit=cand.close_price + Decimal("3.0"),
        ),
        setup_candle=cand,
        reversal_confirmed=True,
    )
    setup = stalking_svc.get_setup("BTCUSDT")
    assert setup is not None
    assert setup.status is StalkingStatus.STALKING

    # Target retest is set to 127.0
    stalking_svc.set_setup_for_testing(
        replace(setup, target_retest_price=Decimal("127.0"))
    )

    # Next candle opens at 127.2, dips to 126.8 (touching 127.0),
    # and bounces up to 128.0 (at Upper BB)
    trigger_candle = _make_candle(
        index=34,
        open_price=Decimal("127.2"),
        high_price=Decimal("128.5"),
        low_price=Decimal("126.8"),
        close_price=Decimal("128.0"),
    )
    all_candles = candles + [trigger_candle]

    # Next candle touches target at Upper BB zone
    sig = strategy_svc.generate_signal(
        candles=all_candles,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    # The signal should be HOLD because trigger guards reject entry at Upper BB
    assert sig.signal_type is SignalType.HOLD
    assert "[STALKING_INVALIDATED]" in (sig.reason or "")
    # Check that setup status in stalking_svc is INVALIDATED
    final_setup = stalking_svc.get_setup("BTCUSDT")
    assert final_setup is not None
    assert final_setup.status is StalkingStatus.INVALIDATED


def test_stalking_retest_bounce_hardening() -> None:
    """A red candle dumping into its low cannot trigger a LONG retest bounce."""
    stalking_svc = SetupStalkingService(max_candidates=5)
    setup_candle = _make_candle(
        index=0,
        open_price=Decimal("100"),
        high_price=Decimal("102"),
        low_price=Decimal("99"),
        close_price=Decimal("101"),
    )
    stalking_svc.register_candidate(
        signal=Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("101"),
            confidence=Decimal("0.75"),
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
            generated_at=setup_candle.close_time,
            reason="Test Long Setup",
        ),
        setup_candle=setup_candle,
        reversal_confirmed=True,
    )
    setup = stalking_svc.get_setup("BTCUSDT")
    assert setup is not None

    # Set target retest price to 100.5
    stalking_svc.set_setup_for_testing(
        replace(
            setup,
            target_retest_price=Decimal("100.5"),
        )
    )

    # Bar 1: Red candle dumping into close with tiny lower wick (like the 2ZUSDT bar)
    # open=101.0, high=101.2, low=100.4, close=100.5
    # range=0.8, upper_wick=0.2, lower_wick=0.1. Lower wick is smaller than upper wick!
    dumping_candle = _make_candle(
        index=1,
        open_price=Decimal("101.0"),
        high_price=Decimal("101.2"),
        low_price=Decimal("100.4"),
        close_price=Decimal("100.5"),
    )
    updated = stalking_svc.on_candle_update(dumping_candle)
    assert updated is not None
    # Must NOT trigger because it is a red dump candle without a dominant lower wick
    assert updated.status is StalkingStatus.STALKING

    # Bar 2: A true bullish bounce candle (green with dominant lower wick)
    # open=100.5, low=100.3, high=101.0, close=100.9
    bounce_candle = _make_candle(
        index=2,
        open_price=Decimal("100.5"),
        high_price=Decimal("101.0"),
        low_price=Decimal("100.3"),
        close_price=Decimal("100.9"),
    )
    updated_bounce = stalking_svc.on_candle_update(bounce_candle)
    assert updated_bounce is not None
    assert updated_bounce.status is StalkingStatus.TRIGGERED
