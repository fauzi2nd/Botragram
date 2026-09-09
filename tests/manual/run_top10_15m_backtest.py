"""
Botragram

Description:
    Manual top 10 coins comparative backtest runner evaluating
    15-minute timeframe performance with EMA 200 Trend Filter
    comparing baseline vs trailing stop & volatility sizing.

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
from botragram.models import BacktestRequest, Candle, Signal
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
class TimeframeComparisonSummary:
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


async def run_15m_top10_backtest() -> list[TimeframeComparisonSummary]:
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
    summaries: list[TimeframeComparisonSummary] = []

    try:
        strat = TrendFilteredEMAScalpingStrategy()

        # Baseline: Fixed SL/TP on 15m (SL 1.2%, TP 2.5%)
        base_risk = RiskSettings(
            leverage=5,
            scalping_stop_loss_pct=Decimal("0.012"),
            scalping_take_profit_pct=Decimal("0.025"),
            trailing_stop_enabled=False,
            volatility_sizing_enabled=False,
        )
        # Enhanced: With Trailing Stop & Volatility Sizing on 15m
        enh_risk = RiskSettings(
            leverage=5,
            scalping_stop_loss_pct=Decimal("0.012"),
            scalping_take_profit_pct=Decimal("0.025"),
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.015"),
            trailing_stop_distance_pct=Decimal("0.008"),
            volatility_sizing_enabled=True,
            baseline_volatility_pct=Decimal("0.015"),
        )

        base_engine = BacktestEngine(strategy=strat, risk_settings=base_risk)
        enh_engine = BacktestEngine(strategy=strat, risk_settings=enh_risk)

        dummy_engine = BacktestEngine(strategy=strat, risk_settings=base_risk)
        bt_service = BacktestService(
            exchange_client=exchange_client, engine=dummy_engine
        )

        print("=== Running Solusi 2: 15-Minute Timeframe (EMA 200 Trend Filter) ===")
        print(
            "Comparing: Baseline (15m Fixed) vs "
            "Enhanced (15m Trailing Stop + Vol Sizing)\n"
        )

        for idx, symbol in enumerate(TOP_10_SYMBOLS, start=1):
            print(f"[{idx}/10] Testing {symbol} (15m)...", end=" ", flush=True)

            req = BacktestRequest(
                symbol=symbol,
                interval=Interval.M15,
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

                b_res = await base_engine.run(request=req, candles=candles)
                e_res = await enh_engine.run(request=req, candles=candles)

                bm = b_res.metrics
                em = e_res.metrics
                pnl_delta = em.net_pnl - bm.net_pnl

                summary = TimeframeComparisonSummary(
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

                sign = "+" if pnl_delta >= _DECIMAL_ZERO else ""
                print(
                    f"DONE | Trades: {em.total_trades} | "
                    f"WR: {bm.win_rate_pct:.1f}%->{em.win_rate_pct:.1f}% | "
                    f"Base PnL: ${bm.net_pnl:.2f} -> Enh PnL: ${em.net_pnl:.2f} "
                    f"({sign}${pnl_delta:.2f}) | "
                    f"Fees: ${em.total_fees:.2f}"
                )

            except Exception as exc:
                print(f"ERROR: {exc}")

    finally:
        await exchange_client.close()

    return summaries


def format_15m_report(summaries: list[TimeframeComparisonSummary]) -> str:
    if not summaries:
        return "No results."

    total_base_pnl = sum((s.base_pnl for s in summaries), _DECIMAL_ZERO)
    total_enh_pnl = sum((s.enh_pnl for s in summaries), _DECIMAL_ZERO)
    total_pnl_delta = total_enh_pnl - total_base_pnl

    total_base_trades = sum(s.base_trades for s in summaries)
    total_enh_trades = sum(s.enh_trades for s in summaries)

    total_base_fees = sum((s.base_fees for s in summaries), _DECIMAL_ZERO)
    total_enh_fees = sum((s.enh_fees for s in summaries), _DECIMAL_ZERO)

    count = Decimal(len(summaries))
    avg_base_wr = sum((s.base_win_rate for s in summaries), _DECIMAL_ZERO) / count
    avg_enh_wr = sum((s.enh_win_rate for s in summaries), _DECIMAL_ZERO) / count
    avg_base_dd = sum((s.base_drawdown for s in summaries), _DECIMAL_ZERO) / count
    avg_enh_dd = sum((s.enh_drawdown for s in summaries), _DECIMAL_ZERO) / count

    lines = [
        "## 📊 Laporan Solusi 2: Timeframe 15m (EMA Scalping + EMA 200 Filter)",
        "",
        "### 1. Ringkasan Portofolio (10 Koin Teratas - 15m)",
        "| Metrik Portofolio | 15m Baseline (Fixed SL/TP) | "
        "15m Enhanced (Trailing Stop) | Perubahan |",
        "| :--- | :--- | :--- | :--- |",
        (
            f"| **Total Net PnL** | `${total_base_pnl:,.2f}` | "
            f"`${total_enh_pnl:,.2f}` | "
            f"**`{'+' if total_pnl_delta >= _DECIMAL_ZERO else ''}"
            f"${total_pnl_delta:,.2f}`** |"
        ),
        (
            f"| **Total Biaya Fee Exchange** | `${total_base_fees:,.2f}` | "
            f"`${total_enh_fees:,.2f}` | "
            f"`{total_enh_fees - total_base_fees:+.2f}` |"
        ),
        (
            f"| **Rata-rata Win Rate** | `{avg_base_wr:.2f}%` | "
            f"`{avg_enh_wr:.2f}%` | "
            f"**`{avg_enh_wr - avg_base_wr:+.2f}%`** |"
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
        "| Simbol | Lilin | Trades | Base WR | Enh WR | "
        "Base PnL | Enh PnL | PnL Delta | Total Fees |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for s in summaries:
        delta_str = f"{'+' if s.pnl_delta >= _DECIMAL_ZERO else ''}${s.pnl_delta:.2f}"
        lines.append(
            f"| **{s.symbol}** | {s.candle_count} | {s.enh_trades} | "
            f"{s.base_win_rate:.1f}% | **{s.enh_win_rate:.1f}%** | "
            f"${s.base_pnl:.2f} | **${s.enh_pnl:.2f}** | "
            f"`{delta_str}` | ${s.enh_fees:.2f} |"
        )

    return "\n".join(lines)


async def main() -> None:
    summaries = await run_15m_top10_backtest()
    report = format_15m_report(summaries)
    out_file = Path("backtest_top10_15m_report.md")
    out_file.write_text(report, encoding="utf-8")
    print(f"\nReport successfully saved to {out_file.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
