"""
Botragram

Description:
    Manual top 10 coins comparative backtest runner for the upgraded
    PIER strategy (Pinbar + Engulfing + Morning/Evening Star + Parabolic SAR)
    against the baseline (Pinbar + Engulfing only).

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
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.constants import BYBIT_REST_BASE_URL
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import ExchangeType, Interval, MarketType, StrategyType
from botragram.exchanges import ExchangeFactory
from botragram.models import BacktestRequest
from botragram.services.backtest_service import BacktestService
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy

TOP_10_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
)

_DECIMAL_ZERO: Decimal = Decimal("0")


@dataclass(slots=True, kw_only=True, frozen=True)
class UpgradeComparisonSummary:
    symbol: str
    candle_count: int
    base_trades: int
    upg_trades: int
    base_win_rate: Decimal
    upg_win_rate: Decimal
    base_pnl: Decimal
    upg_pnl: Decimal
    pnl_delta: Decimal
    base_fees: Decimal
    upg_fees: Decimal
    base_drawdown: Decimal
    upg_drawdown: Decimal


async def run_upgraded_pier_top10_backtest() -> list[UpgradeComparisonSummary]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=14)

    rest_client = ExchangeFactory.create_rest_client(
        exchange_type=ExchangeType.BYBIT,
        base_url=BYBIT_REST_BASE_URL,
    )
    exchange_client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BYBIT,
        rest_client=rest_client,
        market_type=MarketType.FUTURES,
    )

    await exchange_client.connect()
    summaries: list[UpgradeComparisonSummary] = []

    try:
        # Baseline Strategy: Star patterns and Parabolic SAR disabled
        base_strat = PinbarEngulfingEmaRsiStrategy(
            trend_period=100,
            pullback_period=21,
            rsi_period=14,
            volume_period=20,
            volume_multiplier=Decimal("1.05"),
            include_star_patterns=False,
            use_parabolic_sar=False,
        )

        # Upgraded Strategy: Star patterns and Parabolic SAR enabled
        upg_strat = PinbarEngulfingEmaRsiStrategy(
            trend_period=100,
            pullback_period=21,
            rsi_period=14,
            volume_period=20,
            volume_multiplier=Decimal("1.05"),
            include_star_patterns=True,
            use_parabolic_sar=True,
        )

        # Shared Risk Settings with Fee-Optimized Dynamic Tiered Trailing Stop
        shared_risk = RiskSettings(
            leverage=5,
            stop_loss_pct=Decimal("0.012"),
            take_profit_pct=Decimal("0.024"),
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.015"),
            trailing_stop_distance_pct=Decimal("0.006"),
            trailing_stop_tier2_trigger_pct=Decimal("0.022"),
            trailing_stop_tier2_distance_pct=Decimal("0.0035"),
            trailing_stop_tier3_trigger_pct=Decimal("0.035"),
            trailing_stop_tier3_distance_pct=Decimal("0.0020"),
            volatility_sizing_enabled=True,
            baseline_volatility_pct=Decimal("0.015"),
        )

        base_engine = BacktestEngine(strategy=base_strat, risk_settings=shared_risk)
        upg_engine = BacktestEngine(strategy=upg_strat, risk_settings=shared_risk)

        dummy_engine = BacktestEngine(strategy=base_strat, risk_settings=shared_risk)
        bt_service = BacktestService(
            exchange_client=exchange_client, engine=dummy_engine
        )

        print("\n=== Multi-Coin Backtest: PIER Strategy Upgrade Comparison (15m) ===")
        print(
            "Comparing: Baseline (Pinbar+Engulfing) vs Upgraded "
            "(+ Morning/Evening Star & Parabolic SAR)\n"
        )

        for idx, symbol in enumerate(TOP_10_SYMBOLS, start=1):
            print(f"[{idx}/10] Testing {symbol} (15m)...", end=" ", flush=True)

            req = BacktestRequest(
                symbol=symbol,
                interval=Interval.M15,
                strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
                market_type=MarketType.FUTURES,
                start_time=start,
                end_time=now,
                initial_balance=Decimal("10000"),
                fee_rate=Decimal("0.0006"),
                slippage_rate=Decimal("0.0002"),
                max_candles=1000,
            )

            try:
                candles = await bt_service.load_candles(request=req)
                if not candles:
                    print("SKIP (no candles)")
                    continue

                b_res = await base_engine.run(request=req, candles=candles)
                u_res = await upg_engine.run(request=req, candles=candles)

                bm = b_res.metrics
                um = u_res.metrics
                pnl_delta = um.net_pnl - bm.net_pnl

                summary = UpgradeComparisonSummary(
                    symbol=symbol,
                    candle_count=len(candles),
                    base_trades=bm.total_trades,
                    upg_trades=um.total_trades,
                    base_win_rate=bm.win_rate_pct,
                    upg_win_rate=um.win_rate_pct,
                    base_pnl=bm.net_pnl,
                    upg_pnl=um.net_pnl,
                    pnl_delta=pnl_delta,
                    base_fees=bm.total_fees,
                    upg_fees=um.total_fees,
                    base_drawdown=bm.max_drawdown_pct,
                    upg_drawdown=um.max_drawdown_pct,
                )
                summaries.append(summary)

                delta_str = (
                    f"+${pnl_delta:.2f}"
                    if pnl_delta >= _DECIMAL_ZERO
                    else f"-${abs(pnl_delta):.2f}"
                )
                print(
                    f"Done ({len(candles)} candles). "
                    f"Trades: {bm.total_trades} -> {um.total_trades} | "
                    f"WinRate: {bm.win_rate_pct:.1f}% -> {um.win_rate_pct:.1f}% | "
                    f"PnL Delta: {delta_str}"
                )

            except Exception as e:
                print(f"FAILED ({e})")

    finally:
        await exchange_client.close()

    _print_comparison_table(summaries)
    return summaries


def _print_comparison_table(summaries: list[UpgradeComparisonSummary]) -> None:
    if not summaries:
        print("\nNo successful backtests to report.")
        return

    header_part1 = f"{'Symbol':<10} | {'Candles':<7} | {'Trades (B->U)':<15} | "
    header_part2 = (
        f"{'WinRate (B->U)':<16} | {'Base PnL':<12} | {'Upg PnL':<12} | "
        f"{'PnL Delta':<12}"
    )
    print(header_part1 + header_part2)
    print("=" * 105)

    tot_base_trades = 0
    tot_upg_trades = 0
    tot_base_pnl = _DECIMAL_ZERO
    tot_upg_pnl = _DECIMAL_ZERO

    for s in summaries:
        tot_base_trades += s.base_trades
        tot_upg_trades += s.upg_trades
        tot_base_pnl += s.base_pnl
        tot_upg_pnl += s.upg_pnl

        trade_str = f"{s.base_trades} -> {s.upg_trades}"
        wr_str = f"{s.base_win_rate:.1f}% -> {s.upg_win_rate:.1f}%"
        delta_str = (
            f"+${s.pnl_delta:.2f}"
            if s.pnl_delta >= _DECIMAL_ZERO
            else f"-${abs(s.pnl_delta):.2f}"
        )

        row_part1 = f"{s.symbol:<10} | {s.candle_count:<7} | {trade_str:<15} | "
        row_part2 = (
            f"{wr_str:<16} | ${s.base_pnl:<11.2f} | ${s.upg_pnl:<11.2f} | "
            f"{delta_str:<12}"
        )
        print(row_part1 + row_part2)

    tot_delta = tot_upg_pnl - tot_base_pnl
    tot_delta_str = (
        f"+${tot_delta:.2f}"
        if tot_delta >= _DECIMAL_ZERO
        else f"-${abs(tot_delta):.2f}"
    )

    print("=" * 105)
    tot_trade_str = f"{tot_base_trades} -> {tot_upg_trades}"
    tot_str1 = f"{'TOTAL':<10} | {'-':<7} | {tot_trade_str:<15} | "
    tot_str2 = (
        f"{'-':<16} | ${tot_base_pnl:<11.2f} | ${tot_upg_pnl:<11.2f} | "
        f"{tot_delta_str:<12}"
    )
    print(tot_str1 + tot_str2)
    print("=" * 105)


if __name__ == "__main__":
    asyncio.run(run_upgraded_pier_top10_backtest())
