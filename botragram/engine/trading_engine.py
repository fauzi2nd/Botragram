"""
Botragram

Description:
    Trading execution decision engine.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from botragram.engine.cfd_financing_engine import CfdFinancingEngine
from botragram.engine.cfd_sizing_engine import CfdSizingEngine
from botragram.engine.portfolio_engine import PortfolioEngine
from botragram.engine.risk_engine import RiskEngine
from botragram.enums import MarketType, PositionSide, SignalType, StrategyType
from botragram.models import (
    Position,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
    TradingDecision,
)

__all__ = ["TradingEngine"]

_DECIMAL_ZERO = Decimal("0")
_HOLD_SIGNAL_REASON = "Strategy generated a hold signal"
_OPEN_POSITION_REASON = "An active position already exists for the symbol"
_MAXIMUM_OPEN_POSITIONS_REASON = "Maximum open positions reached"


@dataclass(slots=True, kw_only=True, frozen=True)
class TradingEngine:
    """Evaluate whether a trading signal should be executed."""

    risk_engine: RiskEngine
    portfolio_engine: PortfolioEngine = field(default_factory=PortfolioEngine)
    min_signal_confidence: Decimal = _DECIMAL_ZERO
    cfd_sizing_engine: CfdSizingEngine | None = None
    cfd_financing_engine: CfdFinancingEngine | None = None
    market_type: MarketType = MarketType.FUTURES

    def evaluate(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        has_open_position: bool,
        open_positions: Sequence[Position] | None = None,
        current_drawdown_pct: Decimal = _DECIMAL_ZERO,
        max_open_positions: int | None = None,
        max_position_size_usdt: Decimal | None = None,
        leverage: int | None = None,
        dynamic_leverage_enabled: bool | None = None,
        volatility_pct: Decimal | None = None,
    ) -> TradingDecision:
        """Evaluate a signal with optional runtime limits below env ceilings."""
        self._validate_inputs(
            account_balance=account_balance,
            current_drawdown_pct=current_drawdown_pct,
        )
        effective_max_open_positions = self._resolve_max_open_positions(
            runtime_limit=max_open_positions,
        )

        if signal.signal_type is SignalType.HOLD:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=_HOLD_SIGNAL_REASON,
            )

        if signal.confidence < self.min_signal_confidence:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=(
                    f"Signal confidence {signal.confidence} is below "
                    f"minimum threshold {self.min_signal_confidence}"
                ),
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
                max_open_positions=effective_max_open_positions,
            ):
                return TradingDecision(
                    should_execute=False,
                    signal=signal,
                    risk_result=None,
                    reason=_MAXIMUM_OPEN_POSITIONS_REASON,
                )

        current_open_positions_count = (
            len(open_positions) if open_positions is not None else 0
        )
        remaining_slots = max(
            1,
            effective_max_open_positions - current_open_positions_count,
        )

        if self.market_type is MarketType.CFD and self.cfd_sizing_engine is not None:
            return self._evaluate_cfd(
                signal=signal,
                account_balance=account_balance,
                current_drawdown_pct=current_drawdown_pct,
                max_position_size_usdt=max_position_size_usdt,
                leverage=leverage,
            )

        risk_result = self.risk_engine.evaluate(
            signal=signal,
            account_balance=account_balance,
            current_drawdown_pct=current_drawdown_pct,
            max_position_size_usdt=max_position_size_usdt,
            leverage=leverage,
            dynamic_leverage_enabled=dynamic_leverage_enabled,
            volatility_pct=volatility_pct,
            remaining_slots=remaining_slots,
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

    def _evaluate_cfd(
        self,
        *,
        signal: Signal,
        account_balance: Decimal,
        current_drawdown_pct: Decimal,
        max_position_size_usdt: Decimal | None = None,
        leverage: int | None,
    ) -> TradingDecision:
        """Evaluate a CFD signal calculating lots, margin, and leverage."""
        if self.cfd_sizing_engine is None:
            raise RuntimeError("CFD sizing engine is required for MarketType.CFD")

        if current_drawdown_pct >= self.risk_engine.settings.max_drawdown_pct:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason="Maximum account drawdown reached",
            )

        effective_max_position_size = self._resolve_max_position_size(
            runtime_limit=max_position_size_usdt,
        )

        spec = self.cfd_sizing_engine.get_contract_spec(signal.symbol)
        # CFD leverage must originate from authoritative instrument metadata,
        # not generic futures assumptions
        requested_lev = spec.default_leverage
        effective_leverage = (
            self.cfd_financing_engine.validate_leverage(signal.symbol, requested_lev)
            if self.cfd_financing_engine is not None
            else requested_lev
        )

        try:
            strategy_type = StrategyType(signal.strategy_name)
        except ValueError:
            strategy_type = None

        if signal.stop_loss is not None and signal.take_profit is not None:
            stop_loss = signal.stop_loss
            take_profit = signal.take_profit
        else:
            side = (
                PositionSide.LONG
                if signal.signal_type is SignalType.BUY
                else PositionSide.SHORT
            )
            calc_sl, calc_tp = self.risk_engine.calculate_protection_levels(
                side=side,
                entry_price=signal.price,
                strategy_type=strategy_type,
            )
            stop_loss = signal.stop_loss if signal.stop_loss is not None else calc_sl
            take_profit = (
                signal.take_profit if signal.take_profit is not None else calc_tp
            )

        risk_amount = account_balance * self.risk_engine.settings.risk_per_trade_pct
        try:
            sizing = self.cfd_sizing_engine.calculate_lot_size(
                symbol=signal.symbol,
                entry_price=signal.price,
                stop_loss=stop_loss,
                risk_amount=risk_amount,
            )
        except ValueError as err:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=f"CFD sizing calculation failed: {err}",
            )

        normalized_lots = sizing.normalized_lots
        if normalized_lots <= _DECIMAL_ZERO:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason="Calculated CFD lot size is zero",
            )

        # Validate that actual executable loss does not exceed configured risk budget
        actual_risk = (
            sizing.distance_in_pips * sizing.pip_value_per_lot * normalized_lots
        )
        if actual_risk > risk_amount:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=(
                    f"Normalized CFD risk {actual_risk} exceeds configured "
                    f"risk budget {risk_amount}"
                ),
            )

        # Enforce maximum position size ceiling
        notional_usdt = sizing.notional_value
        if notional_usdt > effective_max_position_size:
            return TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=(
                    f"CFD position notional {notional_usdt} exceeds maximum "
                    f"position size limit {effective_max_position_size}"
                ),
            )

        if self.cfd_financing_engine is not None:
            margin_req = self.cfd_financing_engine.calculate_margin_requirement(
                symbol=signal.symbol,
                lots=normalized_lots,
                price=signal.price,
                leverage=effective_leverage,
                free_margin=account_balance,
            )
            if not margin_req.is_sufficient:
                return TradingDecision(
                    should_execute=False,
                    signal=signal,
                    risk_result=None,
                    reason=(
                        f"Insufficient free margin {account_balance} for "
                        f"CFD required margin {margin_req.required_margin}"
                    ),
                )

        spec = self.cfd_sizing_engine.get_contract_spec(signal.symbol)
        reward_dist_pips = abs(take_profit - signal.price) / spec.pip_size
        reward_amount = reward_dist_pips * sizing.pip_value_per_lot * normalized_lots
        sl_dist = abs(signal.price - stop_loss)
        rrr = (
            abs(take_profit - signal.price) / sl_dist
            if sl_dist > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )

        risk_result = RiskResult(
            approved=True,
            position=PositionSize(
                quantity=normalized_lots,
                notional=notional_usdt,
                leverage=effective_leverage,
            ),
            metrics=RiskMetrics(
                entry_price=signal.price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=actual_risk,
                reward_amount=reward_amount,
                risk_reward_ratio=rrr,
            ),
        )
        return TradingDecision(
            should_execute=True,
            signal=signal,
            risk_result=risk_result,
        )

    def _resolve_max_position_size(
        self,
        *,
        runtime_limit: Decimal | None,
    ) -> Decimal:
        """Resolve maximum position size ceiling through risk engine settings."""
        hard_limit = self.risk_engine.settings.max_position_size_usdt
        if runtime_limit is None:
            return hard_limit
        if not runtime_limit.is_finite() or runtime_limit <= _DECIMAL_ZERO:
            raise ValueError(
                "Runtime maximum position size must be finite and positive"
            )
        if runtime_limit > hard_limit:
            raise ValueError("Runtime maximum position size exceeds configured ceiling")
        return runtime_limit

    def _resolve_max_open_positions(self, *, runtime_limit: int | None) -> int:
        """Return a runtime capacity without allowing it above the env ceiling."""
        hard_limit = self.risk_engine.settings.max_open_positions
        if runtime_limit is None:
            return hard_limit
        if isinstance(runtime_limit, bool) or runtime_limit <= 0:
            raise ValueError("Runtime maximum open positions must be positive")
        if runtime_limit > hard_limit:
            raise ValueError(
                "Runtime maximum open positions exceeds configured ceiling"
            )
        return runtime_limit

    @staticmethod
    def _validate_inputs(
        *,
        account_balance: Decimal,
        current_drawdown_pct: Decimal,
    ) -> None:
        if account_balance <= _DECIMAL_ZERO:
            raise ValueError("Account balance must be greater than zero")
        if current_drawdown_pct < _DECIMAL_ZERO:
            raise ValueError("Current drawdown must not be negative")
