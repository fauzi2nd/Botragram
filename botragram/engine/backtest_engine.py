"""
Botragram

Description:
    Deterministic candle-by-candle backtest engine.

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
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.pnl_engine import PnLEngine
from botragram.engine.risk_engine import DEFAULT_BREAKEVEN_FEE_BUFFER, RiskEngine
from botragram.engine.trading_engine import TradingEngine
from botragram.enums import (
    Interval,
    OrderSide,
    PositionSide,
    SignalType,
    StrategyType,
    TrailingMode,
)
from botragram.models import (
    BacktestMetrics,
    BacktestRequest,
    BacktestResult,
    BacktestTrade,
    Candle,
    Signal,
    Ticker,
    Trade,
)
from botragram.services.paper_trading_service import PaperTradingService
from botragram.services.strategy_service import StrategyService
from botragram.storage import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)
from botragram.strategies.base import BaseStrategy

__all__ = [
    "BacktestEngine",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")
_STRATEGY_WINDOW: Final[int] = 500
_BREAKEVEN_ROI_THRESHOLD: Final[Decimal] = Decimal("0.30")
_BREAKEVEN_FEE_BUFFER: Final[Decimal] = DEFAULT_BREAKEVEN_FEE_BUFFER
_PROTECTION_WARNING: Final[str] = (
    "Stepped SL+ uses conservative next-candle activation because OHLC does not "
    "encode intrabar high/low order"
)


# =============================================================================
# Backtest Engine
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestEngine:
    """Replay historical candles through the production PAPER execution path."""

    strategy: BaseStrategy
    risk_settings: RiskSettings
    strategy_service: StrategyService | None = None

    async def run(
        self,
        *,
        request: BacktestRequest,
        candles: Sequence[Candle],
    ) -> BacktestResult:
        """Run a deterministic backtest without future-candle access."""
        ordered_candles, warnings = self._validate_candles(
            request=request,
            candles=candles,
        )
        if self.strategy.strategy_type is not request.strategy_type:
            raise ValueError("Backtest strategy does not match the request")

        order_repository = MemoryOrderRepository()
        trade_repository = MemoryTradeRepository()
        position_repository = MemoryPositionRepository()
        paper_service = PaperTradingService(
            order_repository=order_repository,
            trade_repository=trade_repository,
            position_repository=position_repository,
            trading_engine=TradingEngine(
                risk_engine=RiskEngine(settings=self.risk_settings),
            ),
            pnl_engine=PnLEngine(),
            initial_balance=request.initial_balance,
            fee_rate=request.fee_rate,
            slippage_rate=request.slippage_rate,
            close_on_opposite_signal=request.close_on_opposite_signal,
        )
        exit_reasons: list[str] = []
        peak_equity = request.initial_balance
        current_drawdown = _DECIMAL_ZERO

        for index, candle in enumerate(ordered_candles):
            close_reason = await self._apply_intrabar_protection(
                candle=candle,
                paper_service=paper_service,
                position_repository=position_repository,
            )
            if close_reason is not None:
                exit_reasons.append(close_reason)
                peak_equity, current_drawdown = await self._equity_state(
                    paper_service=paper_service,
                    initial_balance=request.initial_balance,
                    peak_equity=peak_equity,
                )
            else:
                ptp_reason = await self._apply_partial_take_profit(
                    candle=candle,
                    paper_service=paper_service,
                    position_repository=position_repository,
                )
                if ptp_reason is not None:
                    exit_reasons.append(ptp_reason)
                    peak_equity, current_drawdown = await self._equity_state(
                        paper_service=paper_service,
                        initial_balance=request.initial_balance,
                        peak_equity=peak_equity,
                    )

                await self._advance_stepped_protection(
                    candle=candle,
                    position_repository=position_repository,
                    candles_history=ordered_candles[: index + 1],
                )

            if index + 1 < self.strategy.minimum_candles:
                continue

            window_start = max(0, index + 1 - _STRATEGY_WINDOW)
            if self.strategy_service is not None:
                signal = self.strategy_service.generate_signal(
                    candles=ordered_candles[window_start : index + 1],
                    strategy_type=request.strategy_type,
                )
            else:
                signal = self.strategy.generate_signal(
                    candles=ordered_candles[window_start : index + 1],
                )
            had_position = (
                await position_repository.get_by_symbol(symbol=request.symbol)
                is not None
            )
            volatility_pct = (
                (candle.high_price - candle.low_price) / candle.close_price
                if candle.close_price > _DECIMAL_ZERO
                else None
            )
            execution = await paper_service.execute(
                signal=signal,
                current_drawdown_pct=current_drawdown,
                interval=request.interval,
                volatility_pct=volatility_pct,
            )

            has_position = (
                await position_repository.get_by_symbol(symbol=request.symbol)
                is not None
            )
            if had_position and not has_position and execution.executed:
                exit_reasons.append(execution.reason or "Position closed by signal")
                peak_equity, current_drawdown = await self._equity_state(
                    paper_service=paper_service,
                    initial_balance=request.initial_balance,
                    peak_equity=peak_equity,
                )

        if await position_repository.get_by_symbol(symbol=request.symbol) is not None:
            final_candle = ordered_candles[-1]
            position = await position_repository.get_by_symbol(symbol=request.symbol)
            if position is None:
                raise RuntimeError("Backtest position disappeared during finalization")
            close_signal = Signal(
                symbol=request.symbol,
                signal_type=(
                    SignalType.CLOSE_LONG
                    if position.side is PositionSide.LONG
                    else SignalType.CLOSE_SHORT
                ),
                price=final_candle.close_price,
                confidence=_DECIMAL_ZERO,
                strategy_name="backtest_finalizer",
                generated_at=final_candle.close_time,
                reason="End of backtest range",
            )
            execution = await paper_service.execute(signal=close_signal)
            if execution.executed:
                exit_reasons.append("End of backtest range")

        trade_count = await trade_repository.count(symbol=request.symbol)
        fills = await trade_repository.get_latest(
            limit=max(1, trade_count),
            symbol=request.symbol,
        )
        completed_trades = self._build_completed_trades(
            fills=fills,
            exit_reasons=exit_reasons,
        )
        metrics = self._calculate_metrics(
            request=request,
            trades=completed_trades,
            fills=fills,
        )
        return BacktestResult(
            request=request,
            candle_count=len(ordered_candles),
            trades=completed_trades,
            metrics=metrics,
            warnings=warnings,
        )

    @staticmethod
    async def _apply_intrabar_protection(
        *,
        candle: Candle,
        paper_service: PaperTradingService,
        position_repository: MemoryPositionRepository,
    ) -> str | None:
        """Apply conservative SL-first OHLC protection for an existing position."""
        position = await position_repository.get_by_symbol(symbol=candle.symbol)
        if position is None:
            return None

        trigger_price: Decimal | None = None
        reason: str | None = None
        if position.side is PositionSide.LONG:
            if (
                position.stop_loss is not None
                and candle.low_price <= position.stop_loss
            ):
                trigger_price = min(candle.open_price, position.stop_loss)
                reason = "Paper stop-loss triggered"
            elif (
                position.take_profit is not None
                and candle.high_price >= position.take_profit
            ):
                trigger_price = max(candle.open_price, position.take_profit)
                reason = "Paper take-profit triggered"
        elif position.side is PositionSide.SHORT:
            if (
                position.stop_loss is not None
                and candle.high_price >= position.stop_loss
            ):
                trigger_price = max(candle.open_price, position.stop_loss)
                reason = "Paper stop-loss triggered"
            elif (
                position.take_profit is not None
                and candle.low_price <= position.take_profit
            ):
                trigger_price = min(candle.open_price, position.take_profit)
                reason = "Paper take-profit triggered"

        if trigger_price is None:
            return None

        await paper_service.on_market_tick(
            ticker=Ticker(
                symbol=candle.symbol,
                bid_price=trigger_price,
                ask_price=trigger_price,
                last_price=trigger_price,
                timestamp=candle.open_time + timedelta(microseconds=1),
            )
        )
        still_open = await position_repository.get_by_symbol(symbol=candle.symbol)
        return reason if still_open is None else None

    async def _apply_partial_take_profit(
        self,
        *,
        candle: Candle,
        paper_service: PaperTradingService,
        position_repository: MemoryPositionRepository,
    ) -> str | None:
        """Trigger intrabar partial TP without lookahead if enabled and configured."""
        if not self.risk_settings.partial_tp_enabled:
            return None

        position = await position_repository.get_by_symbol(symbol=candle.symbol)
        if (
            position is None
            or position.partial_tp_executed
            or position.take_profit is None
        ):
            return None

        tp_distance = abs(position.take_profit - position.entry_price)
        if tp_distance <= _DECIMAL_ZERO:
            return None

        favorable_price = (
            candle.high_price
            if position.side is PositionSide.LONG
            else candle.low_price
        )
        progress = RiskEngine.calculate_tp_progress(
            position=position,
            current_price=favorable_price,
        )
        if progress < self.risk_settings.partial_tp_trigger_progress:
            return None

        close_qty = (
            position.quantity * self.risk_settings.partial_tp_ratio
        ).normalize()
        if close_qty <= _DECIMAL_ZERO or close_qty >= position.quantity:
            return None

        if position.side is PositionSide.LONG:
            nominal_trigger = (
                position.entry_price
                + tp_distance * self.risk_settings.partial_tp_trigger_progress
            )
            trigger_price = max(candle.open_price, nominal_trigger)
        else:
            nominal_trigger = (
                position.entry_price
                - tp_distance * self.risk_settings.partial_tp_trigger_progress
            )
            trigger_price = min(candle.open_price, nominal_trigger)

        new_stop: Decimal | None
        new_step: int
        try:
            be_stop = RiskEngine.calculate_stepped_stop_loss(
                position=position,
                step=1,
                breakeven_fee_buffer=self.risk_settings.breakeven_fee_buffer,
            )
            if position.side is PositionSide.LONG:
                new_stop = (
                    be_stop
                    if (position.stop_loss is None or be_stop > position.stop_loss)
                    else position.stop_loss
                )
            else:
                new_stop = (
                    be_stop
                    if (position.stop_loss is None or be_stop < position.stop_loss)
                    else position.stop_loss
                )
            new_step = max(position.protection_step, 1)
        except ValueError as err:
            _LOGGER.warning(
                "Backtest cannot calculate BE stop after partial TP for %s: %s. "
                "Retaining current stop.",
                position.symbol,
                err,
            )
            new_stop = position.stop_loss
            new_step = position.protection_step

        result = await paper_service.execute_partial_close(
            symbol=position.symbol,
            close_quantity=close_qty,
            reference_price=trigger_price,
            new_stop_loss=new_stop,
            new_protection_step=new_step,
            executed_at=candle.open_time + timedelta(microseconds=2),
            reason="Partial take-profit triggered",
        )
        if result is not None and result.executed:
            return "Partial take-profit triggered"
        return None

    async def _advance_stepped_protection(
        self,
        *,
        candle: Candle,
        position_repository: MemoryPositionRepository,
        candles_history: Sequence[Candle] = (),
    ) -> None:
        """Arm stepped SL & trailing stop from this candle for next candle."""
        position = await position_repository.get_by_symbol(symbol=candle.symbol)
        if position is None or position.take_profit is None:
            return

        if not self.risk_settings.stepped_stop_enabled:
            return

        tp_distance = abs(position.take_profit - position.entry_price)
        step = position.protection_step

        if tp_distance > _DECIMAL_ZERO:
            current_price = (
                candle.high_price
                if position.side is PositionSide.LONG
                else candle.low_price
            )
            progress = RiskEngine.calculate_tp_progress(
                position=position,
                current_price=current_price,
            )
            roi = RiskEngine.calculate_position_roi(
                position=position,
                current_price=current_price,
            )
            resolved_step = RiskEngine.resolve_target_protection_step(
                progress=progress,
                roi=roi,
                breakeven_roi_threshold=self.risk_settings.breakeven_roi_threshold,
                breakeven_progress_threshold=self.risk_settings.breakeven_progress_threshold,
                thresholds=self.risk_settings.stepped_stop_thresholds,
            )
            if resolved_step > position.protection_step:
                step = resolved_step

        stepped_stop: Decimal | None = None
        if step > 0:
            try:
                stepped_stop = RiskEngine.calculate_stepped_stop_loss(
                    position=position,
                    step=step,
                    thresholds=self.risk_settings.stepped_stop_thresholds,
                    locked_lag=self.risk_settings.stepped_stop_locked_lag,
                    breakeven_fee_buffer=self.risk_settings.breakeven_fee_buffer,
                )
            except ValueError as err:
                _LOGGER.warning(
                    "Backtest cannot calculate stepped stop loss for %s step %s: %s",
                    position.symbol,
                    step,
                    err,
                )

        is_pier = position.strategy_type is StrategyType.PINBAR_ENGULFING_EMA_RSI
        eff_trailing_mode = (
            self.risk_settings.pier_trailing_mode
            if (is_pier and self.risk_settings.pier_trailing_mode is not None)
            else self.risk_settings.trailing_mode
        )
        eff_swing_window = (
            self.risk_settings.pier_trailing_swing_window
            if (is_pier and self.risk_settings.pier_trailing_swing_window is not None)
            else self.risk_settings.trailing_swing_window
        )
        eff_buffer_pct = (
            self.risk_settings.pier_trailing_buffer_pct
            if (is_pier and self.risk_settings.pier_trailing_buffer_pct is not None)
            else self.risk_settings.trailing_buffer_pct
        )

        replacement_stop: Decimal | None = None
        new_step = position.protection_step

        if eff_trailing_mode is TrailingMode.SWING_PIVOT and candles_history:
            swing_stop = RiskEngine.calculate_swing_pivot_stop_loss(
                position=position,
                candles=candles_history,
                window=eff_swing_window,
                buffer_pct=eff_buffer_pct,
            )
            if swing_stop is not None:
                # Enforce Breakeven floor if position reached BE threshold
                if step >= 1:
                    try:
                        be_stop = RiskEngine.calculate_stepped_stop_loss(
                            position=position,
                            step=1,
                            thresholds=self.risk_settings.stepped_stop_thresholds,
                            locked_lag=self.risk_settings.stepped_stop_locked_lag,
                            breakeven_fee_buffer=self.risk_settings.breakeven_fee_buffer,
                        )
                        if position.side is PositionSide.LONG:
                            replacement_stop = (
                                be_stop if swing_stop < be_stop else swing_stop
                            )
                        else:
                            replacement_stop = (
                                be_stop if swing_stop > be_stop else swing_stop
                            )
                    except ValueError:
                        replacement_stop = swing_stop
                else:
                    replacement_stop = swing_stop
                new_step = position.protection_step + 1
            elif stepped_stop is not None:
                replacement_stop = stepped_stop
                new_step = step
            else:
                return
        else:
            if stepped_stop is None:
                return
            replacement_stop = stepped_stop
            new_step = step

        if position.side is PositionSide.LONG:
            if position.stop_loss is not None:
                if replacement_stop < position.stop_loss:
                    return
                if (
                    replacement_stop == position.stop_loss
                    and new_step <= position.protection_step
                ):
                    return
        else:
            if position.stop_loss is not None:
                if replacement_stop > position.stop_loss:
                    return
                if (
                    replacement_stop == position.stop_loss
                    and new_step <= position.protection_step
                ):
                    return

        await position_repository.update(
            position=replace(
                position,
                stop_loss=replacement_stop,
                protection_step=new_step,
                updated_at=candle.close_time,
            )
        )

    @staticmethod
    async def _equity_state(
        *,
        paper_service: PaperTradingService,
        initial_balance: Decimal,
        peak_equity: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Return updated realized-equity peak and drawdown ratio."""
        equity = initial_balance + await paper_service.get_realized_pnl()
        updated_peak = max(peak_equity, equity)
        drawdown = (
            (updated_peak - equity) / updated_peak
            if updated_peak > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        return updated_peak, drawdown

    @staticmethod
    def _build_completed_trades(
        *,
        fills: Sequence[Trade],
        exit_reasons: Sequence[str],
    ) -> tuple[BacktestTrade, ...]:
        """Pair entry and exit fills into completed position records."""
        completed: list[BacktestTrade] = []
        entry: Trade | None = None
        entry_remaining_qty = _DECIMAL_ZERO
        entry_original_qty = _DECIMAL_ZERO
        reason_index = 0

        for fill in fills:
            if fill.realized_pnl is None:
                entry = fill
                entry_original_qty = fill.quantity
                entry_remaining_qty = fill.quantity
                continue
            if entry is None:
                raise RuntimeError("Backtest exit fill has no matching entry fill")

            reason = (
                exit_reasons[reason_index]
                if reason_index < len(exit_reasons)
                else "Position closed"
            )
            fee_fraction = (
                min(fill.quantity / entry_original_qty, Decimal("1"))
                if entry_original_qty > _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            allocated_entry_fee = entry.fee * fee_fraction

            completed.append(
                BacktestTrade(
                    side=(
                        PositionSide.LONG
                        if entry.side is OrderSide.BUY
                        else PositionSide.SHORT
                    ),
                    entry_time=entry.executed_at,
                    exit_time=fill.executed_at,
                    entry_price=entry.price,
                    exit_price=fill.price,
                    quantity=fill.quantity,
                    fees=allocated_entry_fee + fill.fee,
                    realized_pnl=fill.realized_pnl,
                    reason=reason,
                )
            )
            entry_remaining_qty -= fill.quantity
            reason_index += 1
            if entry_remaining_qty <= _DECIMAL_ZERO:
                entry = None

        if entry is not None:
            raise RuntimeError("Backtest finished with an unmatched entry fill")
        return tuple(completed)

    @staticmethod
    def _calculate_metrics(
        *,
        request: BacktestRequest,
        trades: Sequence[BacktestTrade],
        fills: Sequence[Trade],
    ) -> BacktestMetrics:
        """Calculate deterministic realized-equity performance metrics."""
        net_pnl = sum((trade.realized_pnl for trade in trades), start=_DECIMAL_ZERO)
        final_balance = request.initial_balance + net_pnl
        winning = tuple(trade for trade in trades if trade.realized_pnl > 0)
        losing = tuple(trade for trade in trades if trade.realized_pnl < 0)
        gross_profit = sum(
            (trade.realized_pnl for trade in winning),
            start=_DECIMAL_ZERO,
        )
        gross_loss = abs(
            sum((trade.realized_pnl for trade in losing), start=_DECIMAL_ZERO)
        )
        peak = request.initial_balance
        equity = request.initial_balance
        max_drawdown = _DECIMAL_ZERO
        for trade in trades:
            equity += trade.realized_pnl
            peak = max(peak, equity)
            if peak > _DECIMAL_ZERO:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)

        trade_total = len(trades)
        return BacktestMetrics(
            initial_balance=request.initial_balance,
            final_balance=final_balance,
            net_pnl=net_pnl,
            return_pct=(net_pnl / request.initial_balance) * _DECIMAL_HUNDRED,
            total_trades=trade_total,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate_pct=(
                Decimal(len(winning)) / Decimal(trade_total) * _DECIMAL_HUNDRED
                if trade_total > 0
                else _DECIMAL_ZERO
            ),
            profit_factor=(gross_profit / gross_loss if gross_loss > 0 else None),
            max_drawdown_pct=max_drawdown * _DECIMAL_HUNDRED,
            total_fees=sum((fill.fee for fill in fills), start=_DECIMAL_ZERO),
            long_trades=sum(1 for trade in trades if trade.side is PositionSide.LONG),
            short_trades=sum(1 for trade in trades if trade.side is PositionSide.SHORT),
        )

    def _validate_candles(
        self,
        *,
        request: BacktestRequest,
        candles: Sequence[Candle],
    ) -> tuple[tuple[Candle, ...], tuple[str, ...]]:
        """Validate replay ordering and report historical-data gaps."""
        if request.interval is Interval.MN1:
            raise ValueError("Monthly candle backtests are not supported yet")
        if not candles:
            raise ValueError("Backtest requires historical candles")

        ordered = tuple(candles)
        if len(ordered) < self.strategy.minimum_candles:
            raise ValueError(
                f"Backtest requires at least {self.strategy.minimum_candles} candles"
            )
        if any(candle.symbol.upper() != request.symbol for candle in ordered):
            raise ValueError("Backtest candles must match the requested symbol")
        if any(candle.interval is not request.interval for candle in ordered):
            raise ValueError("Backtest candles must match the requested interval")
        if any(
            previous.open_time >= current.open_time
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("Backtest candles must be strictly chronological")

        expected_seconds = request.interval.seconds
        gap_count = sum(
            1
            for previous, current in zip(ordered, ordered[1:], strict=False)
            if int((current.open_time - previous.open_time).total_seconds())
            != expected_seconds
        )
        warnings: list[str] = [_PROTECTION_WARNING]
        if gap_count > 0:
            warnings.append(f"Historical data contains {gap_count} candle gap(s)")
        return ordered, tuple(warnings)
