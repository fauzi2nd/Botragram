"""
Botragram

Description:
    Manual top 10 coins comparative backtest runner evaluating
    EMA Scalping baseline vs EMA Scalping with EMA 200 Macro Trend Filter.

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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.constants import BYBIT_REST_BASE_URL
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import ExchangeType, Interval, MarketType, SignalType, StrategyType
from botragram.exchanges import ExchangeFactory
from botragram.indicators import calculate_ema
from botragram.models import BacktestRequest, BacktestResult, Candle, Signal
from botragram.services.backtest_service import BacktestService
from botragram.strategies.scalping.ema_scalping import EMAScalpingStrategy

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


class TrendFilteredEMAScalpingStrategy(EMAScalpingStrategy):
    """EMA Scalping with EMA 200 Macro Trend Confirmation."""

    trend_period: int = 200

    @property
    def minimum_candles(self) -> int:
        return self.trend_period + 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        sig = super().generate_signal(candles=candles)
        if sig.signal_type is SignalType.HOLD:
            return sig

        if len(candles) < self.trend_period:
            return replace(
                sig,
                signal_type=SignalType.HOLD,
                reason="Insufficient candles for trend filter",
            )

        close_prices = tuple(c.close_price for c in candles)
        ema_trend = calculate_ema(close_prices, period=self.trend_period)[-1]
        latest_close = candles[-1].close_price

        if sig.signal_type is SignalType.BUY and latest_close < ema_trend:
            return replace(
                sig,
                signal_type=SignalType.HOLD,
                reason="Filtered: BUY signal below 200 EMA",
            )

        if sig.signal_type is SignalType.SELL and latest_close > ema_trend:
            return replace(
                sig,
                signal_type=SignalType.HOLD,
                reason="Filtered: SELL signal above 200 EMA",
            )

        return replace(
            sig,
            reason=f"{sig.reason} + Confirmed by EMA 200 Trend",
        )


@dataclass(slots=True, kw_only=True, frozen=True)
class TrendComparisonSummary:
    symbol: str
    candle_count: int
    base_trades: int
    filt_trades: int
    base_win_rate: Decimal
    filt_win_rate: Decimal
    base_pnl: Decimal
    filt_pnl: Decimal
    pnl_delta: Decimal
    base_fees: Decimal
    filt_fees: Decimal
    fees_saved: Decimal
    base_drawdown: Decimal
    filt_drawdown: Decimal


async def run_trend_filter_comparison() -> list[TrendComparisonSummary]:
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
    summaries: list[TrendComparisonSummary] = []

    try:
        base_strat = EMAScalpingStrategy()
        filt_strat = TrendFilteredEMAScalpingStrategy()
        risk_settings = RiskSettings(leverage=5, trailing_stop_enabled=True)

        base_engine = BacktestEngine(strategy=base_strat, risk_settings=risk_settings)
        filt_engine = BacktestEngine(strategy=filt_strat, risk_settings=risk_settings)

        dummy_engine = BacktestEngine(strategy=base_strat, risk_settings=risk_settings)
        bt_service = BacktestService(
            exchange_client=exchange_client, engine=dummy_engine
        )

        print("=== Running Solusi 1: EMA Scalping + EMA 200 Trend Filter ===")
        print("Comparing: Pure EMA 5/13 vs EMA 5/13 + EMA 200 Trend Filter\n")

        for idx, symbol in enumerate(TOP_10_SYMBOLS, start=1):
            print(f"[{idx}/10] Testing {symbol}...", end=" ", flush=True)

            req = BacktestRequest(
                symbol=symbol,
                interval=Interval.M5,
                strategy_type=StrategyType.EMA_SCALPING,
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
                    print("SKIP")
                    continue

                b_res: BacktestResult = await base_engine.run(
                    request=req, candles=candles
                )
                f_res: BacktestResult = await filt_engine.run(
                    request=req, candles=candles
                )

                bm = b_res.metrics
                fm = f_res.metrics

                pnl_delta = fm.net_pnl - bm.net_pnl
                fees_saved = bm.total_fees - fm.total_fees

                summary = TrendComparisonSummary(
                    symbol=symbol,
                    candle_count=len(candles),
                    base_trades=bm.total_trades,
                    filt_trades=fm.total_trades,
                    base_win_rate=bm.win_rate_pct,
                    filt_win_rate=fm.win_rate_pct,
                    base_pnl=bm.net_pnl,
                    filt_pnl=fm.net_pnl,
                    pnl_delta=pnl_delta,
                    base_fees=bm.total_fees,
                    filt_fees=fm.total_fees,
                    fees_saved=fees_saved,
                    base_drawdown=bm.max_drawdown_pct,
                    filt_drawdown=fm.max_drawdown_pct,
                )
                summaries.append(summary)

                sign = "+" if pnl_delta >= _DECIMAL_ZERO else ""
                print(
                    f"DONE | Trades: {bm.total_trades}->{fm.total_trades} | "
                    f"WR: {bm.win_rate_pct:.1f}%->{fm.win_rate_pct:.1f}% | "
                    f"PnL: ${bm.net_pnl:.2f}->${fm.net_pnl:.2f} "
                    f"({sign}${pnl_delta:.2f}) | "
                    f"Fees Saved: ${fees_saved:.2f}"
                )

            except Exception as exc:
                print(f"ERROR: {exc}")

    finally:
        await exchange_client.close()

    return summaries


def format_trend_report(summaries: list[TrendComparisonSummary]) -> str:
    if not summaries:
        return "No results."

    total_base_pnl = sum((s.base_pnl for s in summaries), _DECIMAL_ZERO)
    total_filt_pnl = sum((s.filt_pnl for s in summaries), _DECIMAL_ZERO)
    total_pnl_delta = total_filt_pnl - total_base_pnl

    total_base_trades = sum(s.base_trades for s in summaries)
    total_filt_trades = sum(s.filt_trades for s in summaries)

    total_base_fees = sum((s.base_fees for s in summaries), _DECIMAL_ZERO)
    total_filt_fees = sum((s.filt_fees for s in summaries), _DECIMAL_ZERO)
    total_fees_saved = total_base_fees - total_filt_fees

    count = Decimal(len(summaries))
    avg_base_wr = sum((s.base_win_rate for s in summaries), _DECIMAL_ZERO) / count
    avg_filt_wr = sum((s.filt_win_rate for s in summaries), _DECIMAL_ZERO) / count

    lines = [
        "## 📊 Laporan Hasil Solusi 1: EMA Scalping + Filter Tren Makro (EMA 200)",
        "",
        "### 1. Ringkasan Portofolio (10 Koin Teratas)",
        "| Metrik Portofolio | Tanpa Filter (Murni 5/13) | "
        "Dengan Filter EMA 200 | Penghematan / Peningkatan |",
        "| :--- | :--- | :--- | :--- |",
        (
            f"| **Total Net PnL** | `${total_base_pnl:,.2f}` | "
            f"`${total_filt_pnl:,.2f}` | "
            f"**`{'+' if total_pnl_delta >= _DECIMAL_ZERO else ''}"
            f"${total_pnl_delta:,.2f}`** |"
        ),
        (
            f"| **Total Biaya Fee Exchange** | `${total_base_fees:,.2f}` | "
            f"`${total_filt_fees:,.2f}` | "
            f"**`Hemat +${total_fees_saved:,.2f}`** |"
        ),
        (
            f"| **Rata-rata Win Rate** | `{avg_base_wr:.2f}%` | "
            f"`{avg_filt_wr:.2f}%` | "
            f"**`{avg_filt_wr - avg_base_wr:+.2f}%`** |"
        ),
        (
            f"| **Total Eksekusi Trade** | `{total_base_trades}` | "
            f"`{total_filt_trades}` | "
            f"`{total_filt_trades - total_base_trades:+d} trade (whipsaw terpotong)` |"
        ),
        "",
        "### 2. Rincian Per Koin",
        "| Simbol | Trades Murni | Trades Filtered | Base WR | Filtered WR | "
        "Base PnL | Filtered PnL | PnL Delta | Fee Hemat |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for s in summaries:
        delta_str = f"{'+' if s.pnl_delta >= _DECIMAL_ZERO else ''}${s.pnl_delta:.2f}"
        lines.append(
            f"| **{s.symbol}** | {s.base_trades} | {s.filt_trades} | "
            f"{s.base_win_rate:.1f}% | **{s.filt_win_rate:.1f}%** | "
            f"${s.base_pnl:.2f} | **${s.filt_pnl:.2f}** | "
            f"`{delta_str}` | +${s.fees_saved:.2f} |"
        )

    return "\n".join(lines)


async def main() -> None:
    summaries = await run_trend_filter_comparison()
    report = format_trend_report(summaries)
    out_file = Path("backtest_top10_ema_trend_filtered_report.md")
    out_file.write_text(report, encoding="utf-8")
    print(f"\nReport successfully saved to {out_file.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
