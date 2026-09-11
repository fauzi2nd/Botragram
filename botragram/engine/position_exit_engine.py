"""
Botragram

Description:
    In-flight trading position exit and invalidation decision engine.

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
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    PositionExitAction,
    PositionSide,
    SignalType,
)
from botragram.indicators.price_action.candlesticks import (
    detect_engulfing,
    detect_pinbar,
)
from botragram.models import (
    Candle,
    Position,
    PositionExitDecision,
    Signal,
)

__all__ = [
    "PositionExitEngine",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_MIN_CONFIDENCE: Final[float] = 0.75


# =============================================================================
# Engine Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PositionExitEngine:
    """Evaluate in-flight positions upon candle close for early setup invalidation."""

    enabled: bool = False
    min_confidence: float = _DEFAULT_MIN_CONFIDENCE
    check_candlestick_reversal: bool = True
    check_opposite_signal: bool = True

    def evaluate(
        self,
        *,
        position: Position,
        candles: Sequence[Candle],
        strategy_signal: Signal | None = None,
    ) -> PositionExitDecision:
        """Evaluate an open position for early exit invalidation.

        Args:
            position: Authoritative open position snapshot.
            candles: Sequence of closed candles for the position symbol.
            strategy_signal: Optional fresh signal generated for this candle close.

        Returns:
            PositionExitDecision declaring HOLD or EARLY_CUT_LOSS with rationale.
        """
        current_price = position.current_price
        unrealized_pnl = position.unrealized_pnl

        if not self.enabled:
            return PositionExitDecision(
                action=PositionExitAction.HOLD,
                symbol=position.symbol,
                reason="Early position exit monitoring disabled",
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
            )

        if position.quantity <= _DECIMAL_ZERO:
            return PositionExitDecision(
                action=PositionExitAction.HOLD,
                symbol=position.symbol,
                reason="Position quantity is zero",
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
            )

        # Do not cut loss if the position is already in floating profit.
        # Stateful stepped stop or partial take-profit manages profitable positions.
        if self._is_in_profit(position=position):
            return PositionExitDecision(
                action=PositionExitAction.HOLD,
                symbol=position.symbol,
                reason="Position is in floating profit; protected by trailing ladder",
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
            )

        # Check 1: Confirmed opposite strategy signal
        if self.check_opposite_signal and strategy_signal is not None:
            opposite_decision = self._check_opposite_signal(
                position=position,
                signal=strategy_signal,
            )
            if opposite_decision is not None:
                return opposite_decision

        # Check 2: Counter-trend candlestick reversal pattern on closed candle
        if self.check_candlestick_reversal and len(candles) >= 2:
            reversal_decision = self._check_candlestick_reversal(
                position=position,
                prev_candle=candles[-2],
                curr_candle=candles[-1],
            )
            if reversal_decision is not None:
                return reversal_decision

        return PositionExitDecision(
            action=PositionExitAction.HOLD,
            symbol=position.symbol,
            reason="No invalidation criteria met",
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
        )

    def _is_in_profit(self, *, position: Position) -> bool:
        """Return True when position is currently in profit."""
        if (
            position.entry_price <= _DECIMAL_ZERO
            or position.current_price <= _DECIMAL_ZERO
        ):
            return False

        if position.side is PositionSide.LONG:
            return position.current_price > position.entry_price

        if position.side is PositionSide.SHORT:
            return position.current_price < position.entry_price

        return False

    def _check_opposite_signal(
        self,
        *,
        position: Position,
        signal: Signal,
    ) -> PositionExitDecision | None:
        """Evaluate whether a strategy signal invalidates the current position."""
        if signal.confidence < Decimal(str(self.min_confidence)):
            return None

        confidence_val = float(signal.confidence)

        # Long position invalidated by SELL or CLOSE_LONG
        if position.side is PositionSide.LONG and signal.signal_type in (
            SignalType.SELL,
            SignalType.CLOSE_LONG,
        ):
            return PositionExitDecision(
                action=PositionExitAction.EARLY_CUT_LOSS,
                symbol=position.symbol,
                reason=(
                    f"Opposite strategy signal generated: {signal.signal_type.value} "
                    f"(confidence={signal.confidence:.2f})"
                ),
                confidence=confidence_val,
                trigger_price=position.current_price,
                current_price=position.current_price,
                unrealized_pnl=position.unrealized_pnl,
            )

        # Short position invalidated by BUY or CLOSE_SHORT
        if position.side is PositionSide.SHORT and signal.signal_type in (
            SignalType.BUY,
            SignalType.CLOSE_SHORT,
        ):
            return PositionExitDecision(
                action=PositionExitAction.EARLY_CUT_LOSS,
                symbol=position.symbol,
                reason=(
                    f"Opposite strategy signal generated: {signal.signal_type.value} "
                    f"(confidence={signal.confidence:.2f})"
                ),
                confidence=confidence_val,
                trigger_price=position.current_price,
                current_price=position.current_price,
                unrealized_pnl=position.unrealized_pnl,
            )

        return None

    def _check_candlestick_reversal(
        self,
        *,
        position: Position,
        prev_candle: Candle,
        curr_candle: Candle,
    ) -> PositionExitDecision | None:
        """Evaluate whether a closed candlestick pattern invalidates the position."""
        engulfing = detect_engulfing(
            prev_candle=prev_candle,
            curr_candle=curr_candle,
        )
        pinbar = detect_pinbar(candle=curr_candle)

        # Short position invalidated by bullish reversal
        if position.side is PositionSide.SHORT:
            if engulfing.matched and engulfing.side is PositionSide.LONG:
                return PositionExitDecision(
                    action=PositionExitAction.EARLY_CUT_LOSS,
                    symbol=position.symbol,
                    reason="Bullish engulfing candle formed against SHORT position",
                    confidence=0.85,
                    trigger_price=curr_candle.close_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl,
                )

            if pinbar.matched and pinbar.side is PositionSide.LONG:
                return PositionExitDecision(
                    action=PositionExitAction.EARLY_CUT_LOSS,
                    symbol=position.symbol,
                    reason=(
                        "Bullish pinbar rejection candle formed against SHORT position"
                    ),
                    confidence=0.80,
                    trigger_price=curr_candle.close_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl,
                )

        # Long position invalidated by bearish reversal
        if position.side is PositionSide.LONG:
            if engulfing.matched and engulfing.side is PositionSide.SHORT:
                return PositionExitDecision(
                    action=PositionExitAction.EARLY_CUT_LOSS,
                    symbol=position.symbol,
                    reason="Bearish engulfing candle formed against LONG position",
                    confidence=0.85,
                    trigger_price=curr_candle.close_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl,
                )

            if pinbar.matched and pinbar.side is PositionSide.SHORT:
                return PositionExitDecision(
                    action=PositionExitAction.EARLY_CUT_LOSS,
                    symbol=position.symbol,
                    reason=(
                        "Bearish pinbar rejection candle formed against LONG position"
                    ),
                    confidence=0.80,
                    trigger_price=curr_candle.close_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl,
                )

        return None
