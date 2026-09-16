"""
Botragram

Description:
    Trading risk evaluation and position sizing engine.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Final

from botragram.config.risk_settings import RiskSettings
from botragram.constants.strategy import get_strategy_default_exit_rates
from botragram.enums import PositionSide, SignalType, StrategyType
from botragram.models import (
    Position,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
)

__all__ = [
    "DEFAULT_BREAKEVEN_FEE_BUFFER",
    "DEFAULT_BREAKEVEN_ROI_THRESHOLD",
    "LOCKED_PROGRESS_LAG",
    "PROGRESS_THRESHOLDS",
    "RiskEngine",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LIQUIDATION_SAFETY_FACTOR: Final[Decimal] = Decimal("0.70")
_MAINTENANCE_MARGIN_BUFFER: Final[Decimal] = Decimal("0.012")

PROGRESS_THRESHOLDS: Final[tuple[Decimal, ...]] = (
    Decimal("0.30"),
    Decimal("0.45"),
    Decimal("0.60"),
    Decimal("0.75"),
    Decimal("0.90"),
)
LOCKED_PROGRESS_LAG: Final[Decimal] = Decimal("0.20")
DEFAULT_BREAKEVEN_ROI_THRESHOLD: Final[Decimal] = Decimal("0.30")
DEFAULT_BREAKEVEN_FEE_BUFFER: Final[Decimal] = Decimal("0.0016")


@dataclass(slots=True, kw_only=True, frozen=True)
class RiskEngine:
    """Evaluate trading signals and calculate position sizing."""

    settings: RiskSettings

    def resolve_exit_rates(
        self,
        strategy_type: StrategyType | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Return the effective (stop_loss_pct, take_profit_pct) for a strategy."""
        return self._resolve_exit_rates(strategy_type=strategy_type)

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

    @staticmethod
    def calculate_tp_progress(
        *,
        position: Position,
        current_price: Decimal,
    ) -> Decimal:
        """Return favorable price movement as a ratio of the TP distance."""
        take_profit = position.take_profit
        if take_profit is None:
            return _DECIMAL_ZERO

        target_distance = abs(take_profit - position.entry_price)
        if target_distance <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        favorable_move = (
            current_price - position.entry_price
            if position.side is PositionSide.LONG
            else position.entry_price - current_price
        )
        return max(favorable_move / target_distance, _DECIMAL_ZERO)

    @staticmethod
    def calculate_position_roi(
        *,
        position: Position,
        current_price: Decimal,
    ) -> Decimal:
        """Return return-on-equity (ROI) ratio based on position leverage."""
        if position.entry_price <= _DECIMAL_ZERO or position.leverage <= 0:
            return _DECIMAL_ZERO

        if position.side is PositionSide.LONG:
            price_change = (current_price - position.entry_price) / position.entry_price
        else:
            price_change = (position.entry_price - current_price) / position.entry_price

        return price_change * Decimal(position.leverage)

    @classmethod
    def resolve_protection_step(
        cls,
        *,
        progress: Decimal,
        roi: Decimal,
        breakeven_roi_threshold: Decimal = DEFAULT_BREAKEVEN_ROI_THRESHOLD,
    ) -> int:
        """Return the highest crossed protection step number.

        Step 1: Breakeven lock activated when ROI >= breakeven_roi_threshold.
        Steps 2..6: Stepped profit protection based on TP progress
        (30%, 45%, 60%, 75%, 90%).
        """
        tp_steps = sum(progress >= threshold for threshold in PROGRESS_THRESHOLDS)
        if tp_steps > 0:
            return tp_steps + 1
        if roi >= breakeven_roi_threshold:
            return 1
        return 0

    @classmethod
    def calculate_stepped_stop_loss(
        cls,
        *,
        position: Position,
        step: int,
        breakeven_fee_buffer: Decimal = DEFAULT_BREAKEVEN_FEE_BUFFER,
    ) -> Decimal:
        """Calculate the profit-lock price for a specific protection step.

        Invariant: Steps >= 2 must never lock in less profit than Step 1
        breakeven fee buffer.
        """
        fee_buffer_distance = position.entry_price * breakeven_fee_buffer

        if step == 1:
            if position.side is PositionSide.LONG:
                return position.entry_price + fee_buffer_distance
            return position.entry_price - fee_buffer_distance

        take_profit = position.take_profit
        if take_profit is None:
            raise ValueError("Profit protection requires a take-profit price")

        threshold_idx = step - 2
        if not (0 <= threshold_idx < len(PROGRESS_THRESHOLDS)):
            raise ValueError(f"Invalid protection step: {step}")

        locked_progress = PROGRESS_THRESHOLDS[threshold_idx] - LOCKED_PROGRESS_LAG
        locked_distance = abs(take_profit - position.entry_price) * locked_progress

        if position.side is PositionSide.LONG:
            return position.entry_price + locked_distance

        return position.entry_price - locked_distance

    def evaluate(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        current_drawdown_pct: Decimal = _DECIMAL_ZERO,
        max_position_size_usdt: Decimal | None = None,
        leverage: int | None = None,
        dynamic_leverage_enabled: bool | None = None,
        volatility_pct: Decimal | None = None,
        remaining_slots: int | None = None,
    ) -> RiskResult:
        """Evaluate a signal against configured and optional runtime limits."""
        self._validate_inputs(
            signal=signal,
            account_balance=account_balance,
            current_drawdown_pct=current_drawdown_pct,
        )
        if volatility_pct is not None and (
            not volatility_pct.is_finite() or volatility_pct <= _DECIMAL_ZERO
        ):
            raise ValueError("Volatility percentage must be finite and positive")
        if remaining_slots is not None and (
            isinstance(remaining_slots, bool) or remaining_slots <= 0
        ):
            raise ValueError("Remaining slots must be positive")

        effective_max_position_size = self._resolve_max_position_size(
            runtime_limit=max_position_size_usdt,
        )
        effective_leverage = (
            leverage
            if (
                leverage is not None and not isinstance(leverage, bool) and leverage > 0
            )
            else self.settings.leverage
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

        if signal.stop_loss is not None:
            if not signal.stop_loss.is_finite() or signal.stop_loss <= _DECIMAL_ZERO:
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Explicit stop-loss must be finite and positive",
                )
            if (
                signal.signal_type is SignalType.BUY
                and signal.stop_loss >= signal.price
            ):
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Explicit buy stop-loss must be below entry price",
                )
            if (
                signal.signal_type is SignalType.SELL
                and signal.stop_loss <= signal.price
            ):
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Explicit sell stop-loss must be above entry price",
                )
            stop_loss = signal.stop_loss
        else:
            stop_loss = self._calculate_stop_loss(
                signal_type=signal.signal_type,
                entry_price=signal.price,
                stop_loss_pct=stop_loss_pct,
            )

        if signal.take_profit is not None:
            if (
                not signal.take_profit.is_finite()
                or signal.take_profit <= _DECIMAL_ZERO
            ):
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Explicit take-profit must be finite and positive",
                )
            if (
                signal.signal_type is SignalType.BUY
                and signal.take_profit <= signal.price
            ):
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Explicit buy take-profit must be above entry price",
                )
            if (
                signal.signal_type is SignalType.SELL
                and signal.take_profit >= signal.price
            ):
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Explicit sell take-profit must be below entry price",
                )
            take_profit = signal.take_profit
        else:
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

        is_dynamic = (
            dynamic_leverage_enabled
            if dynamic_leverage_enabled is not None
            else self.settings.dynamic_leverage_enabled
        )
        if is_dynamic:
            sl_pct = risk_per_unit / signal.price
            if sl_pct > _DECIMAL_ZERO:
                effective_risk_distance = (
                    max(sl_pct, volatility_pct)
                    if volatility_pct is not None
                    else sl_pct
                )
                denominator = (
                    effective_risk_distance / _LIQUIDATION_SAFETY_FACTOR
                ) + _MAINTENANCE_MARGIN_BUFFER
                safe_lev = (
                    int(Decimal("1") / denominator)
                    if denominator > _DECIMAL_ZERO
                    else self.settings.min_leverage
                )
                effective_leverage = min(
                    self.settings.max_leverage,
                    max(self.settings.min_leverage, safe_lev),
                )

        if (
            self.settings.slot_sizing_enabled
            and remaining_slots is not None
            and remaining_slots > 0
        ):
            usable_balance = account_balance * (
                Decimal("1") - self.settings.slot_margin_buffer_pct
            )
            if usable_balance <= _DECIMAL_ZERO:
                return self._rejected_result(
                    entry_price=signal.price,
                    reason="Insufficient usable balance after safety margin buffer",
                )
            slot_margin = usable_balance / Decimal(remaining_slots)
            max_lev_decimal = Decimal(self.settings.max_leverage)
            if slot_margin * max_lev_decimal < self.settings.min_order_notional_usdt:
                return self._rejected_result(
                    entry_price=signal.price,
                    reason=(
                        f"Insufficient slot margin {slot_margin} to meet "
                        f"minimum order notional "
                        f"{self.settings.min_order_notional_usdt}"
                    ),
                )
            if (
                slot_margin * Decimal(effective_leverage)
                < self.settings.min_order_notional_usdt
                and effective_leverage < self.settings.max_leverage
            ):
                needed_lev = int(
                    (
                        self.settings.min_order_notional_usdt / slot_margin
                    ).to_integral_value(rounding=ROUND_CEILING)
                )
                effective_leverage = min(
                    self.settings.max_leverage,
                    max(effective_leverage, needed_lev),
                )

            notional = slot_margin * Decimal(effective_leverage)

            if (
                self.settings.volatility_sizing_enabled
                or self.settings.dynamic_sizing_enabled
            ) and volatility_pct is not None:
                vol_multiplier = min(
                    Decimal("1.5"),
                    max(
                        Decimal("0.5"),
                        self.settings.baseline_volatility_pct / volatility_pct,
                    ),
                )
                notional = notional * vol_multiplier

            if (
                self.settings.dynamic_sizing_enabled
                and self.settings.confidence_sizing_enabled
                and signal.confidence > _DECIMAL_ZERO
                and self.settings.baseline_confidence > _DECIMAL_ZERO
            ):
                conf_multiplier = min(
                    self.settings.max_confidence_multiplier,
                    max(
                        self.settings.min_confidence_multiplier,
                        signal.confidence / self.settings.baseline_confidence,
                    ),
                )
                notional = notional * conf_multiplier

            if notional > effective_max_position_size:
                notional = effective_max_position_size

            max_balance_notional = usable_balance * Decimal(effective_leverage)
            if notional > max_balance_notional:
                notional = max_balance_notional

            if notional < self.settings.min_order_notional_usdt <= max_balance_notional:
                notional = self.settings.min_order_notional_usdt

            quantity = notional / signal.price
        else:
            allowed_risk = account_balance * self.settings.risk_per_trade_pct
            quantity = allowed_risk / risk_per_unit
            notional = quantity * signal.price

            if (
                self.settings.volatility_sizing_enabled
                or self.settings.dynamic_sizing_enabled
            ) and volatility_pct is not None:
                vol_multiplier = min(
                    Decimal("1.5"),
                    max(
                        Decimal("0.5"),
                        self.settings.baseline_volatility_pct / volatility_pct,
                    ),
                )
                notional = notional * vol_multiplier

            if (
                self.settings.dynamic_sizing_enabled
                and self.settings.confidence_sizing_enabled
                and signal.confidence > _DECIMAL_ZERO
                and self.settings.baseline_confidence > _DECIMAL_ZERO
            ):
                conf_multiplier = min(
                    self.settings.max_confidence_multiplier,
                    max(
                        self.settings.min_confidence_multiplier,
                        signal.confidence / self.settings.baseline_confidence,
                    ),
                )
                notional = notional * conf_multiplier

            if notional > effective_max_position_size:
                notional = effective_max_position_size
                quantity = notional / signal.price
            else:
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
                leverage=effective_leverage,
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

    def _resolve_max_position_size(
        self,
        *,
        runtime_limit: Decimal | None,
    ) -> Decimal:
        """Return a runtime limit without allowing it above the env ceiling."""
        hard_limit = self.settings.max_position_size_usdt
        if runtime_limit is None:
            return hard_limit
        if not runtime_limit.is_finite() or runtime_limit <= _DECIMAL_ZERO:
            raise ValueError(
                "Runtime maximum position size must be finite and positive"
            )
        if runtime_limit > hard_limit:
            raise ValueError("Runtime maximum position size exceeds configured ceiling")
        return runtime_limit

    def _validate_inputs(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        current_drawdown_pct: Decimal,
    ) -> None:
        """Validate trading risk inputs."""
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
        """Resolve strategy-specific or fallback global exit percentages."""
        match strategy_type:
            case (
                StrategyType.EMA_SCALPING
                | StrategyType.RSI_BB_SCALPING
                | StrategyType.VWAP_BREAKOUT
            ):
                return (
                    self.settings.scalping_stop_loss_pct,
                    self.settings.scalping_take_profit_pct,
                )
            case StrategyType.EMA_CROSS:
                return (
                    self.settings.ema_cross_stop_loss_pct,
                    self.settings.ema_cross_take_profit_pct,
                )
            case (
                StrategyType.EMA_RSI
                | StrategyType.ICHIMOKU_CLOUD
                | StrategyType.SUPERTREND
                | StrategyType.ADX_TREND
                | StrategyType.BOLLINGER_BREAKOUT
            ):
                return (
                    self.settings.trend_stop_loss_pct,
                    self.settings.trend_take_profit_pct,
                )
            case StrategyType.MACD_SWING:
                return (
                    self.settings.swing_stop_loss_pct,
                    self.settings.swing_take_profit_pct,
                )
            case StrategyType.PINBAR_ENGULFING_EMA_RSI:
                return (
                    self.settings.pier_stop_loss_pct,
                    self.settings.pier_take_profit_pct,
                )
            case (
                StrategyType.HIGH_CONFLUENCE_EXHAUSTION
                | StrategyType.CHOCH_FVG
                | StrategyType.LIQUIDITY_SWEEP_EXHAUSTION
                | StrategyType.CHOCH_RSI_BB_HYBRID
                | StrategyType.MORPH
                | StrategyType.QUAD_CONFLUENCE
            ):
                return get_strategy_default_exit_rates(strategy_type)
            case _:
                return self.settings.stop_loss_pct, self.settings.take_profit_pct

    @staticmethod
    def _resolve_strategy_type(strategy_name: str) -> StrategyType | None:
        try:
            return StrategyType(strategy_name)
        except ValueError:
            return None
