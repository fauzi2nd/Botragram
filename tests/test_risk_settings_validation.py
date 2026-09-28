"""
Botragram

Description:
    Coverage gap tests for RiskSettings __post_init__ validation paths
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
from decimal import Decimal

# =============================================================================
# Third Party
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings


# =============================================================================
# Helpers
# =============================================================================
def _valid_base() -> dict[str, object]:
    """Return a minimal valid RiskSettings kwargs dict."""
    return {
        "leverage": 5,
        "min_leverage": 1,
        "max_leverage": 25,
    }


def _make(**overrides: object) -> RiskSettings:
    base = _valid_base()
    base.update(overrides)
    return RiskSettings(**base)  # type: ignore[arg-type]


# =============================================================================
# leverage validations — lines 173, 177
# =============================================================================
class TestLeverageValidation:
    def test_raises_for_zero_leverage(self) -> None:
        """Line 173: leverage = 0 raises ValueError."""
        with pytest.raises(ValueError, match="leverage must be greater than zero"):
            _make(leverage=0)

    def test_raises_for_negative_leverage(self) -> None:
        """Line 173: leverage < 0 raises ValueError."""
        with pytest.raises(ValueError, match="leverage must be greater than zero"):
            _make(leverage=-1)

    def test_raises_for_zero_pier_leverage(self) -> None:
        """Line 177: pier_leverage = 0 raises ValueError."""
        with pytest.raises(ValueError, match="PIER risk leverage"):
            _make(pier_leverage=0)


# =============================================================================
# PIER optional field validations — lines 183, 189, 197, 203, 209, 217
# =============================================================================
class TestPierOptionalValidation:
    def test_raises_for_zero_pier_max_position_size(self) -> None:
        """Line 183: pier_max_position_size_usdt = 0 raises ValueError."""
        with pytest.raises(ValueError, match="PIER max position size"):
            _make(pier_max_position_size_usdt=Decimal("0"))

    def test_raises_for_negative_pier_max_position_size(self) -> None:
        """Line 183: pier_max_position_size_usdt < 0 raises ValueError."""
        with pytest.raises(ValueError, match="PIER max position size"):
            _make(pier_max_position_size_usdt=Decimal("-1"))

    def test_raises_for_invalid_pier_risk_per_trade_pct(self) -> None:
        """Line 189: pier_risk_per_trade_pct = 0 raises ValueError."""
        with pytest.raises(ValueError, match="PIER risk per trade"):
            _make(pier_risk_per_trade_pct=Decimal("0"))

    def test_raises_for_pier_risk_per_trade_pct_above_one(self) -> None:
        """Line 189: pier_risk_per_trade_pct >= 1 raises ValueError."""
        with pytest.raises(ValueError, match="PIER risk per trade"):
            _make(pier_risk_per_trade_pct=Decimal("1"))

    def test_raises_for_pier_trailing_swing_window_too_small(self) -> None:
        """Line 197: pier_trailing_swing_window < 3 raises ValueError."""
        with pytest.raises(ValueError, match="PIER trailing swing window"):
            _make(pier_trailing_swing_window=2)

    def test_raises_for_negative_pier_trailing_buffer_pct(self) -> None:
        """Line 203: pier_trailing_buffer_pct < 0 raises ValueError."""
        with pytest.raises(ValueError, match="PIER trailing buffer"):
            _make(pier_trailing_buffer_pct=Decimal("-0.001"))

    def test_raises_for_invalid_pier_partial_tp_ratio(self) -> None:
        """Line 209: pier_partial_tp_ratio = 0 raises ValueError."""
        with pytest.raises(ValueError, match="PIER partial TP ratio"):
            _make(pier_partial_tp_ratio=Decimal("0"))

    def test_raises_for_invalid_pier_partial_tp_trigger_progress(self) -> None:
        """Line 217: pier_partial_tp_trigger_progress = 1 raises ValueError."""
        with pytest.raises(ValueError, match="PIER partial TP trigger progress"):
            _make(pier_partial_tp_trigger_progress=Decimal("1"))

    def test_raises_for_pier_early_exit_confidence_above_one(self) -> None:
        """Line 224: pier_early_exit_min_confidence > 1 raises ValueError."""
        with pytest.raises(ValueError, match="PIER early exit min confidence"):
            _make(pier_early_exit_min_confidence=1.5)


# =============================================================================
# Global field validations — lines 229, 238
# =============================================================================
class TestGlobalFieldValidation:
    def test_raises_for_zero_max_executable_quote_age_ms(self) -> None:
        """Line 229: max_executable_quote_age_ms = 0 raises ValueError."""
        with pytest.raises(ValueError, match="Maximum executable quote age"):
            _make(max_executable_quote_age_ms=0)

    def test_raises_for_zero_max_position_size_usdt(self) -> None:
        """Line 238: max_position_size_usdt = 0 raises ValueError."""
        with pytest.raises(ValueError, match="Maximum position size"):
            _make(max_position_size_usdt=Decimal("0"))

    def test_raises_for_zero_max_open_positions(self) -> None:
        """Line ~235: max_open_positions = 0 raises ValueError."""
        with pytest.raises(ValueError, match="Maximum open positions"):
            _make(max_open_positions=0)


# =============================================================================
# TP must exceed SL — lines 241, 244, 247, 250, 253, 261
# =============================================================================
class TestTpMustExceedSl:
    def test_raises_when_global_tp_le_sl(self) -> None:
        """Line 241: take_profit_pct <= stop_loss_pct."""
        with pytest.raises(ValueError, match="Global take-profit"):
            _make(stop_loss_pct=Decimal("0.03"), take_profit_pct=Decimal("0.02"))

    def test_raises_when_scalping_tp_le_sl(self) -> None:
        """Line 244: scalping_take_profit_pct <= scalping_stop_loss_pct."""
        with pytest.raises(ValueError, match="Scalping take-profit"):
            _make(
                scalping_stop_loss_pct=Decimal("0.01"),
                scalping_take_profit_pct=Decimal("0.005"),
            )

    def test_raises_when_trend_tp_le_sl(self) -> None:
        """Line 247: trend_take_profit_pct <= trend_stop_loss_pct."""
        with pytest.raises(ValueError, match="Trend take-profit"):
            _make(
                trend_stop_loss_pct=Decimal("0.03"),
                trend_take_profit_pct=Decimal("0.015"),
            )

    def test_raises_when_swing_tp_le_sl(self) -> None:
        """Line 250: swing_take_profit_pct <= swing_stop_loss_pct."""
        with pytest.raises(ValueError, match="Swing take-profit"):
            _make(
                swing_stop_loss_pct=Decimal("0.05"),
                swing_take_profit_pct=Decimal("0.025"),
            )

    def test_raises_when_ema_scalping_tp_le_sl(self) -> None:
        """Line 253: ema_scalping_take_profit_pct <= ema_scalping_stop_loss_pct."""
        with pytest.raises(ValueError, match="EMA scalping take-profit"):
            _make(
                ema_scalping_stop_loss_pct=Decimal("0.01"),
                ema_scalping_take_profit_pct=Decimal("0.005"),
            )

    def test_raises_when_ema_cross_tp_le_sl(self) -> None:
        """Line ~258: ema_cross_take_profit_pct <= ema_cross_stop_loss_pct."""
        with pytest.raises(ValueError, match="EMA cross take-profit"):
            _make(
                ema_cross_stop_loss_pct=Decimal("0.04"),
                ema_cross_take_profit_pct=Decimal("0.02"),
            )

    def test_raises_when_pier_tp_le_sl(self) -> None:
        """Line 261: pier_take_profit_pct <= pier_stop_loss_pct."""
        with pytest.raises(ValueError, match="PIER take-profit"):
            _make(
                pier_stop_loss_pct=Decimal("0.024"),
                pier_take_profit_pct=Decimal("0.012"),
            )


# =============================================================================
# Breakeven / trailing validations — lines 272, 284, 289
# =============================================================================
class TestBreakevenTrailingValidation:
    def test_raises_for_zero_breakeven_progress_threshold(self) -> None:
        """Line 272: breakeven_progress_threshold = 0 raises ValueError."""
        with pytest.raises(ValueError, match="breakeven_progress_threshold"):
            _make(breakeven_progress_threshold=Decimal("0"))

    def test_raises_for_trailing_swing_window_too_small(self) -> None:
        """Line 284: trailing_swing_window < 3 raises ValueError."""
        with pytest.raises(ValueError, match="trailing_swing_window"):
            _make(trailing_swing_window=2)

    def test_raises_for_trailing_buffer_pct_negative(self) -> None:
        """Line 289: trailing_buffer_pct < 0 raises ValueError."""
        with pytest.raises(ValueError, match="trailing_buffer_pct"):
            _make(trailing_buffer_pct=Decimal("-0.001"))

    def test_raises_for_trailing_buffer_pct_too_large(self) -> None:
        """Line 289: trailing_buffer_pct >= 0.05 raises ValueError."""
        with pytest.raises(ValueError, match="trailing_buffer_pct"):
            _make(trailing_buffer_pct=Decimal("0.05"))


# =============================================================================
# partial_tp_enabled validations — lines 320, 326
# =============================================================================
class TestPartialTpValidation:
    def test_raises_for_invalid_partial_tp_ratio_when_enabled(self) -> None:
        """Line 320: partial_tp_enabled=True, ratio=0 raises ValueError."""
        with pytest.raises(ValueError, match="Partial take-profit ratio"):
            _make(partial_tp_enabled=True, partial_tp_ratio=Decimal("0"))

    def test_raises_for_invalid_partial_tp_trigger_progress_when_enabled(self) -> None:
        """Line 326: partial_tp_enabled=True, trigger_progress=1 raises ValueError."""
        with pytest.raises(ValueError, match="Partial take-profit trigger progress"):
            _make(
                partial_tp_enabled=True,
                partial_tp_trigger_progress=Decimal("1"),
            )


# =============================================================================
# volatility_sizing_enabled validation — line 340
# =============================================================================
class TestVolatilitySizingValidation:
    def test_raises_for_invalid_baseline_volatility_when_enabled(self) -> None:
        """Line 340: volatility_sizing_enabled=True, baseline=0 raises ValueError."""
        with pytest.raises(ValueError, match="Baseline volatility"):
            _make(
                volatility_sizing_enabled=True,
                baseline_volatility_pct=Decimal("0"),
            )


# =============================================================================
# early_exit_min_confidence validation — line 340 (line ~339)
# =============================================================================
class TestEarlyExitConfidenceValidation:
    def test_raises_for_early_exit_confidence_above_one(self) -> None:
        """Line ~339: early_exit_min_confidence > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="Early exit minimum confidence"):
            _make(early_exit_min_confidence=1.1)

    def test_raises_for_early_exit_confidence_negative(self) -> None:
        """Line ~339: early_exit_min_confidence < 0 raises ValueError."""
        with pytest.raises(ValueError, match="Early exit minimum confidence"):
            _make(early_exit_min_confidence=-0.1)


# =============================================================================
# slot/leverage bounds validations — lines 362, 367
# =============================================================================
class TestSlotAndLeverageBoundsValidation:
    def test_raises_for_slot_margin_buffer_pct_equal_one(self) -> None:
        """Line 362: slot_margin_buffer_pct = 1 raises ValueError."""
        with pytest.raises(ValueError, match="slot_margin_buffer_pct"):
            _make(slot_margin_buffer_pct=Decimal("1"))

    def test_raises_for_slot_margin_buffer_pct_negative(self) -> None:
        """Line 362: slot_margin_buffer_pct < 0 raises ValueError."""
        with pytest.raises(ValueError, match="slot_margin_buffer_pct"):
            _make(slot_margin_buffer_pct=Decimal("-0.01"))

    def test_raises_for_zero_min_order_notional(self) -> None:
        """Line 367: min_order_notional_usdt = 0 raises ValueError."""
        with pytest.raises(ValueError, match="min_order_notional_usdt"):
            _make(min_order_notional_usdt=Decimal("0"))

    def test_raises_when_min_leverage_exceeds_max_leverage(self) -> None:
        """Line ~357: min_leverage > max_leverage raises ValueError."""
        with pytest.raises(ValueError, match="min_leverage cannot exceed"):
            _make(min_leverage=20, max_leverage=10)

    def test_raises_for_zero_min_leverage(self) -> None:
        """Line ~354: min_leverage = 0 raises ValueError."""
        with pytest.raises(ValueError, match="Leverage bounds"):
            _make(min_leverage=0)
