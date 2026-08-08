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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.pnl_engine import PnLEngine
from botragram.engine.risk_engine import RiskEngine
from botragram.engine.signal_engine import SignalEngine
from botragram.engine.trading_engine import TradingEngine
from botragram.enums import Interval, OrderSide, PositionSide, SignalType
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
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")
_STRATEGY_WINDOW: Final[int] = 500
_PROTECTION_WARNING: Final[str] = (
    "Stepped SL+ is not simulated; only baseline SL/TP and strategy exits apply"
)


# =============================================================================
# Backtest Engine
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class BacktestEngine:
    """Replay historical candles through the production PAPER execution path."""

    strategy: BaseStrategy
    risk_settings: RiskSettings

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
        )
        signal_engine = SignalEngine(strategy=self.strategy)
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

            if index + 1 < self.strategy.minimum_candles:
                continue

            window_start = max(0, index + 1 - _STRATEGY_WINDOW)
            signal = signal_engine.generate(
                candles=ordered_candles[window_start : index + 1],
            )
            had_position = (
                await position_repository.get_by_symbol(symbol=request.symbol)
                is not None
            )
            execution = await paper_service.execute(
                signal=signal,
                current_drawdown_pct=current_drawdown,
                interval=request.interval,
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
        reason_index = 0

        for fill in fills:
            if fill.realized_pnl is None:
                entry = fill
                continue
            if entry is None:
                raise RuntimeError("Backtest exit fill has no matching entry fill")

            reason = (
                exit_reasons[reason_index]
                if reason_index < len(exit_reasons)
                else "Position closed"
            )
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
                    fees=entry.fee + fill.fee,
                    realized_pnl=fill.realized_pnl,
                    reason=reason,
                )
            )
            entry = None
            reason_index += 1

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
