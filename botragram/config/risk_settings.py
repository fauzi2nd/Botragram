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

    # Exit
    stop_loss_pct: Decimal = Decimal("0.02")
    take_profit_pct: Decimal = Decimal("0.04")

    # EMA scalping exits
    ema_scalping_stop_loss_pct: Decimal = Decimal("0.005")
    ema_scalping_take_profit_pct: Decimal = Decimal("0.01")

    # EMA cross exits
    ema_cross_stop_loss_pct: Decimal = Decimal("0.02")
    ema_cross_take_profit_pct: Decimal = Decimal("0.04")

    def __post_init__(self) -> None:
        """Validate global and strategy-specific risk ratios."""
        ratios = (
            ("risk_per_trade_pct", self.risk_per_trade_pct),
            ("max_drawdown_pct", self.max_drawdown_pct),
            ("stop_loss_pct", self.stop_loss_pct),
            ("take_profit_pct", self.take_profit_pct),
            ("ema_scalping_stop_loss_pct", self.ema_scalping_stop_loss_pct),
            ("ema_scalping_take_profit_pct", self.ema_scalping_take_profit_pct),
            ("ema_cross_stop_loss_pct", self.ema_cross_stop_loss_pct),
            ("ema_cross_take_profit_pct", self.ema_cross_take_profit_pct),
        )

        for name, value in ratios:
            if not value.is_finite():
                raise ValueError(f"Risk setting {name!r} must be finite")

            if not Decimal("0") < value < Decimal("1"):
                raise ValueError(f"Risk setting {name!r} must be between zero and one")

        if self.leverage <= 0:
            raise ValueError("Risk leverage must be greater than zero")

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

        if self.ema_scalping_take_profit_pct <= self.ema_scalping_stop_loss_pct:
            raise ValueError(
                "EMA scalping take-profit must exceed EMA scalping stop-loss"
            )

        if self.ema_cross_take_profit_pct <= self.ema_cross_stop_loss_pct:
            raise ValueError("EMA cross take-profit must exceed EMA cross stop-loss")
