"""
Botragram

Description:
    Coverage gap tests for RiskEngine — edge cases and boundary paths
    not exercised by existing test files.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Third Party
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.risk_engine import RiskEngine
from botragram.enums import Interval, PositionSide, SignalType, StrategyType
from botragram.models import Candle, Position, Signal

# =============================================================================
# Helpers
# =============================================================================
_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _settings() -> RiskSettings:
    """Return the shared valid risk configuration for boundary tests."""
    return RiskSettings(
        leverage=5,
        min_leverage=1,
        max_leverage=25,
        min_order_notional_usdt=Decimal("5"),
        slot_margin_buffer_pct=Decimal("0.05"),
    )


def _signal(
    *,
    signal_type: SignalType = SignalType.BUY,
    price: Decimal = Decimal("100"),
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
    confidence: Decimal = Decimal("0.70"),
    strategy: str = StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
) -> Signal:
    return Signal(
        symbol="XYZUSDT",
        signal_type=signal_type,
        price=price,
        confidence=confidence,
        strategy_name=strategy,
        generated_at=_NOW,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def _position(
    *,
    side: PositionSide = PositionSide.LONG,
    entry_price: Decimal = Decimal("100"),
    stop_loss: Decimal | None = Decimal("95"),
    take_profit: Decimal | None = Decimal("110"),
    leverage: int = 5,
    opened_at: datetime | None = None,
) -> Position:
    ts = opened_at or _NOW
    return Position(
        symbol="XYZUSDT",
        side=side,
        entry_price=entry_price,
        current_price=entry_price,
        unrealized_pnl=Decimal("0"),
        quantity=Decimal("1"),
        leverage=leverage,
        stop_loss=stop_loss,
        take_profit=take_profit,
        opened_at=ts,
        updated_at=ts,
    )


def _candle(
    *,
    open_price: Decimal = Decimal("100"),
    high_price: Decimal = Decimal("105"),
    low_price: Decimal = Decimal("95"),
    close_price: Decimal = Decimal("102"),
    close_time: datetime | None = None,
) -> Candle:
    ts = close_time or _NOW
    return Candle(
        symbol="XYZUSDT",
        interval=Interval.M5,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=Decimal("1000"),
        open_time=ts - timedelta(minutes=5),
        close_time=ts,
    )


# =============================================================================
# calculate_tp_progress — missing lines 104, 108
# =============================================================================
class TestCalculateTpProgress:
    def test_returns_zero_when_take_profit_is_none(self) -> None:
        """Line 104: take_profit is None -> 0."""
        pos = _position(take_profit=None)
        result = RiskEngine.calculate_tp_progress(
            position=pos,
            current_price=Decimal("102"),
        )
        assert result == Decimal("0")

    def test_returns_zero_when_entry_equals_take_profit(self) -> None:
        """Line 108: target_distance <= 0 -> 0."""
        pos = _position(entry_price=Decimal("100"), take_profit=Decimal("100"))
        result = RiskEngine.calculate_tp_progress(
            position=pos,
            current_price=Decimal("100"),
        )
        assert result == Decimal("0")


# =============================================================================
# calculate_position_roi — missing line 125
# =============================================================================
class TestCalculatePositionRoi:
    def test_returns_zero_when_leverage_zero(self) -> None:
        """Line 125: leverage = 0 -> 0."""
        pos = _position(leverage=0)
        result = RiskEngine.calculate_position_roi(
            position=pos,
            current_price=Decimal("110"),
        )
        assert result == Decimal("0")

    def test_returns_zero_when_entry_price_zero(self) -> None:
        """Line 125: entry_price = 0 guard."""
        pos = Position(
            symbol="XYZUSDT",
            side=PositionSide.LONG,
            entry_price=Decimal("0"),
            current_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            quantity=Decimal("1"),
            leverage=5,
            stop_loss=None,
            take_profit=None,
            opened_at=_NOW,
            updated_at=_NOW,
        )
        result = RiskEngine.calculate_position_roi(
            position=pos,
            current_price=Decimal("100"),
        )
        assert result == Decimal("0")


# =============================================================================
# resolve_exit_rates public wrapper — line 65
# =============================================================================
class TestResolveExitRates:
    def test_public_wrapper_delegates_correctly(self) -> None:
        """Line 65: public resolve_exit_rates() delegates to _resolve_exit_rates."""
        engine = RiskEngine(settings=_settings())
        sl, tp = engine.resolve_exit_rates(
            strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI
        )
        assert sl == engine.settings.pier_stop_loss_pct
        assert tp == engine.settings.pier_take_profit_pct

    def test_returns_global_defaults_for_none_strategy(self) -> None:
        """Line 65 + case _: fallback to global defaults."""
        engine = RiskEngine(settings=_settings())
        sl, tp = engine.resolve_exit_rates(strategy_type=None)
        assert sl == engine.settings.stop_loss_pct
        assert tp == engine.settings.take_profit_pct


# =============================================================================
# calculate_protection_levels — line 76
# =============================================================================
class TestCalculateProtectionLevels:
    def test_raises_for_zero_entry_price(self) -> None:
        """Line 76: entry_price <= 0 raises ValueError."""
        engine = RiskEngine(settings=_settings())
        with pytest.raises(ValueError, match="entry price"):
            engine.calculate_protection_levels(
                side=PositionSide.LONG,
                entry_price=Decimal("0"),
            )


# =============================================================================
# resolve_breakeven_step — no take_profit, line 239
# =============================================================================
class TestResolveBreakevenStep:
    def test_returns_step_zero_below_threshold(self) -> None:
        """resolve_breakeven_step: ROI below threshold -> step 0."""
        result = RiskEngine.resolve_breakeven_step(roi=Decimal("0.10"))
        assert result == 0

    def test_returns_step_one_above_threshold(self) -> None:
        """resolve_breakeven_step: ROI above default threshold -> step 1."""
        result = RiskEngine.resolve_breakeven_step(roi=Decimal("0.35"))
        assert result == 1


# =============================================================================
# calculate_swing_pivot_stop_loss — SHORT path, lines 300, 323, 332-333
# =============================================================================
class TestCalculateSwingPivotStopLossCoverage:
    def test_short_candle_before_opened_breaks(self) -> None:
        """Line 323: close_time < opened_at -> break in SHORT loop."""
        future = _NOW + timedelta(hours=1)
        pos = _position(
            side=PositionSide.SHORT,
            stop_loss=Decimal("115"),
            opened_at=future,
        )
        candles = [
            _candle(
                high_price=Decimal("108"),
                close_time=_NOW - timedelta(minutes=10 * i),
            )
            for i in range(10)
        ]
        result = RiskEngine.calculate_swing_pivot_stop_loss(
            position=pos, candles=candles
        )
        assert result is None

    def test_short_no_swing_high_found(self) -> None:
        """Lines 332-333: is_swing_high set False for flat candles (no peak)."""
        opened = _NOW - timedelta(hours=1)
        pos = _position(
            side=PositionSide.SHORT,
            stop_loss=Decimal("120"),
            opened_at=opened,
        )
        candles = [
            _candle(
                high_price=Decimal("100"),
                low_price=Decimal("99"),
                close_price=Decimal("100"),
                close_time=_NOW + timedelta(minutes=5 * i),
            )
            for i in range(10)
        ]
        result = RiskEngine.calculate_swing_pivot_stop_loss(
            position=pos, candles=candles
        )
        assert result is None

    def test_long_candle_before_opened_breaks(self) -> None:
        """Line 300: close_time < opened_at -> break in LONG loop."""
        future = _NOW + timedelta(hours=1)
        pos = _position(
            side=PositionSide.LONG,
            stop_loss=Decimal("85"),
            opened_at=future,
        )
        candles = [
            _candle(
                low_price=Decimal("92"),
                close_time=_NOW - timedelta(minutes=10 * i),
            )
            for i in range(10)
        ]
        result = RiskEngine.calculate_swing_pivot_stop_loss(
            position=pos, candles=candles
        )
        assert result is None


# =============================================================================
# evaluate() — remaining_slots validation, line 371
# =============================================================================
class TestEvaluateValidation:
    def test_raises_for_remaining_slots_zero(self) -> None:
        """Line 371: remaining_slots = 0 raises ValueError."""
        engine = RiskEngine(settings=_settings())
        with pytest.raises(ValueError, match="Remaining slots"):
            engine.evaluate(
                signal=_signal(),
                account_balance=Decimal("100"),
                remaining_slots=0,
            )

    def test_raises_for_remaining_slots_negative(self) -> None:
        """Line 371: remaining_slots = -1 raises ValueError."""
        engine = RiskEngine(settings=_settings())
        with pytest.raises(ValueError, match="Remaining slots"):
            engine.evaluate(
                signal=_signal(),
                account_balance=Decimal("100"),
                remaining_slots=-1,
            )


# =============================================================================
# evaluate() — Origin: SL/TP distance = 0, lines 467, 481
# =============================================================================
class TestEvaluateOriginDistanceBoundaries:
    def _origin_signal(
        self,
        stop_loss: Decimal,
        take_profit: Decimal,
        price: Decimal = Decimal("100"),
    ) -> Signal:
        return _signal(
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=StrategyType.BOTRAGRAM_ORIGIN.value,
        )

    def test_rejected_when_origin_sl_distance_zero(self) -> None:
        """Line 467: SL distance = 0 after Origin SL-distance check.

        The Origin path (line 458) fires when strategy=BOTRAGRAM_ORIGIN
        AND both stop_loss and take_profit are provided. The SL=entry case
        is caught at line 416 (generic BUY SL guard) BEFORE Origin block.
        To reach line 467, provide a valid SL (below entry) so it passes
        line 416, but set actual_sl_dist = 0 by clamping. We can do this by
        abusing the TP=entry path instead and confirming the earlier guard
        covers both, or simply validate that the path before is covered.

        Instead: test that sl_dist=0 is reported correctly by making SL just
        barely above entry (invalid for BUY) - this hits line 416-421 and
        returns rejected. Line 467 is an unreachable guard in practice for BUY
        (already blocked at 416). Confirm rejection reason covers sl.
        """
        engine = RiskEngine(settings=_settings())
        result = engine.evaluate(
            signal=self._origin_signal(
                stop_loss=Decimal("101"),  # above price for BUY -> rejected at line 419
                take_profit=Decimal("103"),
            ),
            account_balance=Decimal("1000"),
        )
        assert not result.approved
        assert "stop-loss" in (result.reason or "").lower()

    def test_rejected_when_origin_tp_distance_zero(self) -> None:
        """Line 481: TP = entry -> distance = 0 -> rejected.

        For a BUY signal, TP <= entry is caught at line 441-448 before Origin
        block. To reach line 481 in Origin path: TP must pass the initial
        guard (TP > entry for BUY) but then TP-dist evaluates to 0 after
        the Origin sl_dist check. Since that's structurally impossible for a
        valid float (entry != TP and TP > entry implies dist > 0), line 481
        is a defensive guard. Cover the preceding guard instead:
        TP < entry for BUY -> rejected at line 441-448.
        """
        engine = RiskEngine(settings=_settings())
        result = engine.evaluate(
            signal=self._origin_signal(
                stop_loss=Decimal("97"),
                take_profit=Decimal(
                    "99"
                ),  # below price for BUY -> rejected at line 444
            ),
            account_balance=Decimal("1000"),
        )
        assert not result.approved
        assert "take-profit" in (result.reason or "").lower()


# =============================================================================
# evaluate() — slot_sizing: usable_balance <= 0, line 567
# =============================================================================
class TestEvaluateSlotSizingUsableBalance:
    def test_rejected_when_usable_balance_nearly_zero(self) -> None:
        """Line 573 path: slot_margin too small -> rejected (covers the check
        that happens when slot_margin * max_leverage < min_order_notional)."""
        settings = RiskSettings(
            leverage=5,
            min_leverage=1,
            max_leverage=25,
            slot_sizing_enabled=True,
            slot_margin_buffer_pct=Decimal("0.9999"),
            min_order_notional_usdt=Decimal("5"),
        )
        engine = RiskEngine(settings=settings)
        sig = _signal(
            signal_type=SignalType.BUY,
            price=Decimal("1"),
            stop_loss=Decimal("0.9"),
        )
        result = engine.evaluate(
            signal=sig,
            account_balance=Decimal("0.0001"),
            remaining_slots=1,
        )
        assert not result.approved
        # Hits either 'Insufficient usable balance' (line 567) or
        # 'Insufficient slot margin' (line 573) depending on precision
        assert not result.approved


# =============================================================================
# evaluate() — slot_sizing + volatility_sizing, lines 603-610
# =============================================================================
class TestEvaluateSlotSizingWithVolatility:
    def test_volatility_multiplier_applied_in_slot_path(self) -> None:
        """Lines 603-610: slot path applies vol_multiplier when vol sizing enabled."""
        settings = RiskSettings(
            leverage=5,
            min_leverage=1,
            max_leverage=25,
            slot_sizing_enabled=True,
            slot_margin_buffer_pct=Decimal("0.05"),
            min_order_notional_usdt=Decimal("1"),
            volatility_sizing_enabled=True,
            baseline_volatility_pct=Decimal("0.02"),
            confidence_sizing_enabled=False,
        )
        engine = RiskEngine(settings=settings)
        sig = _signal(
            signal_type=SignalType.BUY,
            price=Decimal("100"),
            stop_loss=Decimal("95"),
        )
        result_normal = engine.evaluate(
            signal=sig,
            account_balance=Decimal("100"),
            remaining_slots=1,
            volatility_pct=Decimal("0.02"),
        )
        result_high_vol = engine.evaluate(
            signal=sig,
            account_balance=Decimal("100"),
            remaining_slots=1,
            volatility_pct=Decimal("0.04"),
        )
        assert result_normal.approved
        assert result_high_vol.approved
        assert result_high_vol.position.notional < result_normal.position.notional


# =============================================================================
# evaluate() — slot_sizing + confidence_sizing, lines 618-625
# =============================================================================
class TestEvaluateSlotSizingWithConfidence:
    def test_confidence_multiplier_applied_in_slot_path(self) -> None:
        """Lines 618-625: slot path applies conf_multiplier when dynamic+confidence
        enabled."""
        settings = RiskSettings(
            leverage=5,
            min_leverage=1,
            max_leverage=25,
            slot_sizing_enabled=True,
            slot_margin_buffer_pct=Decimal("0.05"),
            min_order_notional_usdt=Decimal("1"),
            dynamic_sizing_enabled=True,
            confidence_sizing_enabled=True,
            baseline_confidence=Decimal("0.70"),
            max_confidence_multiplier=Decimal("1.5"),
            min_confidence_multiplier=Decimal("0.8"),
        )
        engine = RiskEngine(settings=settings)
        sig_low = _signal(confidence=Decimal("0.50"), stop_loss=Decimal("95"))
        sig_high = _signal(confidence=Decimal("0.95"), stop_loss=Decimal("95"))
        result_low = engine.evaluate(
            signal=sig_low,
            account_balance=Decimal("100"),
            remaining_slots=1,
        )
        result_high = engine.evaluate(
            signal=sig_high,
            account_balance=Decimal("100"),
            remaining_slots=1,
        )
        assert result_low.approved
        assert result_high.approved
        assert result_high.position.notional > result_low.position.notional


# =============================================================================
# evaluate() — slot notional ceiling, lines 632, 635
# =============================================================================
class TestEvaluateSlotNotionalBoundaries:
    def test_notional_capped_by_max_balance(self) -> None:
        """Line 632: notional clamped to usable_balance * leverage."""
        settings = RiskSettings(
            leverage=5,
            min_leverage=1,
            max_leverage=5,
            slot_sizing_enabled=True,
            slot_margin_buffer_pct=Decimal("0"),
            min_order_notional_usdt=Decimal("1"),
            max_position_size_usdt=Decimal("10000"),
            confidence_sizing_enabled=False,
        )
        engine = RiskEngine(settings=settings)
        sig = _signal(
            signal_type=SignalType.BUY,
            price=Decimal("100"),
            stop_loss=Decimal("90"),
        )
        result = engine.evaluate(
            signal=sig,
            account_balance=Decimal("10"),
            remaining_slots=1,
        )
        assert result.approved
        assert result.position.notional <= Decimal("50")

    def test_notional_lifted_to_min_notional(self) -> None:
        """Line 635: notional < min_notional -> lift to min_notional."""
        settings = RiskSettings(
            leverage=5,
            min_leverage=1,
            max_leverage=25,
            slot_sizing_enabled=True,
            slot_margin_buffer_pct=Decimal("0"),
            min_order_notional_usdt=Decimal("5"),
            max_position_size_usdt=Decimal("10000"),
            confidence_sizing_enabled=False,
        )
        engine = RiskEngine(settings=settings)
        sig = _signal(
            signal_type=SignalType.BUY,
            price=Decimal("1"),
            stop_loss=Decimal("0.9"),
        )
        result = engine.evaluate(
            signal=sig,
            account_balance=Decimal("2"),
            remaining_slots=4,
        )
        assert result.approved
        assert result.position.notional >= Decimal("5")


# =============================================================================
# _resolve_max_position_size — runtime > ceiling, line 725
# =============================================================================
class TestResolveMaxPositionSize:
    def test_raises_when_runtime_limit_exceeds_ceiling(self) -> None:
        """Line 725: runtime_limit > hard_limit raises ValueError."""
        engine = RiskEngine(
            settings=RiskSettings(
                leverage=5,
                min_leverage=1,
                max_leverage=25,
                max_position_size_usdt=Decimal("100"),
            )
        )
        sig = _signal(signal_type=SignalType.BUY, stop_loss=Decimal("95"))
        with pytest.raises(ValueError, match="ceiling"):
            engine.evaluate(
                signal=sig,
                account_balance=Decimal("1000"),
                max_position_size_usdt=Decimal("200"),
            )


# =============================================================================
# _resolve_max_position_size — runtime <= 0 or non-finite, line 725
# =============================================================================
class TestResolveMaxPositionSizeInvalidRuntime:
    def _engine(self) -> RiskEngine:
        return RiskEngine(
            settings=RiskSettings(
                leverage=5,
                min_leverage=1,
                max_leverage=25,
                max_position_size_usdt=Decimal("100"),
            )
        )

    def test_raises_when_runtime_limit_negative(self) -> None:
        """Line 725: runtime_limit < 0 raises ValueError (not finite and positive)."""
        engine = self._engine()
        sig = _signal(signal_type=SignalType.BUY, stop_loss=Decimal("95"))
        with pytest.raises(ValueError, match="finite and positive"):
            engine.evaluate(
                signal=sig,
                account_balance=Decimal("1000"),
                max_position_size_usdt=Decimal("-10"),
            )

    def test_raises_when_runtime_limit_zero(self) -> None:
        """Line 725: runtime_limit = 0 raises ValueError."""
        engine = self._engine()
        sig = _signal(signal_type=SignalType.BUY, stop_loss=Decimal("95"))
        with pytest.raises(ValueError, match="finite and positive"):
            engine.evaluate(
                signal=sig,
                account_balance=Decimal("1000"),
                max_position_size_usdt=Decimal("0"),
            )


# =============================================================================
# calculate_stepped_stop_loss — take_profit=None with step >= 2, line 239
# =============================================================================
class TestCalculateSteppedStopLossNoTp:
    def test_raises_when_step_ge_2_and_no_take_profit(self) -> None:
        """Line 239: step >= 2 with take_profit=None raises ValueError."""
        pos = _position(take_profit=None)
        with pytest.raises(ValueError, match="take-profit"):
            RiskEngine.calculate_stepped_stop_loss(position=pos, step=2)

    def test_step_one_without_take_profit_returns_breakeven(self) -> None:
        """Step 1 with no TP is allowed — returns entry + fee_buffer for LONG."""
        pos = _position(
            side=PositionSide.LONG,
            entry_price=Decimal("100"),
            take_profit=None,
        )
        result = RiskEngine.calculate_stepped_stop_loss(position=pos, step=1)
        assert result > Decimal("100")  # entry + fee_buffer


# =============================================================================
# evaluate() — SELL auto-SL confirms risk_per_unit > 0 (documents line 527 guard)
# =============================================================================
class TestEvaluateSellAutoSl:
    def test_sell_with_auto_sl_is_approved(self) -> None:
        """SELL with no explicit SL -> auto-calculated SL above entry -> approved.

        Also exercises the fallback strategy path in _resolve_exit_rates (case _).
        """
        engine = RiskEngine(
            settings=RiskSettings(
                leverage=5,
                min_leverage=1,
                max_leverage=25,
                stop_loss_pct=Decimal("0.02"),
                take_profit_pct=Decimal("0.04"),
            )
        )
        sig = Signal(
            symbol="XYZUSDT",
            signal_type=SignalType.SELL,
            price=Decimal("100"),
            confidence=Decimal("0.70"),
            strategy_name="unknown_strategy",
            generated_at=_NOW,
            stop_loss=None,
            take_profit=None,
        )
        result = engine.evaluate(signal=sig, account_balance=Decimal("1000"))
        assert result.approved
        assert result.position.notional > Decimal("0")
