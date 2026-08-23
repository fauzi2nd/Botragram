"""
Botragram

Description:
    Trading execution decision engine.

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
from dataclasses import dataclass, field
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.portfolio_engine import PortfolioEngine
from botragram.engine.risk_engine import RiskEngine
from botragram.enums import SignalType
from botragram.models import Position, Signal, TradingDecision

__all__ = [
    "TradingEngine",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")

_HOLD_SIGNAL_REASON = "Strategy generated a hold signal"
_OPEN_POSITION_REASON = "An active position already exists for the symbol"
_MAXIMUM_OPEN_POSITIONS_REASON = "Maximum open positions reached"


# =============================================================================
# Trading Engine
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class TradingEngine:
    """Evaluate whether a trading signal should be executed."""

    risk_engine: RiskEngine
    portfolio_engine: PortfolioEngine = field(default_factory=PortfolioEngine)

    def evaluate(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        has_open_position: bool,
        open_positions: Sequence[Position] | None = None,
        current_drawdown_pct: Decimal = _DECIMAL_ZERO,
    ) -> TradingDecision:
        """Evaluate a signal and produce an execution decision.

        Args:
            signal: Trading signal to evaluate.
            account_balance: Available balance in quote currency.
            has_open_position: Whether the symbol already has a position.
            open_positions: Optional portfolio snapshot used for capacity and
                duplicate-symbol checks. Omit to preserve single-symbol
                evaluation behavior.
            current_drawdown_pct: Current account drawdown ratio.

        Returns:
            Immutable trading execution decision.

        Raises:
            ValueError: If evaluation inputs are invalid.
        """
        self._validate_inputs(
            account_balance=account_balance,
            current_drawdown_pct=current_drawdown_pct,
        )

        if signal.signal_type is SignalType.HOLD:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=_HOLD_SIGNAL_REASON,
            )

        if has_open_position:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=_OPEN_POSITION_REASON,
            )

        if open_positions is not None:
            if self.portfolio_engine.has_position(
                positions=open_positions,
                symbol=signal.symbol,
            ):
                return TradingDecision(
                    should_execute=False,
                    signal=signal,
                    risk_result=None,
                    reason=_OPEN_POSITION_REASON,
                )

            if not self.portfolio_engine.can_open_position(
                positions=open_positions,
                max_open_positions=self.risk_engine.settings.max_open_positions,
            ):
                return TradingDecision(
                    should_execute=False,
                    signal=signal,
                    risk_result=None,
                    reason=_MAXIMUM_OPEN_POSITIONS_REASON,
                )

        risk_result = self.risk_engine.evaluate(
            signal=signal,
            account_balance=account_balance,
            current_drawdown_pct=current_drawdown_pct,
        )

        if not risk_result.approved:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=risk_result,
                reason=risk_result.reason,
            )

        return TradingDecision(
            should_execute=True,
            signal=signal,
            risk_result=risk_result,
        )

    @staticmethod
    def _validate_inputs(
        *,
        account_balance: Decimal,
        current_drawdown_pct: Decimal,
    ) -> None:
        """Validate trading decision inputs."""
        if account_balance <= _DECIMAL_ZERO:
            raise ValueError("Account balance must be greater than zero")

        if current_drawdown_pct < _DECIMAL_ZERO:
            raise ValueError("Current drawdown must not be negative")
