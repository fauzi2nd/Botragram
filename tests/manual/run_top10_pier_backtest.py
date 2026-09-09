"""
Botragram

Description:
    Manual top 10 coins comparative backtest runner for the new
    Pinbar + Engulfing EMA-RSI Pullback strategy on 15m timeframe.

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
from pathlib import Path

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
class PierBacktestSummary:
    symbol: str
    candle_count: int
    base_trades: int
    enh_trades: int
    base_win_rate: Decimal
    enh_win_rate: Decimal
    base_pnl: Decimal
    enh_pnl: Decimal
    pnl_delta: Decimal
    base_fees: Decimal
    enh_fees: Decimal
    base_drawdown: Decimal
    enh_drawdown: Decimal


async def run_pier_top10_backtest() -> list[PierBacktestSummary]:
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
    summaries: list[PierBacktestSummary] = []

    try:
        # Use trend_period=100 to fit comfortably within 1000 15m candles
        strat = PinbarEngulfingEmaRsiStrategy(
            trend_period=100,
            pullback_period=21,
            rsi_period=14,
            volume_period=20,
            volume_multiplier=Decimal("1.05"),
        )

        # Baseline: Fixed SL 1.2%, TP 2.4% (RR 1:2.0)
        base_risk = RiskSettings(
            leverage=5,
            stop_loss_pct=Decimal("0.012"),
            take_profit_pct=Decimal("0.024"),
            trailing_stop_enabled=False,
            volatility_sizing_enabled=False,
        )

        # Enhanced: Dynamic Trailing Stop (trigger 1.2%, distance 0.6%)
        enh_risk = RiskSettings(
            leverage=5,
            stop_loss_pct=Decimal("0.012"),
            take_profit_pct=Decimal("0.024"),
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.012"),
            trailing_stop_distance_pct=Decimal("0.006"),
            volatility_sizing_enabled=True,
            baseline_volatility_pct=Decimal("0.015"),
        )

        base_engine = BacktestEngine(strategy=strat, risk_settings=base_risk)
        enh_engine = BacktestEngine(strategy=strat, risk_settings=enh_risk)

        dummy_engine = BacktestEngine(strategy=strat, risk_settings=base_risk)
        bt_service = BacktestService(
            exchange_client=exchange_client, engine=dummy_engine
        )

        print("\n=== Multi-Coin Backtest: Pinbar + Engulfing EMA-RSI (15m) ===")
        print(
            "Evaluating 10 Top Coins: "
            "Baseline (Fixed SL/TP) vs Enhanced (Trailing Stop)\n"
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
                e_res = await enh_engine.run(request=req, candles=candles)

                bm = b_res.metrics
                em = e_res.metrics
                pnl_delta = em.net_pnl - bm.net_pnl

                summary = PierBacktestSummary(
                    symbol=symbol,
                    candle_count=len(candles),
                    base_trades=bm.total_trades,
                    enh_trades=em.total_trades,
                    base_win_rate=bm.win_rate_pct,
                    enh_win_rate=em.win_rate_pct,
                    base_pnl=bm.net_pnl,
                    enh_pnl=em.net_pnl,
                    pnl_delta=pnl_delta,
                    base_fees=bm.total_fees,
                    enh_fees=em.total_fees,
                    base_drawdown=bm.max_drawdown_pct,
                    enh_drawdown=em.max_drawdown_pct,
                )
                summaries.append(summary)

                delta_str = (
                    f"+${pnl_delta:.2f}"
                    if pnl_delta >= _DECIMAL_ZERO
                    else f"-${abs(pnl_delta):.2f}"
                )
                print(
                    f"Done ({len(candles)} bars) | Trades: Base={bm.total_trades}, "
                    f"WR={bm.win_rate_pct:.1f}% | PnL: Base=${bm.net_pnl:.2f}, "
                    f"Enh=${em.net_pnl:.2f} ({delta_str})"
                )
            except Exception as e:
                print(f"FAILED: {e}")

    finally:
        await exchange_client.close()

    return summaries


def format_markdown_report(summaries: list[PierBacktestSummary]) -> str:
    total_base_pnl = sum((s.base_pnl for s in summaries), _DECIMAL_ZERO)
    total_enh_pnl = sum((s.enh_pnl for s in summaries), _DECIMAL_ZERO)
    total_base_fees = sum((s.base_fees for s in summaries), _DECIMAL_ZERO)
    total_enh_fees = sum((s.enh_fees for s in summaries), _DECIMAL_ZERO)
    total_base_trades = sum(s.base_trades for s in summaries)
    total_enh_trades = sum(s.enh_trades for s in summaries)
    portfolio_delta = total_enh_pnl - total_base_pnl

    avg_base_wr = (
        sum((s.base_win_rate for s in summaries), _DECIMAL_ZERO)
        / Decimal(len(summaries))
        if summaries
        else _DECIMAL_ZERO
    )
    avg_enh_wr = (
        sum((s.enh_win_rate for s in summaries), _DECIMAL_ZERO)
        / Decimal(len(summaries))
        if summaries
        else _DECIMAL_ZERO
    )
    avg_base_dd = (
        sum((s.base_drawdown for s in summaries), _DECIMAL_ZERO)
        / Decimal(len(summaries))
        if summaries
        else _DECIMAL_ZERO
    )
    avg_enh_dd = (
        sum((s.enh_drawdown for s in summaries), _DECIMAL_ZERO)
        / Decimal(len(summaries))
        if summaries
        else _DECIMAL_ZERO
    )

    delta_sign = "+" if portfolio_delta >= _DECIMAL_ZERO else "-"
    wr_diff = avg_enh_wr - avg_base_wr
    wr_sign = "+" if wr_diff >= _DECIMAL_ZERO else ""

    lines = [
        "## 📊 Laporan Backtest Multi-Coin: Pinbar + Engulfing EMA-RSI (15m)",
        "",
        "### 1. Ringkasan Portofolio (10 Koin Teratas - 15m)",
        (
            "| Metrik Portofolio | 15m Baseline (Fixed SL/TP) | "
            "15m Enhanced (Trailing Stop) | Perubahan |"
        ),
        "| :--- | :--- | :--- | :--- |",
        (
            f"| **Total Net PnL** | `${total_base_pnl:.2f}` | "
            f"`${total_enh_pnl:.2f}` | "
            f"**`{delta_sign}${abs(portfolio_delta):.2f}`** |"
        ),
        (
            f"| **Total Biaya Fee Exchange** | `${total_base_fees:.2f}` | "
            f"`${total_enh_fees:.2f}` | "
            f"`${total_enh_fees - total_base_fees:+.2f}` |"
        ),
        (
            f"| **Rata-rata Win Rate** | `{avg_base_wr:.2f}%` | "
            f"`{avg_enh_wr:.2f}%` | **`{wr_sign}{wr_diff:.2f}%`** |"
        ),
        (
            f"| **Rata-rata Max Drawdown** | `{avg_base_dd:.2f}%` | "
            f"`{avg_enh_dd:.2f}%` | "
            f"`{avg_enh_dd - avg_base_dd:+.2f}%` |"
        ),
        (
            f"| **Total Eksekusi Trade** | `{total_base_trades}` | "
            f"`{total_enh_trades}` | "
            f"`{total_enh_trades - total_base_trades:+d}` |"
        ),
        "",
        "### 2. Rincian Per Koin (15m)",
        (
            "| Simbol | Lilin | Trades | Base WR | Enh WR | "
            "Base PnL | Enh PnL | PnL Delta | Total Fees |"
        ),
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for s in summaries:
        p_sign = "+" if s.pnl_delta >= _DECIMAL_ZERO else "-"
        lines.append(
            f"| **{s.symbol}** | {s.candle_count} | {s.base_trades} | "
            f"{s.base_win_rate:.1f}% | **{s.enh_win_rate:.1f}%** | "
            f"${s.base_pnl:.2f} | **${s.enh_pnl:.2f}** | "
            f"`{p_sign}${abs(s.pnl_delta):.2f}` | ${s.base_fees:.2f} |"
        )

    lines.append("")
    return "\n".join(lines)


async def main() -> None:
    summaries = await run_pier_top10_backtest()
    if not summaries:
        print("No summaries produced.")
        return

    md_report = format_markdown_report(summaries)
    out_file = Path("backtest_top10_pier_report.md")
    out_file.write_text(md_report, encoding="utf-8")
    print(f"\nReport written to {out_file.absolute()}\n")


if __name__ == "__main__":
    asyncio.run(main())
