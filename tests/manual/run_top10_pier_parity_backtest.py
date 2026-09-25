"""
Botragram

Description:
    Manual top 10 coins research backtest runner for the PIER strategy
    using the EXACT current production runtime configuration.

    Unlike historical studies (which used hardcoded parameters such as
    trend_period=100 and volume_multiplier=1.05), this runner constructs
    the strategy and risk engine directly from the authoritative
    `SettingsManager`, `StrategyFactory`, and environment bindings.

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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager
from botragram.constants import BYBIT_REST_BASE_URL
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import (
    ExchangeType,
    Interval,
    MarketType,
    PositionSide,
    StrategyType,
)
from botragram.exchanges import ExchangeFactory
from botragram.models import BacktestRequest, BacktestTrade
from botragram.services.backtest_service import BacktestService
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")

TOP_10_SYMBOLS: Final[tuple[str, ...]] = (
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


def _empty_str_int_dict() -> dict[str, int]:
    return {}


# =============================================================================
# Data Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class PierParitySymbolSummary:
    """Detailed parity metrics for one symbol."""

    symbol: str
    candle_count: int
    total_trades: int
    gross_pnl: Decimal
    net_pnl: Decimal
    fees: Decimal
    win_rate: Decimal
    profit_factor: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    max_drawdown: Decimal
    expectancy: Decimal
    long_trades: int
    short_trades: int
    long_win_rate: Decimal
    short_win_rate: Decimal
    pattern_breakdown: dict[str, int] = field(default_factory=_empty_str_int_dict)
    regime_breakdown: dict[str, int] = field(default_factory=_empty_str_int_dict)


# =============================================================================
# Parity Backtest Runner
# =============================================================================
def _extract_pattern_name(reason: str) -> str:
    for name in (
        "Bullish Pinbar",
        "Bearish Pinbar",
        "Bullish Engulfing",
        "Bearish Engulfing",
        "Morning Star",
        "Evening Star",
    ):
        if name in reason:
            return name
    return "Candle Pattern"


def _calculate_profit_factor(trades: Sequence[BacktestTrade]) -> Decimal:
    gross_win = sum(
        (t.realized_pnl for t in trades if t.realized_pnl > _DECIMAL_ZERO),
        _DECIMAL_ZERO,
    )
    gross_loss = abs(
        sum(
            (t.realized_pnl for t in trades if t.realized_pnl < _DECIMAL_ZERO),
            _DECIMAL_ZERO,
        )
    )
    if gross_loss == _DECIMAL_ZERO:
        return Decimal("999.0") if gross_win > _DECIMAL_ZERO else _DECIMAL_ZERO
    return (gross_win / gross_loss).quantize(Decimal("0.01"))


def _calculate_expectancy(trades: Sequence[BacktestTrade]) -> Decimal:
    if not trades:
        return _DECIMAL_ZERO
    total_pnl = sum((t.realized_pnl - t.fees for t in trades), _DECIMAL_ZERO)
    return (total_pnl / Decimal(len(trades))).quantize(Decimal("0.01"))


async def run_pier_runtime_parity_backtest() -> list[PierParitySymbolSummary]:
    """Execute current runtime parity backtest across top 10 crypto pairs."""
    env = EnvironmentProvider()
    settings_mgr = SettingsManager(environment_provider=env)

    strategy_settings = settings_mgr.load_strategy_settings()
    risk_settings = settings_mgr.load_risk_settings()

    # Resolve strategy from authoritative factory using PIER type
    strategy = StrategyFactory.create(
        settings=replace(
            strategy_settings,
            strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        )
    )
    if not isinstance(strategy, PinbarEngulfingEmaRsiStrategy):
        raise TypeError("Failed to instantiate PinbarEngulfingEmaRsiStrategy")

    # Timeframe from environment or strategy default
    interval_raw = env.get_global_market_interval()
    try:
        timeframe = Interval(interval_raw)
    except ValueError:
        timeframe = Interval.M15

    now = datetime.now(UTC)
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
    summaries: list[PierParitySymbolSummary] = []

    print("\n=======================================================")
    print("PIER CURRENT RUNTIME PARITY STUDY")
    print("=======================================================")
    print(f"Sample Period:     {start.isoformat()} to {now.isoformat()}")
    print(f"Timeframe:         {timeframe.value}")
    print(f"Trend Period:      {strategy.trend_period}")
    print(f"Pullback Period:   {strategy.pullback_period}")
    print(
        f"RSI Period:        {strategy.rsi_period} "
        f"(L: {strategy.rsi_long_min}-{strategy.rsi_long_max}, "
        f"S: {strategy.rsi_short_min}-{strategy.rsi_short_max})"
    )
    print(
        f"Volume Period:     {strategy.volume_period} "
        f"(Multiplier: {strategy.volume_multiplier})"
    )
    print(
        f"ATR Period:        {strategy.atr_period} "
        f"(SL Multiplier: {strategy.atr_multiplier_sl})"
    )
    print(
        f"Location ATR:      {strategy.location_atr_multiplier} "
        f"(Tolerance Pct: {strategy.location_tolerance_pct})"
    )
    print(
        f"Pullback ATR:      {strategy.pullback_atr_multiplier} "
        f"(Proximity Pct: {strategy.pullback_proximity_pct})"
    )
    print(f"Min Confidence:    {strategy.min_confidence}")
    print(
        f"Risk Ceiling SL:   {risk_settings.pier_stop_loss_pct * _DECIMAL_HUNDRED:.2f}%"
    )
    print(
        f"Risk Ceiling TP:   "
        f"{risk_settings.pier_take_profit_pct * _DECIMAL_HUNDRED:.2f}%"
    )
    print("=======================================================\n")

    try:
        engine = BacktestEngine(strategy=strategy, risk_settings=risk_settings)
        bt_service = BacktestService(exchange_client=exchange_client, engine=engine)

        for idx, symbol in enumerate(TOP_10_SYMBOLS, start=1):
            print(
                f"[{idx}/10] Testing {symbol} ({timeframe.value})...",
                end=" ",
                flush=True,
            )

            req = BacktestRequest(
                symbol=symbol,
                interval=timeframe,
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

                res = await engine.run(request=req, candles=candles)
                m = res.metrics
                trades = res.trades

                long_trades = [t for t in trades if t.side == PositionSide.LONG]
                short_trades = [t for t in trades if t.side == PositionSide.SHORT]
                long_wins = [t for t in long_trades if t.realized_pnl > _DECIMAL_ZERO]
                short_wins = [t for t in short_trades if t.realized_pnl > _DECIMAL_ZERO]

                long_wr = (
                    (
                        Decimal(len(long_wins))
                        / Decimal(len(long_trades))
                        * _DECIMAL_HUNDRED
                    ).quantize(Decimal("0.01"))
                    if long_trades
                    else _DECIMAL_ZERO
                )
                short_wr = (
                    (
                        Decimal(len(short_wins))
                        / Decimal(len(short_trades))
                        * _DECIMAL_HUNDRED
                    ).quantize(Decimal("0.01"))
                    if short_trades
                    else _DECIMAL_ZERO
                )

                wins = [t for t in trades if t.realized_pnl > _DECIMAL_ZERO]
                losses = [t for t in trades if t.realized_pnl < _DECIMAL_ZERO]
                avg_win = (
                    (
                        sum((w.realized_pnl for w in wins), _DECIMAL_ZERO)
                        / Decimal(len(wins))
                    ).quantize(Decimal("0.01"))
                    if wins
                    else _DECIMAL_ZERO
                )
                avg_loss = (
                    (
                        sum(
                            (loss_item.realized_pnl for loss_item in losses),
                            _DECIMAL_ZERO,
                        )
                        / Decimal(len(losses))
                    ).quantize(Decimal("0.01"))
                    if losses
                    else _DECIMAL_ZERO
                )

                pattern_breakdown: dict[str, int] = {}
                regime_breakdown: dict[str, int] = {
                    "BULLISH": len(long_trades),
                    "BEARISH": len(short_trades),
                }
                for t in trades:
                    p = _extract_pattern_name(t.reason)
                    pattern_breakdown[p] = pattern_breakdown.get(p, 0) + 1

                summary = PierParitySymbolSummary(
                    symbol=symbol,
                    candle_count=len(candles),
                    total_trades=m.total_trades,
                    gross_pnl=m.net_pnl + m.total_fees,
                    net_pnl=m.net_pnl,
                    fees=m.total_fees,
                    win_rate=m.win_rate_pct,
                    profit_factor=(
                        m.profit_factor
                        if m.profit_factor is not None
                        else _calculate_profit_factor(trades)
                    ),
                    avg_win=avg_win,
                    avg_loss=avg_loss,
                    max_drawdown=m.max_drawdown_pct,
                    expectancy=_calculate_expectancy(trades),
                    long_trades=len(long_trades),
                    short_trades=len(short_trades),
                    long_win_rate=long_wr,
                    short_win_rate=short_wr,
                    pattern_breakdown=pattern_breakdown,
                    regime_breakdown=regime_breakdown,
                )
                summaries.append(summary)
                print(
                    f"DONE | Trades: {summary.total_trades}, "
                    f"Net PnL: {summary.net_pnl:+.2f} USDT, "
                    f"Win Rate: {summary.win_rate:.1f}%"
                )

            except Exception as e:
                print(f"ERROR ({e})")

    finally:
        await exchange_client.close()

    return summaries


if __name__ == "__main__":
    asyncio.run(run_pier_runtime_parity_backtest())
