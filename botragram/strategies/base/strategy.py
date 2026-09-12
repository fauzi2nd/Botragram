"""
Botragram

Description:
    Base trading strategy interface.

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
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType, StrategyType
from botragram.indicators import (
    evaluate_account_ratio_sentiment,
    evaluate_oi_confluence,
)
from botragram.models import Candle, Signal

__all__ = [
    "BaseStrategy",
]


# =============================================================================
# Abstract Strategy Classes
# =============================================================================
class BaseStrategy(ABC):
    """Abstract interface implemented by trading strategies."""

    __slots__ = ()

    @property
    @abstractmethod
    def strategy_type(self) -> StrategyType:
        """Return the strategy type."""

    @property
    @abstractmethod
    def minimum_candles(self) -> int:
        """Return the minimum candle count required for evaluation."""

    @abstractmethod
    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
    ) -> Signal:
        """Generate a trading signal from ordered candle data.

        Args:
            candles: Candles ordered from oldest to newest.

        Returns:
            Generated trading signal.

        Raises:
            ValueError: If candle data is insufficient or invalid.
        """

    def validate_candles(
        self,
        *,
        candles: Sequence[Candle],
    ) -> None:
        """Validate candle data before strategy evaluation.

        Args:
            candles: Candles ordered from oldest to newest.

        Raises:
            ValueError: If candle data is insufficient, contains mixed
                symbols, or is not chronologically ordered.
        """
        if len(candles) < self.minimum_candles:
            raise ValueError(
                f"{self.strategy_type.value} requires at least "
                f"{self.minimum_candles} candles"
            )

        first_symbol = candles[0].symbol

        if any(candle.symbol != first_symbol for candle in candles[1:]):
            raise ValueError("Strategy candles must use the same trading symbol")

        if any(
            previous.open_time >= current.open_time
            for previous, current in zip(
                candles,
                candles[1:],
                strict=False,
            )
        ):
            raise ValueError("Strategy candles must be ordered from oldest to newest")

    def apply_open_interest_confluence(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
        min_change_pct: Decimal = Decimal("0.0"),
        confidence_bonus: Decimal = Decimal("0.05"),
        strict: bool = False,
    ) -> Signal:
        """Apply Open Interest confluence evaluation to a generated signal.

        Args:
            signal: Generated candidate signal.
            candles: Candle sequence used for evaluation.
            min_change_pct: Minimum positive OI change percentage for confirmation.
            confidence_bonus: Confidence bonus to add when confirmed.
            strict: When True, transforms warning or contradictory signals to HOLD.

        Returns:
            Enhanced or filtered Signal.
        """
        if signal.signal_type is SignalType.HOLD:
            return signal

        confluence = evaluate_oi_confluence(
            signal_type=signal.signal_type,
            candles=candles,
            min_change_pct=min_change_pct,
        )
        if confluence is None:
            return signal

        if confluence.is_confirmed:
            new_confidence = min(Decimal("0.95"), signal.confidence + confidence_bonus)
            return replace(
                signal,
                confidence=new_confidence,
                reason=f"{signal.reason} [{confluence.reason}]",
            )

        if confluence.is_warning:
            if strict:
                return replace(
                    signal,
                    signal_type=SignalType.HOLD,
                    confidence=Decimal("0.0"),
                    reason=(
                        f"[REJECTED_OI] {confluence.reason} "
                        f"(originally {signal.signal_type.value})"
                    ),
                )
            new_confidence = max(Decimal("0.10"), signal.confidence - confidence_bonus)
            return replace(
                signal,
                confidence=new_confidence,
                reason=f"{signal.reason} [{confluence.reason}]",
            )

        return signal

    def apply_funding_sentiment_filter(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
        max_long_funding: Decimal = Decimal("0.0005"),
        min_short_funding: Decimal = Decimal("-0.0005"),
        strict: bool = True,
    ) -> Signal:
        """Apply Funding Rate crowding sentiment filter to a generated signal.

        Args:
            signal: Generated candidate signal.
            candles: Candle sequence containing latest funding rate.
            max_long_funding: Maximum funding rate allowed for BUY signals
                (default +0.05% / +0.0005 per 8h, excessive long crowding).
            min_short_funding: Minimum funding rate allowed for SELL signals
                (default -0.05% / -0.0005 per 8h, excessive short crowding).
            strict: If True, transforms signal into HOLD. If False, reduces confidence.

        Returns:
            Filtered or confidence-adjusted Signal.
        """
        if signal.signal_type is SignalType.HOLD or not candles:
            return signal

        latest_candle = candles[-1]
        funding_rate = latest_candle.funding_rate
        if funding_rate is None:
            return signal

        if signal.signal_type is SignalType.BUY and funding_rate > max_long_funding:
            if strict:
                return replace(
                    signal,
                    signal_type=SignalType.HOLD,
                    confidence=Decimal("0.0"),
                    reason=(
                        f"[REJECTED_FUNDING_CROWDED] Excessive long funding "
                        f"({funding_rate:.4%}>{max_long_funding:.4%}) "
                        f"(originally {signal.signal_type.value})"
                    ),
                )
            return replace(
                signal,
                confidence=max(Decimal("0.10"), signal.confidence - Decimal("0.15")),
                reason=f"{signal.reason} [CROWDED_LONG: funding {funding_rate:.4%}]",
            )

        if signal.signal_type is SignalType.SELL and funding_rate < min_short_funding:
            if strict:
                return replace(
                    signal,
                    signal_type=SignalType.HOLD,
                    confidence=Decimal("0.0"),
                    reason=(
                        f"[REJECTED_FUNDING_CROWDED] Excessive short funding "
                        f"({funding_rate:.4%}<{min_short_funding:.4%}) "
                        f"(originally {signal.signal_type.value})"
                    ),
                )
            return replace(
                signal,
                confidence=max(Decimal("0.10"), signal.confidence - Decimal("0.15")),
                reason=f"{signal.reason} [CROWDED_SHORT: funding {funding_rate:.4%}]",
            )

        return signal

    def apply_account_ratio_filter(
        self,
        *,
        signal: Signal,
        candles: Sequence[Candle],
        max_long_ratio: Decimal = Decimal("0.75"),
        min_short_ratio: Decimal = Decimal("0.25"),
        strict: bool = True,
    ) -> Signal:
        """Apply Account Long-Short Ratio crowd sentiment filter to a signal.

        Args:
            signal: Generated candidate signal.
            candles: Candle sequence containing latest candle with buy_ratio.
            max_long_ratio: Upper threshold above which market is crowded long.
            min_short_ratio: Lower threshold below which market is crowded short.
            strict: If True, transforms contradictory signal to HOLD. If False,
                reduces confidence.

        Returns:
            Filtered or confidence-adjusted Signal.
        """
        if signal.signal_type is SignalType.HOLD or not candles:
            return signal

        latest_candle = candles[-1]
        buy_ratio = latest_candle.buy_ratio
        if buy_ratio is None:
            return signal

        sentiment = evaluate_account_ratio_sentiment(
            buy_ratio=buy_ratio,
            max_long_ratio=max_long_ratio,
            min_short_ratio=min_short_ratio,
        )

        if signal.signal_type is SignalType.BUY and sentiment.is_crowded_long:
            if strict:
                return replace(
                    signal,
                    signal_type=SignalType.HOLD,
                    confidence=Decimal("0.0"),
                    reason=(
                        f"[REJECTED_LS_RATIO] {sentiment.reason} "
                        f"(originally {signal.signal_type.value})"
                    ),
                )
            return replace(
                signal,
                confidence=max(Decimal("0.10"), signal.confidence - Decimal("0.15")),
                reason=f"{signal.reason} [{sentiment.reason}]",
            )

        if signal.signal_type is SignalType.SELL and sentiment.is_crowded_short:
            if strict:
                return replace(
                    signal,
                    signal_type=SignalType.HOLD,
                    confidence=Decimal("0.0"),
                    reason=(
                        f"[REJECTED_LS_RATIO] {sentiment.reason} "
                        f"(originally {signal.signal_type.value})"
                    ),
                )
            return replace(
                signal,
                confidence=max(Decimal("0.10"), signal.confidence - Decimal("0.15")),
                reason=f"{signal.reason} [{sentiment.reason}]",
            )

        return signal
