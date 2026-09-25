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
from botragram.indicators import (
    calculate_bollinger_bands,
    calculate_macd,
    calculate_psar,
    calculate_rsi,
    calculate_sma,
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
    check_exhaustion: bool = True

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

        # Check Exhaustion Confluence first (can secure profit via EARLY_TAKE_PROFIT
        # or cut loss via EARLY_CUT_LOSS when multi-indicator exhaustion is detected)
        if self.check_exhaustion and len(candles) >= 30:
            exhaustion_decision = self._check_exhaustion_confluence(
                position=position,
                candles=candles,
            )
            if exhaustion_decision is not None:
                return exhaustion_decision

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

    def _check_exhaustion_confluence(
        self,
        *,
        position: Position,
        candles: Sequence[Candle],
    ) -> PositionExitDecision | None:
        """Evaluate multi-indicator exhaustion confluence upon candle close.

        Combines Bollinger Bands, RSI momentum, MACD histogram, Parabolic SAR,
        and Volume expansion to detect structural turning points.
        """
        if len(candles) < 30:
            return None

        close_prices = tuple(candle.close_price for candle in candles)
        high_prices = tuple(candle.high_price for candle in candles)
        low_prices = tuple(candle.low_price for candle in candles)
        volumes = tuple(candle.volume for candle in candles)

        bb = calculate_bollinger_bands(
            close_prices, period=20, standard_deviation=Decimal("2.0")
        )
        rsi = calculate_rsi(close_prices, period=14)
        macd = calculate_macd(
            close_prices, fast_period=12, slow_period=26, signal_period=9
        )
        psar = calculate_psar(high_prices, low_prices)
        vol_sma = calculate_sma(volumes, period=20)

        curr_candle = candles[-1]
        score = _DECIMAL_ZERO
        signals_detected: list[str] = []

        if position.side is PositionSide.LONG:
            # 1. Bollinger Band breach and re-entry/rejection
            upper_bb = bb.upper[-1]
            if (
                curr_candle.high_price >= upper_bb
                and curr_candle.close_price < upper_bb
            ):
                score += Decimal("0.25")
                signals_detected.append("Upper BB rejection")

            # 2. RSI Overbought or turning down from high levels
            curr_rsi = rsi[-1]
            prev_rsi = rsi[-2]
            if curr_rsi >= Decimal("70.0"):
                score += Decimal("0.25")
                signals_detected.append(f"RSI Overbought ({curr_rsi:.1f})")
            elif prev_rsi >= Decimal("65.0") and curr_rsi < prev_rsi:
                score += Decimal("0.15")
                signals_detected.append(f"RSI Hook Down ({curr_rsi:.1f})")

            # 3. MACD Histogram weakening / rolling over
            if len(macd.histogram) >= 2:
                curr_hist = macd.histogram[-1]
                prev_hist = macd.histogram[-2]
                if curr_hist < prev_hist:
                    score += Decimal("0.20")
                    signals_detected.append("MACD histogram weakening")

            # 4. Parabolic SAR flip to bearish
            if psar.is_uptrend[-1] is False:
                score += Decimal("0.20")
                signals_detected.append("PSAR flipped bearish")

            # 5. Volume surge on exhaustion candle
            if curr_candle.volume >= Decimal("1.5") * vol_sma[-1]:
                score += Decimal("0.15")
                signals_detected.append("Exhaustion volume surge")

            # 6. Upper wick rejection (buyer exhaustion shadow)
            candle_range = curr_candle.high_price - curr_candle.low_price
            if candle_range > _DECIMAL_ZERO:
                upper_wick = curr_candle.high_price - max(
                    curr_candle.open_price, curr_candle.close_price
                )
                if (upper_wick / candle_range) >= Decimal("0.40"):
                    score += Decimal("0.20")
                    signals_detected.append("Upper wick rejection")

        elif position.side is PositionSide.SHORT:
            # 1. Bollinger Band breach and re-entry/rejection
            lower_bb = bb.lower[-1]
            if curr_candle.low_price <= lower_bb and curr_candle.close_price > lower_bb:
                score += Decimal("0.25")
                signals_detected.append("Lower BB rejection")

            # 2. RSI Oversold or turning up from low levels
            curr_rsi = rsi[-1]
            prev_rsi = rsi[-2]
            if curr_rsi <= Decimal("30.0"):
                score += Decimal("0.25")
                signals_detected.append(f"RSI Oversold ({curr_rsi:.1f})")
            elif prev_rsi <= Decimal("35.0") and curr_rsi > prev_rsi:
                score += Decimal("0.15")
                signals_detected.append(f"RSI Hook Up ({curr_rsi:.1f})")

            # 3. MACD Histogram weakening / bottoming
            if len(macd.histogram) >= 2:
                curr_hist = macd.histogram[-1]
                prev_hist = macd.histogram[-2]
                if curr_hist > prev_hist:
                    score += Decimal("0.20")
                    signals_detected.append("MACD histogram recovering")

            # 4. Parabolic SAR flip to bullish
            if psar.is_uptrend[-1] is True:
                score += Decimal("0.20")
                signals_detected.append("PSAR flipped bullish")

            # 5. Volume surge on exhaustion candle
            if curr_candle.volume >= Decimal("1.5") * vol_sma[-1]:
                score += Decimal("0.15")
                signals_detected.append("Exhaustion volume surge")

            # 6. Lower wick rejection (seller exhaustion shadow)
            candle_range = curr_candle.high_price - curr_candle.low_price
            if candle_range > _DECIMAL_ZERO:
                lower_wick = (
                    min(curr_candle.open_price, curr_candle.close_price)
                    - curr_candle.low_price
                )
                if (lower_wick / candle_range) >= Decimal("0.40"):
                    score += Decimal("0.20")
                    signals_detected.append("Lower wick rejection")

        clamped_score = min(score, Decimal("1.0"))
        if clamped_score >= Decimal(str(self.min_confidence)):
            signals_str = ", ".join(signals_detected)
            in_profit = self._is_in_profit(position=position)
            action = (
                PositionExitAction.EARLY_TAKE_PROFIT
                if in_profit
                else PositionExitAction.EARLY_CUT_LOSS
            )
            action_desc = "Early Take Profit" if in_profit else "Early Cut Loss"
            return PositionExitDecision(
                action=action,
                symbol=position.symbol,
                reason=(
                    f"{action_desc}: Multi-indicator exhaustion confluence "
                    f"[{signals_str}] "
                    f"(score={clamped_score:.2f} >= {self.min_confidence:.2f})"
                ),
                confidence=float(clamped_score),
                trigger_price=curr_candle.close_price,
                current_price=position.current_price,
                unrealized_pnl=position.unrealized_pnl,
            )

        return None
