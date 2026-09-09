"""
Botragram

Description:
    Comparative backtest execution comparing baseline vs enhanced risk controls.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

import math

# =============================================================================
# Standard Library Imports
# =============================================================================
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.backtest_engine import BacktestEngine
from botragram.models import (
    BacktestRequest,
    BacktestResult,
    BacktestTrade,
    Candle,
)
from botragram.strategies.base import BaseStrategy

__all__ = [
    "ComparativeBacktestResult",
    "ComparativeBacktestService",
    "calculate_sharpe_ratio",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")


def calculate_sharpe_ratio(trades: Sequence[BacktestTrade]) -> Decimal:
    """Calculate sample per-trade Sharpe ratio from realized trade returns."""
    if len(trades) < 2:
        return _DECIMAL_ZERO

    returns: list[Decimal] = []
    for trade in trades:
        notional = trade.entry_price * trade.quantity
        if notional > _DECIMAL_ZERO:
            returns.append(trade.realized_pnl / notional)

    if len(returns) < 2:
        return _DECIMAL_ZERO

    count = Decimal(len(returns))
    mean_return = sum(returns, _DECIMAL_ZERO) / count

    squared_diff_sum = sum((r - mean_return) ** 2 for r in returns)
    variance = squared_diff_sum / (count - Decimal("1"))
    if variance <= _DECIMAL_ZERO:
        return _DECIMAL_ZERO

    std_dev = Decimal(str(math.sqrt(float(variance))))
    if std_dev <= _DECIMAL_ZERO:
        return _DECIMAL_ZERO

    return (mean_return / std_dev).quantize(Decimal("0.001"))


@dataclass(slots=True, kw_only=True, frozen=True)
class ComparativeBacktestResult:
    """Detailed side-by-side performance comparison."""

    request: BacktestRequest
    candle_count: int
    baseline_result: BacktestResult
    enhanced_result: BacktestResult
    baseline_sharpe: Decimal
    enhanced_sharpe: Decimal
    pnl_delta_usdt: Decimal
    pnl_delta_pct: Decimal
    max_drawdown_reduction_pct: Decimal
    summary_report: str


@dataclass(slots=True, kw_only=True, frozen=True)
class ComparativeBacktestService:
    """Run dual backtest passes comparing baseline vs trailing/volatility sizing."""

    strategy: BaseStrategy
    base_risk_settings: RiskSettings

    async def run(
        self,
        *,
        request: BacktestRequest,
        candles: Sequence[Candle],
        trailing_stop_trigger_pct: Decimal = Decimal("0.015"),
        trailing_stop_distance_pct: Decimal = Decimal("0.008"),
        baseline_volatility_pct: Decimal = Decimal("0.02"),
    ) -> ComparativeBacktestResult:
        """Execute baseline and enhanced backtests on identical candle inputs."""
        # Pass 1: Baseline (both features disabled)
        baseline_settings = replace(
            self.base_risk_settings,
            trailing_stop_enabled=False,
            volatility_sizing_enabled=False,
        )
        baseline_engine = BacktestEngine(
            strategy=self.strategy,
            risk_settings=baseline_settings,
        )
        baseline_result = await baseline_engine.run(
            request=request,
            candles=candles,
        )

        # Pass 2: Enhanced (trailing stop + volatility sizing enabled)
        enhanced_settings = replace(
            self.base_risk_settings,
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=trailing_stop_trigger_pct,
            trailing_stop_distance_pct=trailing_stop_distance_pct,
            volatility_sizing_enabled=True,
            baseline_volatility_pct=baseline_volatility_pct,
        )
        enhanced_engine = BacktestEngine(
            strategy=self.strategy,
            risk_settings=enhanced_settings,
        )
        enhanced_result = await enhanced_engine.run(
            request=request,
            candles=candles,
        )

        # Calculate comparative metrics
        base_sharpe = calculate_sharpe_ratio(baseline_result.trades)
        enh_sharpe = calculate_sharpe_ratio(enhanced_result.trades)

        pnl_delta_usdt = enhanced_result.metrics.net_pnl - (
            baseline_result.metrics.net_pnl
        )
        pnl_delta_pct = enhanced_result.metrics.return_pct - (
            baseline_result.metrics.return_pct
        )
        dd_reduction = (
            baseline_result.metrics.max_drawdown_pct
            - enhanced_result.metrics.max_drawdown_pct
        )

        summary_report = self._format_summary_report(
            request=request,
            baseline_result=baseline_result,
            enhanced_result=enhanced_result,
            baseline_sharpe=base_sharpe,
            enhanced_sharpe=enh_sharpe,
            pnl_delta_usdt=pnl_delta_usdt,
            pnl_delta_pct=pnl_delta_pct,
            max_drawdown_reduction_pct=dd_reduction,
        )

        return ComparativeBacktestResult(
            request=request,
            candle_count=len(candles),
            baseline_result=baseline_result,
            enhanced_result=enhanced_result,
            baseline_sharpe=base_sharpe,
            enhanced_sharpe=enh_sharpe,
            pnl_delta_usdt=pnl_delta_usdt,
            pnl_delta_pct=pnl_delta_pct,
            max_drawdown_reduction_pct=dd_reduction,
            summary_report=summary_report,
        )

    @staticmethod
    def _format_summary_report(
        *,
        request: BacktestRequest,
        baseline_result: BacktestResult,
        enhanced_result: BacktestResult,
        baseline_sharpe: Decimal,
        enhanced_sharpe: Decimal,
        pnl_delta_usdt: Decimal,
        pnl_delta_pct: Decimal,
        max_drawdown_reduction_pct: Decimal,
    ) -> str:
        """Format an informative markdown table comparing both configurations."""
        b_m = baseline_result.metrics
        e_m = enhanced_result.metrics

        lines = [
            f"📊 **Comparative Backtest: {request.symbol} "
            f"({request.strategy_type.value})**",
            "",
            "| Metrik | Baseline (Tanpa Fitur) | Enhanced (Trailing+Vol) | Perubahan |",
            "| :--- | :--- | :--- | :--- |",
            (
                f"| **Net PnL** | `${b_m.net_pnl:,.2f}` | `${e_m.net_pnl:,.2f}` | "
                f"`{'+' if pnl_delta_usdt >= _DECIMAL_ZERO else ''}"
                f"${pnl_delta_usdt:,.2f}` |"
            ),
            (
                f"| **Return %** | `{b_m.return_pct:.2f}%` | `{e_m.return_pct:.2f}%` | "
                f"`{'+' if pnl_delta_pct >= _DECIMAL_ZERO else ''}"
                f"{pnl_delta_pct:.2f}%` |"
            ),
            f"| **Win Rate** | `{b_m.win_rate_pct:.2f}%` | `{e_m.win_rate_pct:.2f}%` | "
            f"`{e_m.win_rate_pct - b_m.win_rate_pct:+.2f}%` |",
            f"| **Max Drawdown** | `{b_m.max_drawdown_pct:.2f}%` | "
            f"`{e_m.max_drawdown_pct:.2f}%` | "
            f"`{-max_drawdown_reduction_pct:+.2f}%` |",
            f"| **Sharpe Ratio** | `{baseline_sharpe:.3f}` | `{enhanced_sharpe:.3f}` | "
            f"`{enhanced_sharpe - baseline_sharpe:+.3f}` |",
            f"| **Total Trades** | `{b_m.total_trades}` | `{e_m.total_trades}` | "
            f"`{e_m.total_trades - b_m.total_trades:+d}` |",
            f"| **Profit Factor** | `{b_m.profit_factor or _DECIMAL_ZERO:.2f}` | "
            f"`{e_m.profit_factor or _DECIMAL_ZERO:.2f}` | - |",
            "",
        ]
        return "\n".join(lines)
