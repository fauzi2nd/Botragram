"""
Botragram

Description:
    Risk management rules settings model.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, TrailingMode

__all__ = [
    "RiskSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class RiskSettings:
    """Settings controlling order sizing and risk limits."""

    # Position
    max_position_size_usdt: Decimal = Decimal("1000")
    max_open_positions: int = 1
    leverage: int = 1

    # Risk
    risk_per_trade_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.10")
    max_executable_quote_age_ms: int = 1_000
    max_spread_bps: Decimal = Decimal("20")

    # Exit - Category Specific Defaults
    scalping_stop_loss_pct: Decimal = Decimal("0.005")
    scalping_take_profit_pct: Decimal = Decimal("0.01")
    trend_stop_loss_pct: Decimal = Decimal("0.015")
    trend_take_profit_pct: Decimal = Decimal("0.03")
    swing_stop_loss_pct: Decimal = Decimal("0.025")
    swing_take_profit_pct: Decimal = Decimal("0.05")

    # Global / Fallback exits
    stop_loss_pct: Decimal = Decimal("0.02")
    take_profit_pct: Decimal = Decimal("0.04")

    # Legacy alias exits (retained for backward compatibility)
    ema_scalping_stop_loss_pct: Decimal = Decimal("0.005")
    ema_scalping_take_profit_pct: Decimal = Decimal("0.01")
    ema_cross_stop_loss_pct: Decimal = Decimal("0.02")
    ema_cross_take_profit_pct: Decimal = Decimal("0.04")

    # PIER (Price Action) Exits & Sizing Overrides
    pier_stop_loss_pct: Decimal = Decimal("0.012")
    pier_take_profit_pct: Decimal = Decimal("0.024")
    pier_leverage: int | None = None
    pier_max_position_size_usdt: Decimal | None = None
    pier_risk_per_trade_pct: Decimal | None = None
    pier_trailing_mode: TrailingMode | None = None
    pier_trailing_swing_timeframe: Interval | None = None
    pier_trailing_swing_window: int | None = None
    pier_trailing_buffer_pct: Decimal | None = None
    pier_partial_tp_enabled: bool | None = None
    pier_partial_tp_ratio: Decimal | None = None
    pier_partial_tp_trigger_progress: Decimal | None = None
    pier_enable_early_position_exit: bool | None = None
    pier_early_exit_min_confidence: float | None = None
    pier_early_exit_check_candlestick_reversal: bool | None = None
    pier_early_exit_check_opposite_signal: bool | None = None
    pier_early_exit_check_exhaustion: bool | None = None

    # Botragram Origin Exits
    origin_stop_loss_pct: Decimal = Decimal("0.030")
    origin_take_profit_pct: Decimal = Decimal("0.045")

    # Stepped Position Protection
    stepped_stop_enabled: bool = True
    stepped_stop_thresholds: tuple[Decimal, ...] = (
        Decimal("0.30"),
        Decimal("0.45"),
        Decimal("0.60"),
        Decimal("0.75"),
        Decimal("0.90"),
    )
    stepped_stop_locked_lag: Decimal = Decimal("0.20")
    breakeven_roi_threshold: Decimal = Decimal("0.30")
    breakeven_progress_threshold: Decimal = Decimal("0.35")
    breakeven_fee_buffer: Decimal = Decimal("0.0016")
    trailing_mode: TrailingMode = TrailingMode.SWING_PIVOT
    trailing_swing_timeframe: Interval = Interval.M5
    trailing_swing_window: int = 5
    trailing_buffer_pct: Decimal = Decimal("0.0015")

    # Partial Take Profit
    partial_tp_enabled: bool = False
    partial_tp_ratio: Decimal = Decimal("0.50")
    partial_tp_trigger_progress: Decimal = Decimal("0.50")

    # Early In-Flight Position Exit
    enable_early_position_exit: bool = False
    early_exit_min_confidence: float = 0.75
    early_exit_check_candlestick_reversal: bool = True
    early_exit_check_opposite_signal: bool = True
    early_exit_check_exhaustion: bool = True

    # Volatility Sizing
    volatility_sizing_enabled: bool = False
    baseline_volatility_pct: Decimal = Decimal("0.02")

    # Smart Dynamic Sizing & Adaptive Leverage
    dynamic_sizing_enabled: bool = False
    confidence_sizing_enabled: bool = True
    baseline_confidence: Decimal = Decimal("0.70")
    max_confidence_multiplier: Decimal = Decimal("1.5")
    min_confidence_multiplier: Decimal = Decimal("0.8")
    dynamic_leverage_enabled: bool = False
    min_leverage: int = 5
    max_leverage: int = 25

    # Dynamic Slot-Based Margin Allocation
    slot_sizing_enabled: bool = False
    slot_margin_buffer_pct: Decimal = Decimal("0.05")
    min_order_notional_usdt: Decimal = Decimal("5.0")

    def __post_init__(self) -> None:
        """Validate global and strategy-specific risk ratios."""
        ratios = (
            ("risk_per_trade_pct", self.risk_per_trade_pct),
            ("max_drawdown_pct", self.max_drawdown_pct),
            ("scalping_stop_loss_pct", self.scalping_stop_loss_pct),
            ("scalping_take_profit_pct", self.scalping_take_profit_pct),
            ("trend_stop_loss_pct", self.trend_stop_loss_pct),
            ("trend_take_profit_pct", self.trend_take_profit_pct),
            ("swing_stop_loss_pct", self.swing_stop_loss_pct),
            ("swing_take_profit_pct", self.swing_take_profit_pct),
            ("stop_loss_pct", self.stop_loss_pct),
            ("take_profit_pct", self.take_profit_pct),
            ("ema_scalping_stop_loss_pct", self.ema_scalping_stop_loss_pct),
            ("ema_scalping_take_profit_pct", self.ema_scalping_take_profit_pct),
            ("ema_cross_stop_loss_pct", self.ema_cross_stop_loss_pct),
            ("ema_cross_take_profit_pct", self.ema_cross_take_profit_pct),
            ("pier_stop_loss_pct", self.pier_stop_loss_pct),
            ("pier_take_profit_pct", self.pier_take_profit_pct),
            ("origin_stop_loss_pct", self.origin_stop_loss_pct),
            ("origin_take_profit_pct", self.origin_take_profit_pct),
        )

        for name, value in ratios:
            if not value.is_finite():
                raise ValueError(f"Risk setting {name!r} must be finite")

            if not Decimal("0") < value < Decimal("1"):
                raise ValueError(f"Risk setting {name!r} must be between zero and one")

        if self.leverage <= 0:
            raise ValueError("Risk leverage must be greater than zero")

        if self.pier_leverage is not None and self.pier_leverage <= 0:
            raise ValueError("PIER risk leverage must be greater than zero")

        if self.pier_max_position_size_usdt is not None and (
            not self.pier_max_position_size_usdt.is_finite()
            or self.pier_max_position_size_usdt <= Decimal("0")
        ):
            raise ValueError("PIER max position size must be greater than zero")

        if self.pier_risk_per_trade_pct is not None and (
            not self.pier_risk_per_trade_pct.is_finite()
            or not Decimal("0") < self.pier_risk_per_trade_pct < Decimal("1")
        ):
            raise ValueError(
                "PIER risk per trade must be between zero and one exclusive"
            )

        if (
            self.pier_trailing_swing_window is not None
            and self.pier_trailing_swing_window < 3
        ):
            raise ValueError("PIER trailing swing window must be at least 3")

        if self.pier_trailing_buffer_pct is not None and (
            not self.pier_trailing_buffer_pct.is_finite()
            or self.pier_trailing_buffer_pct < Decimal("0")
        ):
            raise ValueError("PIER trailing buffer must be non-negative")

        if self.pier_partial_tp_ratio is not None and (
            not self.pier_partial_tp_ratio.is_finite()
            or not Decimal("0") < self.pier_partial_tp_ratio < Decimal("1")
        ):
            raise ValueError(
                "PIER partial TP ratio must be between zero and one exclusive"
            )

        if self.pier_partial_tp_trigger_progress is not None and (
            not self.pier_partial_tp_trigger_progress.is_finite()
            or not Decimal("0") < self.pier_partial_tp_trigger_progress < Decimal("1")
        ):
            raise ValueError(
                "PIER partial TP trigger progress must be between 0 and 1 exclusive"
            )

        if self.pier_early_exit_min_confidence is not None and not (
            0.0 <= self.pier_early_exit_min_confidence <= 1.0
        ):
            raise ValueError(
                "PIER early exit min confidence must be between 0 and 1 inclusive"
            )

        if self.max_executable_quote_age_ms <= 0:
            raise ValueError("Maximum executable quote age must be greater than zero")

        if not self.max_spread_bps.is_finite() or self.max_spread_bps <= Decimal("0"):
            raise ValueError("Maximum spread must be greater than zero")

        if isinstance(self.max_open_positions, bool) or self.max_open_positions <= 0:
            raise ValueError("Maximum open positions must be greater than zero")

        if self.max_position_size_usdt <= 0:
            raise ValueError("Maximum position size must be greater than zero")

        if self.take_profit_pct <= self.stop_loss_pct:
            raise ValueError("Global take-profit must exceed global stop-loss")

        if self.scalping_take_profit_pct <= self.scalping_stop_loss_pct:
            raise ValueError("Scalping take-profit must exceed scalping stop-loss")

        if self.trend_take_profit_pct <= self.trend_stop_loss_pct:
            raise ValueError("Trend take-profit must exceed trend stop-loss")

        if self.swing_take_profit_pct <= self.swing_stop_loss_pct:
            raise ValueError("Swing take-profit must exceed swing stop-loss")

        if self.ema_scalping_take_profit_pct <= self.ema_scalping_stop_loss_pct:
            raise ValueError(
                "EMA scalping take-profit must exceed EMA scalping stop-loss"
            )

        if self.ema_cross_take_profit_pct <= self.ema_cross_stop_loss_pct:
            raise ValueError("EMA cross take-profit must exceed EMA cross stop-loss")

        if self.pier_take_profit_pct <= self.pier_stop_loss_pct:
            raise ValueError("PIER take-profit must exceed PIER stop-loss")

        if (
            not self.breakeven_roi_threshold.is_finite()
            or self.breakeven_roi_threshold <= Decimal("0")
        ):
            raise ValueError("breakeven_roi_threshold must be positive and finite")

        if not self.breakeven_progress_threshold.is_finite() or not (
            Decimal("0") < self.breakeven_progress_threshold < Decimal("1")
        ):
            raise ValueError(
                "breakeven_progress_threshold must be strictly between 0 and 1"
            )

        if (
            not self.breakeven_fee_buffer.is_finite()
            or self.breakeven_fee_buffer < Decimal("0")
            or self.breakeven_fee_buffer >= Decimal("0.05")
        ):
            raise ValueError("breakeven_fee_buffer must be in [0, 0.05)")

        if self.trailing_swing_window < 3:
            raise ValueError("trailing_swing_window must be at least 3")

        if not self.trailing_buffer_pct.is_finite() or not (
            Decimal("0") <= self.trailing_buffer_pct < Decimal("0.05")
        ):
            raise ValueError("trailing_buffer_pct must be in [0, 0.05)")

        if not self.stepped_stop_thresholds:
            raise ValueError("stepped_stop_thresholds cannot be empty")

        prev_threshold = Decimal("0")
        for threshold in self.stepped_stop_thresholds:
            if not threshold.is_finite() or not (
                Decimal("0") < threshold < Decimal("1")
            ):
                raise ValueError(
                    "Each stepped_stop_threshold must be strictly between 0 and 1"
                )
            if threshold <= prev_threshold:
                raise ValueError("stepped_stop_thresholds must be strictly increasing")
            prev_threshold = threshold

        if not self.stepped_stop_locked_lag.is_finite() or not (
            Decimal("0")
            < self.stepped_stop_locked_lag
            < self.stepped_stop_thresholds[0]
        ):
            raise ValueError(
                "stepped_stop_locked_lag must be positive, finite, and strictly "
                "less than the first stepped stop threshold"
            )

        if self.partial_tp_enabled:
            if not self.partial_tp_ratio.is_finite() or not (
                Decimal("0") < self.partial_tp_ratio < Decimal("1")
            ):
                raise ValueError(
                    "Partial take-profit ratio must be strictly between 0 and 1"
                )
            if not self.partial_tp_trigger_progress.is_finite() or not (
                Decimal("0") < self.partial_tp_trigger_progress < Decimal("1")
            ):
                raise ValueError(
                    "Partial take-profit trigger progress must be "
                    "strictly between 0 and 1"
                )

        if self.volatility_sizing_enabled:
            if not self.baseline_volatility_pct.is_finite() or not (
                Decimal("0") < self.baseline_volatility_pct < Decimal("1")
            ):
                raise ValueError(
                    "Baseline volatility percentage must be strictly between 0 and 1"
                )

        if not (0.0 <= self.early_exit_min_confidence <= 1.0):
            raise ValueError(
                "Early exit minimum confidence must be between 0.0 and 1.0"
            )

        if not (Decimal("0") < self.baseline_confidence <= Decimal("1")):
            raise ValueError("baseline_confidence must be between 0 and 1")
        if self.min_confidence_multiplier <= Decimal(
            "0"
        ) or self.max_confidence_multiplier <= Decimal("0"):
            raise ValueError("Confidence multipliers must be positive")
        if self.min_confidence_multiplier > self.max_confidence_multiplier:
            raise ValueError(
                "min_confidence_multiplier cannot exceed max_confidence_multiplier"
            )
        if self.min_leverage <= 0 or self.max_leverage <= 0:
            raise ValueError("Leverage bounds must be positive")
        if self.min_leverage > self.max_leverage:
            raise ValueError("min_leverage cannot exceed max_leverage")
        if not (
            self.slot_margin_buffer_pct.is_finite()
            and Decimal("0") <= self.slot_margin_buffer_pct < Decimal("1")
        ):
            raise ValueError("slot_margin_buffer_pct must be in [0, 1)")
        if not (
            self.min_order_notional_usdt.is_finite()
            and self.min_order_notional_usdt > Decimal("0")
        ):
            raise ValueError("min_order_notional_usdt must be positive")
