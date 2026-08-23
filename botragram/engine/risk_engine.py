"""
Botragram

Description:
    Trading risk evaluation and position sizing engine.

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
from botragram.config.risk_settings import RiskSettings
from botragram.enums import PositionSide, SignalType, StrategyType
from botragram.models import PositionSize, RiskMetrics, RiskResult, Signal

__all__ = [
    "RiskEngine",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Risk Engine
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class RiskEngine:
    """Evaluate trading signals and calculate position sizing."""

    settings: RiskSettings

    def calculate_protection_levels(
        self,
        *,
        side: PositionSide,
        entry_price: Decimal,
        strategy_type: StrategyType | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Calculate configured stop-loss and take-profit for a position."""
        if entry_price <= _DECIMAL_ZERO:
            raise ValueError("Position entry price must be greater than zero")

        signal_type = SignalType.BUY if side is PositionSide.LONG else SignalType.SELL
        stop_loss_pct, take_profit_pct = self._resolve_exit_rates(
            strategy_type=strategy_type,
        )
        return (
            self._calculate_stop_loss(
                signal_type=signal_type,
                entry_price=entry_price,
                stop_loss_pct=stop_loss_pct,
            ),
            self._calculate_take_profit(
                signal_type=signal_type,
                entry_price=entry_price,
                take_profit_pct=take_profit_pct,
            ),
        )

    def evaluate(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        current_drawdown_pct: Decimal = _DECIMAL_ZERO,
    ) -> RiskResult:
        """Evaluate a signal against configured risk limits.

        Args:
            signal: Trading signal to evaluate.
            account_balance: Available balance in quote currency.
            current_drawdown_pct: Current account drawdown ratio.

        Returns:
            Risk evaluation result.

        Raises:
            ValueError: If inputs are invalid.
        """
        self._validate_inputs(
            signal=signal,
            account_balance=account_balance,
            current_drawdown_pct=current_drawdown_pct,
        )

        if signal.signal_type is SignalType.HOLD:
            return self._rejected_result(
                entry_price=signal.price,
                reason="Hold signals cannot create a position",
            )

        if current_drawdown_pct >= self.settings.max_drawdown_pct:
            return self._rejected_result(
                entry_price=signal.price,
                reason="Maximum account drawdown reached",
            )

        strategy_type = self._resolve_strategy_type(signal.strategy_name)
        stop_loss_pct, take_profit_pct = self._resolve_exit_rates(
            strategy_type=strategy_type,
        )
        stop_loss = self._calculate_stop_loss(
            signal_type=signal.signal_type,
            entry_price=signal.price,
            stop_loss_pct=stop_loss_pct,
        )
        take_profit = self._calculate_take_profit(
            signal_type=signal.signal_type,
            entry_price=signal.price,
            take_profit_pct=take_profit_pct,
        )

        risk_per_unit = abs(signal.price - stop_loss)

        if risk_per_unit <= _DECIMAL_ZERO:
            return self._rejected_result(
                entry_price=signal.price,
                reason="Stop-loss distance must be greater than zero",
            )

        allowed_risk = account_balance * self.settings.risk_per_trade_pct

        quantity = allowed_risk / risk_per_unit
        notional = quantity * signal.price

        if notional > self.settings.max_position_size_usdt:
            notional = self.settings.max_position_size_usdt
            quantity = notional / signal.price

        risk_amount = quantity * risk_per_unit
        reward_amount = quantity * abs(take_profit - signal.price)

        risk_reward_ratio = (
            reward_amount / risk_amount
            if risk_amount > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )

        return RiskResult(
            approved=True,
            position=PositionSize(
                quantity=quantity,
                notional=notional,
                leverage=self.settings.leverage,
            ),
            metrics=RiskMetrics(
                entry_price=signal.price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=risk_amount,
                reward_amount=reward_amount,
                risk_reward_ratio=risk_reward_ratio,
            ),
        )

    def _validate_inputs(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        current_drawdown_pct: Decimal,
    ) -> None:
        """Validate risk evaluation inputs."""
        if account_balance <= _DECIMAL_ZERO:
            raise ValueError("Account balance must be greater than zero")

        if signal.price <= _DECIMAL_ZERO:
            raise ValueError("Signal price must be greater than zero")

        if current_drawdown_pct < _DECIMAL_ZERO:
            raise ValueError("Current drawdown must not be negative")

    def _calculate_stop_loss(
        self,
        *,
        signal_type: SignalType,
        entry_price: Decimal,
        stop_loss_pct: Decimal,
    ) -> Decimal:
        """Calculate stop-loss price."""
        distance = entry_price * stop_loss_pct

        if signal_type is SignalType.BUY:
            return entry_price - distance

        return entry_price + distance

    def _calculate_take_profit(
        self,
        *,
        signal_type: SignalType,
        entry_price: Decimal,
        take_profit_pct: Decimal,
    ) -> Decimal:
        """Calculate take-profit price."""
        distance = entry_price * take_profit_pct

        if signal_type is SignalType.BUY:
            return entry_price + distance

        return entry_price - distance

    def _rejected_result(
        self,
        *,
        entry_price: Decimal,
        reason: str,
    ) -> RiskResult:
        """Create a rejected risk result."""
        return RiskResult(
            approved=False,
            position=PositionSize(
                quantity=_DECIMAL_ZERO,
                notional=_DECIMAL_ZERO,
                leverage=self.settings.leverage,
            ),
            metrics=RiskMetrics(
                entry_price=entry_price,
                stop_loss=_DECIMAL_ZERO,
                take_profit=_DECIMAL_ZERO,
                risk_amount=_DECIMAL_ZERO,
                reward_amount=_DECIMAL_ZERO,
                risk_reward_ratio=_DECIMAL_ZERO,
            ),
            reason=reason,
        )

    def _resolve_exit_rates(
        self,
        *,
        strategy_type: StrategyType | None,
    ) -> tuple[Decimal, Decimal]:
        """Return the configured exit ratios for a strategy."""
        if strategy_type is StrategyType.EMA_SCALPING:
            return (
                self.settings.ema_scalping_stop_loss_pct,
                self.settings.ema_scalping_take_profit_pct,
            )

        if strategy_type is StrategyType.EMA_CROSS:
            return (
                self.settings.ema_cross_stop_loss_pct,
                self.settings.ema_cross_take_profit_pct,
            )

        return self.settings.stop_loss_pct, self.settings.take_profit_pct

    @staticmethod
    def _resolve_strategy_type(strategy_name: str) -> StrategyType | None:
        """Resolve a known strategy name without rejecting custom strategies."""
        try:
            return StrategyType(strategy_name)
        except ValueError:
            return None
