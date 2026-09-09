"""
Botragram

Description:
    Manual top 10 coins comparative backtest runner evaluating baseline
    vs trailing stop & volatility sizing on historical Bybit market data.

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
from botragram.config.strategy_settings import StrategySettings
from botragram.constants import BYBIT_REST_BASE_URL
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import ExchangeType, Interval, MarketType, StrategyType
from botragram.exchanges import ExchangeFactory
from botragram.models import BacktestRequest
from botragram.services.backtest_service import BacktestService
from botragram.services.comparative_backtest_service import (
    ComparativeBacktestResult,
    ComparativeBacktestService,
)
from botragram.strategies import StrategyFactory

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
class SymbolBacktestSummary:
    symbol: str
    candle_count: int
    base_trades: int
    enh_trades: int
    base_win_rate: Decimal
    enh_win_rate: Decimal
    base_pnl: Decimal
    enh_pnl: Decimal
    pnl_delta: Decimal
    base_drawdown: Decimal
    enh_drawdown: Decimal
    base_sharpe: Decimal
    enh_sharpe: Decimal


async def run_top10_backtest(
    *,
    days: int = 14,
    interval: Interval = Interval.M5,
    strategy_type: StrategyType = StrategyType.EMA_SCALPING,
    trailing_trigger: Decimal = Decimal("0.008"),
    trailing_distance: Decimal = Decimal("0.004"),
) -> list[SymbolBacktestSummary]:
    """Execute dual backtest runs across top 10 market cap futures symbols."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

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
    summaries: list[SymbolBacktestSummary] = []

    try:
        strat_settings = StrategySettings(strategy_type=strategy_type)
        strategy = StrategyFactory.create(settings=strat_settings)
        risk_settings = RiskSettings(leverage=5)

        dummy_engine = BacktestEngine(strategy=strategy, risk_settings=risk_settings)
        bt_service = BacktestService(
            exchange_client=exchange_client,
            engine=dummy_engine,
        )
        comp_service = ComparativeBacktestService(
            strategy=strategy,
            base_risk_settings=risk_settings,
        )

        print(
            f"=== Running Top 10 Comparative Backtest ({strategy_type.value}, "
            f"{days} Days, {interval.value}) ==="
        )
        print(
            f"Period: {start.strftime('%Y-%m-%d %H:%M')} -> "
            f"{now.strftime('%Y-%m-%d %H:%M')} UTC\n"
        )

        for idx, symbol in enumerate(TOP_10_SYMBOLS, start=1):
            print(f"[{idx}/10] Testing {symbol}...", end=" ", flush=True)

            req = BacktestRequest(
                symbol=symbol,
                interval=interval,
                strategy_type=strategy_type,
                market_type=MarketType.FUTURES,
                start_time=start,
                end_time=now,
                initial_balance=Decimal("10000"),
                fee_rate=Decimal("0.0006"),
                slippage_rate=Decimal("0.0002"),
                max_candles=10000,
            )

            try:
                candles = await bt_service.load_candles(request=req)
                if not candles:
                    print("SKIP (No candle data)")
                    continue

                res: ComparativeBacktestResult = await comp_service.run(
                    request=req,
                    candles=candles,
                    trailing_stop_trigger_pct=trailing_trigger,
                    trailing_stop_distance_pct=trailing_distance,
                )

                b_m = res.baseline_result.metrics
                e_m = res.enhanced_result.metrics

                summary = SymbolBacktestSummary(
                    symbol=symbol,
                    candle_count=len(candles),
                    base_trades=b_m.total_trades,
                    enh_trades=e_m.total_trades,
                    base_win_rate=b_m.win_rate_pct,
                    enh_win_rate=e_m.win_rate_pct,
                    base_pnl=b_m.net_pnl,
                    enh_pnl=e_m.net_pnl,
                    pnl_delta=res.pnl_delta_usdt,
                    base_drawdown=b_m.max_drawdown_pct,
                    enh_drawdown=e_m.max_drawdown_pct,
                    base_sharpe=res.baseline_sharpe,
                    enh_sharpe=res.enhanced_sharpe,
                )
                summaries.append(summary)

                delta_sign = "+" if summary.pnl_delta >= _DECIMAL_ZERO else ""
                print(
                    f"DONE ({len(candles)} candles) | "
                    f"Base PnL: ${b_m.net_pnl:.2f} -> Enh PnL: ${e_m.net_pnl:.2f} "
                    f"({delta_sign}${summary.pnl_delta:.2f})"
                )
            except Exception as exc:
                print(f"ERROR: {exc}")

    finally:
        await exchange_client.close()

    return summaries


def format_portfolio_report(
    summaries: list[SymbolBacktestSummary],
    strategy_name: str = "EMA Scalping",
) -> str:
    """Format aggregate comparative backtest results into markdown report."""
    if not summaries:
        return "No backtest results available."

    total_base_pnl = sum((s.base_pnl for s in summaries), _DECIMAL_ZERO)
    total_enh_pnl = sum((s.enh_pnl for s in summaries), _DECIMAL_ZERO)
    total_pnl_delta = total_enh_pnl - total_base_pnl

    total_base_trades = sum(s.base_trades for s in summaries)
    total_enh_trades = sum(s.enh_trades for s in summaries)

    count = Decimal(len(summaries))
    avg_base_wr = sum((s.base_win_rate for s in summaries), _DECIMAL_ZERO) / count
    avg_enh_wr = sum((s.enh_win_rate for s in summaries), _DECIMAL_ZERO) / count
    avg_base_dd = sum((s.base_drawdown for s in summaries), _DECIMAL_ZERO) / count
    avg_enh_dd = sum((s.enh_drawdown for s in summaries), _DECIMAL_ZERO) / count

    lines: list[str] = [
        f"## 📊 Laporan Hasil Backtest Komparatif Top 10 Koin ({strategy_name})",
        "",
        "### 1. Ringkasan Performa Portofolio (10 Koin Teratas)",
        "| Metrik Portofolio | Baseline (Tanpa Trailing) | "
        "Enhanced (Trailing+Vol Sizing) | Selisih Perubahan |",
        "| :--- | :--- | :--- | :--- |",
        (
            f"| **Total Net PnL** | `${total_base_pnl:,.2f}` | "
            f"`${total_enh_pnl:,.2f}` | "
            f"**`{'+' if total_pnl_delta >= _DECIMAL_ZERO else ''}"
            f"${total_pnl_delta:,.2f}`** |"
        ),
        (
            f"| **Rata-rata Win Rate** | `{avg_base_wr:.2f}%` | `{avg_enh_wr:.2f}%` | "
            f"`{avg_enh_wr - avg_base_wr:+.2f}%` |"
        ),
        (
            f"| **Rata-rata Max Drawdown** | `{avg_base_dd:.2f}%` | "
            f"`{avg_enh_dd:.2f}%` | `{avg_enh_dd - avg_base_dd:+.2f}%` |"
        ),
        (
            f"| **Total Eksekusi Trade** | `{total_base_trades}` | "
            f"`{total_enh_trades}` | `{total_enh_trades - total_base_trades:+d}` |"
        ),
        "",
        "### 2. Rincian Hasil Per Simbol",
        "| Simbol | Lilin | Base PnL | Enh PnL | PnL Delta | "
        "Base Win Rate | Enh Win Rate | Base Max DD | Enh Max DD |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for s in summaries:
        delta_str = f"{'+' if s.pnl_delta >= _DECIMAL_ZERO else ''}${s.pnl_delta:.2f}"
        lines.append(
            f"| **{s.symbol}** | {s.candle_count} | ${s.base_pnl:.2f} | "
            f"${s.enh_pnl:.2f} | **`{delta_str}`** | {s.base_win_rate:.1f}% | "
            f"{s.enh_win_rate:.1f}% | {s.base_drawdown:.2f}% | "
            f"{s.enh_drawdown:.2f}% |"
        )

    return "\n".join(lines)


async def main() -> None:
    strat = StrategyType.EMA_SCALPING
    summaries = await run_top10_backtest(
        days=14,
        interval=Interval.M5,
        strategy_type=strat,
    )
    report = format_portfolio_report(summaries, strategy_name="EMA Scalping")
    from pathlib import Path

    out_file = Path("backtest_top10_ema_scalping_report.md")
    out_file.write_text(report, encoding="utf-8")
    print(f"\nReport successfully saved to {out_file.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
