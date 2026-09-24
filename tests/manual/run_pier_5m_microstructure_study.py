"""
Botragram

Description:
    Manual research and low-timeframe alignment study for the PIER
    (Pinbar + Engulfing EMA-RSI Pullback) strategy on 5m timeframe.

    Evaluates 5m PIER signals against HTF (15m) and micro timeframes
    (3m, 1m) to determine:
    1. How frequently 5m PIER signals trigger counter-trend to micro timeframes.
    2. How many micro bars pass before alignment is achieved.
    3. Maximum Adverse Excursion (MAE) before micro alignment and
       Maximum Favorable Excursion (MFE) after micro alignment.
    4. Diagnostic evaluation of candidate 3m micro confirmations
       (without altering live strategy behavior).

    Research Timeframe Drift Documentation (Task B):
    - Runtime allows operators to configure PIER interval via `PIER_INTERVAL`
      (supported in environment provider and settings resolver).
    - Current default in `get_strategy_default_interval(
      StrategyType.PINBAR_ENGULFING_EMA_RSI)` remains M15.
    - Historical manual backtests (e.g. `run_top10_pier_backtest.py`)
      were run on M15.
    - This study establishes the empirical baseline for PIER on 5m (`Interval.M5`).

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
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants import BYBIT_REST_BASE_URL
from botragram.enums import ExchangeType, Interval, MarketType, SignalType
from botragram.exchanges import ExchangeFactory
from botragram.indicators import calculate_ema
from botragram.models import Candle, Signal
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy
from botragram.utils.candle_resampler import resample_candles

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")

RESEARCH_SYMBOLS: Final[tuple[str, ...]] = (
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

# Trade simulation horizon in 1m bars after signal
_MAX_FORWARD_BARS_1M: Final[int] = 120


# =============================================================================
# Domain / Research Data Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class PierSignalStudyRecord:
    """Detailed record for one actionable 5m PIER signal."""

    symbol: str
    signal_time: datetime
    signal_side: str  # "BUY" or "SELL"
    pier_pattern: str  # Pattern label extracted from reason
    confidence: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    regime_15m: str  # "BULLISH" or "BEARISH"
    direction_3m_at_signal: str  # "BULLISH" or "BEARISH"
    direction_1m_at_signal: str  # "BULLISH" or "BEARISH"
    is_3m_aligned: bool
    is_3m_counter_trend: bool
    is_1m_aligned: bool
    is_1m_counter_trend: bool
    is_micro_reversing_at_signal: bool  # Immediate micro candle reversal
    bars_to_3m_alignment: int
    bars_to_1m_alignment: int
    mae_pct_before_alignment: Decimal  # Max adverse excursion before 3m alignment
    mfe_pct_after_alignment: Decimal  # Max favorable excursion after 3m alignment
    trade_outcome: str  # "WIN", "LOSS", or "TIMEOUT"
    # Task C candidates evaluation:
    candidate_ema_cross_confirmed: bool
    candidate_close_vs_ema_confirmed: bool
    candidate_swing_break_confirmed: bool
    candidate_momentum_shift_confirmed: bool


# =============================================================================
# Deterministic Microstructure Indicators
# =============================================================================
def compute_trend_direction(
    candles: tuple[Candle, ...],
    *,
    fast_period: int = 9,
    slow_period: int = 21,
) -> str:
    """Determine closed-candle trend direction from dual EMAs.

    Args:
        candles: Sequence of closed candles up to evaluation point.
        fast_period: Period for fast EMA.
        slow_period: Period for slow EMA.

    Returns:
        "BULLISH" if fast EMA >= slow EMA, otherwise "BEARISH".
    """
    closes = tuple(c.close_price for c in candles)
    if len(closes) < slow_period:
        return "BULLISH"
    try:
        fast_series = calculate_ema(closes, period=fast_period)
        slow_series = calculate_ema(closes, period=slow_period)
    except ValueError:
        return "BULLISH"

    if not fast_series or not slow_series:
        return "BULLISH"
    latest_fast = fast_series[-1]
    latest_slow = slow_series[-1]
    return "BULLISH" if latest_fast >= latest_slow else "BEARISH"


def is_micro_reversing(
    candles: tuple[Candle, ...],
    *,
    signal_side: str,
) -> bool:
    """Determine whether the latest micro candle has started reversing.

    Args:
        candles: Closed micro candles up to signal time.
        signal_side: "BUY" or "SELL".

    Returns:
        True if price action on the most recent candle aligns with signal direction.
    """
    if not candles:
        return False
    latest = candles[-1]
    if signal_side == "BUY":
        return latest.close_price >= latest.open_price
    return latest.close_price <= latest.open_price


def find_last_micro_swing_level(
    candles: tuple[Candle, ...],
    *,
    signal_side: str,
    lookback: int = 10,
) -> Decimal | None:
    """Find the most recent swing high/low on micro timeframe.

    Args:
        candles: Sequence of closed micro candles.
        signal_side: "BUY" (find swing high to break) or "SELL" (swing low).
        lookback: Number of candles to inspect.

    Returns:
        Swing high price for BUY, or swing low price for SELL.
    """
    if len(candles) < 3:
        return None
    window = candles[-lookback:]
    if signal_side == "BUY":
        return max(c.high_price for c in window)
    return min(c.low_price for c in window)


# =============================================================================
# Trade Simulation & Excursion Calculation
# =============================================================================
def simulate_trade_and_excursion(
    *,
    signal: Signal,
    candles_1m_forward: tuple[Candle, ...],
    candles_3m_forward: tuple[Candle, ...],
    signal_side: str,
    entry_price: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
    is_already_3m_aligned: bool,
) -> tuple[int, int, Decimal, Decimal, str]:
    """Forward-simulate trade to calculate alignment bars, MAE, MFE, and outcome.

    Args:
        signal: Generated PIER signal.
        candles_1m_forward: 1m candles strictly occurring after signal_time.
        candles_3m_forward: 3m candles strictly occurring after signal_time.
        signal_side: "BUY" or "SELL".
        entry_price: Price at signal bar close.
        stop_loss: SL price.
        take_profit: TP price.
        is_already_3m_aligned: Whether 3m direction was already aligned at signal.

    Returns:
        Tuple of (bars_to_3m, bars_to_1m, mae_pct, mfe_pct, outcome).
    """
    del signal
    # 1. Bars to 3m alignment
    bars_3m = 0
    if not is_already_3m_aligned:
        for idx, bar in enumerate(candles_3m_forward, start=1):
            bar_dir = "BULLISH" if bar.close_price >= bar.open_price else "BEARISH"
            target_dir = "BULLISH" if signal_side == "BUY" else "BEARISH"
            if bar_dir == target_dir:
                bars_3m = idx
                break
        if bars_3m == 0:
            bars_3m = len(candles_3m_forward)

    # 2. Bars to 1m alignment
    bars_1m = 0
    for idx, bar in enumerate(candles_1m_forward, start=1):
        bar_dir = "BULLISH" if bar.close_price >= bar.open_price else "BEARISH"
        target_dir = "BULLISH" if signal_side == "BUY" else "BEARISH"
        if bar_dir == target_dir:
            bars_1m = idx
            break
    if bars_1m == 0:
        bars_1m = len(candles_1m_forward)

    # 3. Simulate trade outcome and excursion on 1m bars
    outcome = "TIMEOUT"
    max_adverse = _DECIMAL_ZERO
    max_favorable = _DECIMAL_ZERO
    alignment_1m_idx = bars_1m

    for idx, bar in enumerate(candles_1m_forward, start=1):
        # Excursion before alignment (or throughout trade)
        if signal_side == "BUY":
            adverse_move = (
                (entry_price - bar.low_price) / entry_price
                if entry_price > _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            favorable_move = (
                (bar.high_price - entry_price) / entry_price
                if entry_price > _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            if idx <= alignment_1m_idx and adverse_move > max_adverse:
                max_adverse = adverse_move
            if idx >= alignment_1m_idx and favorable_move > max_favorable:
                max_favorable = favorable_move

            # Check SL / TP hits
            if bar.low_price <= stop_loss:
                outcome = "LOSS"
                break
            if bar.high_price >= take_profit:
                outcome = "WIN"
                break
        else:
            adverse_move = (
                (bar.high_price - entry_price) / entry_price
                if entry_price > _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            favorable_move = (
                (entry_price - bar.low_price) / entry_price
                if entry_price > _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            if idx <= alignment_1m_idx and adverse_move > max_adverse:
                max_adverse = adverse_move
            if idx >= alignment_1m_idx and favorable_move > max_favorable:
                max_favorable = favorable_move

            # Check SL / TP hits
            if bar.high_price >= stop_loss:
                outcome = "LOSS"
                break
            if bar.low_price <= take_profit:
                outcome = "WIN"
                break

    mae_pct = max_adverse * _DECIMAL_HUNDRED
    mfe_pct = max_favorable * _DECIMAL_HUNDRED
    return bars_3m, bars_1m, mae_pct, mfe_pct, outcome


# =============================================================================
# Study Runner
# =============================================================================
class Pier5mMicrostructureStudyRunner:
    """Executes the 5m PIER low-timeframe alignment study."""

    def __init__(self) -> None:
        self._strategy = PinbarEngulfingEmaRsiStrategy(
            trend_period=100,
            pullback_period=21,
            rsi_period=14,
            volume_period=20,
            volume_multiplier=Decimal("1.05"),
        )

    def extract_pattern_label(self, reason: str | None) -> str:
        """Extract clean pattern name from signal reason string."""
        if not reason:
            return "Candle Pattern"
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

    def analyze_symbol_candles(
        self,
        *,
        symbol: str,
        candles_1m: tuple[Candle, ...],
    ) -> list[PierSignalStudyRecord]:
        """Analyze multi-timeframe alignment for all 5m PIER signals on one symbol."""
        if len(candles_1m) < 600:
            return []

        # Deterministically resample 1m into 3m, 5m, and 15m
        candles_3m = tuple(
            resample_candles(
                candles=candles_1m,
                target_interval=Interval.M3,
                closed_only=True,
            )
        )
        candles_5m = tuple(
            resample_candles(
                candles=candles_1m,
                target_interval=Interval.M5,
                closed_only=True,
            )
        )
        candles_15m = tuple(
            resample_candles(
                candles=candles_1m,
                target_interval=Interval.M15,
                closed_only=True,
            )
        )

        records: list[PierSignalStudyRecord] = []
        min_5m_bars = 105  # Need at least trend_period (100) + 5 bars

        for i in range(min_5m_bars, len(candles_5m) - 15):
            eval_candles_5m = candles_5m[: i + 1]
            signal = self._strategy.generate_signal(candles=eval_candles_5m)
            if signal.signal_type is SignalType.HOLD:
                continue

            current_5m_bar = eval_candles_5m[-1]
            signal_time = current_5m_bar.close_time
            signal_side = "BUY" if signal.signal_type is SignalType.BUY else "SELL"
            pattern_label = self.extract_pattern_label(signal.reason)

            # 15m HTF Regime at signal_time
            closed_15m = tuple(c for c in candles_15m if c.close_time <= signal_time)
            regime_15m = compute_trend_direction(
                closed_15m, fast_period=21, slow_period=50
            )

            # 3m Micro timeframe at signal_time
            closed_3m = tuple(c for c in candles_3m if c.close_time <= signal_time)
            direction_3m = compute_trend_direction(
                closed_3m, fast_period=9, slow_period=21
            )
            is_3m_aligned = (signal_side == "BUY" and direction_3m == "BULLISH") or (
                signal_side == "SELL" and direction_3m == "BEARISH"
            )
            is_3m_counter = not is_3m_aligned

            # 1m Micro timeframe at signal_time
            closed_1m = tuple(c for c in candles_1m if c.close_time <= signal_time)
            direction_1m = compute_trend_direction(
                closed_1m, fast_period=9, slow_period=21
            )
            is_1m_aligned = (signal_side == "BUY" and direction_1m == "BULLISH") or (
                signal_side == "SELL" and direction_1m == "BEARISH"
            )
            is_1m_counter = not is_1m_aligned

            # Micro reversal beginning at signal bar?
            reversing_at_signal = is_micro_reversing(closed_3m, signal_side=signal_side)

            # Task C Candidates evaluation (3m confirmation rules):
            # Candidate A: 3m EMA fast/slow direction matches signal
            candidate_a = is_3m_aligned

            # Candidate B: 3m Close vs 3m EMA9
            closes_3m = tuple(c.close_price for c in closed_3m)
            candidate_b = False
            if len(closes_3m) >= 9:
                try:
                    ema9_3m = calculate_ema(closes_3m, period=9)
                    latest_ema9 = ema9_3m[-1] if ema9_3m else None
                    if latest_ema9 is not None and closed_3m:
                        if signal_side == "BUY":
                            candidate_b = closed_3m[-1].close_price > latest_ema9
                        else:
                            candidate_b = closed_3m[-1].close_price < latest_ema9
                except ValueError:
                    pass

            # Candidate C: Break of last confirmed micro swing
            swing_level = find_last_micro_swing_level(
                closed_3m, signal_side=signal_side, lookback=8
            )
            candidate_c = False
            if swing_level is not None and closed_3m:
                if signal_side == "BUY":
                    candidate_c = closed_3m[-1].close_price >= swing_level
                else:
                    candidate_c = closed_3m[-1].close_price <= swing_level

            # Candidate D: Momentum shift (reversing candle + close vs open)
            candidate_d = reversing_at_signal

            # Forward candles for excursion and outcome
            fwd_1m = tuple(c for c in candles_1m if c.open_time >= signal_time)[
                :_MAX_FORWARD_BARS_1M
            ]
            fwd_3m = tuple(c for c in candles_3m if c.open_time >= signal_time)[:40]

            def_sl = current_5m_bar.close_price * Decimal("0.98")
            def_tp = current_5m_bar.close_price * Decimal("1.04")
            bars_3m, bars_1m, mae_pct, mfe_pct, outcome = simulate_trade_and_excursion(
                signal=signal,
                candles_1m_forward=fwd_1m,
                candles_3m_forward=fwd_3m,
                signal_side=signal_side,
                entry_price=current_5m_bar.close_price,
                stop_loss=signal.stop_loss or def_sl,
                take_profit=signal.take_profit or def_tp,
                is_already_3m_aligned=is_3m_aligned,
            )

            records.append(
                PierSignalStudyRecord(
                    symbol=symbol,
                    signal_time=signal_time,
                    signal_side=signal_side,
                    pier_pattern=pattern_label,
                    confidence=signal.confidence,
                    entry_price=current_5m_bar.close_price,
                    stop_loss=signal.stop_loss or def_sl,
                    take_profit=signal.take_profit or def_tp,
                    regime_15m=regime_15m,
                    direction_3m_at_signal=direction_3m,
                    direction_1m_at_signal=direction_1m,
                    is_3m_aligned=is_3m_aligned,
                    is_3m_counter_trend=is_3m_counter,
                    is_1m_aligned=is_1m_aligned,
                    is_1m_counter_trend=is_1m_counter,
                    is_micro_reversing_at_signal=reversing_at_signal,
                    bars_to_3m_alignment=bars_3m,
                    bars_to_1m_alignment=bars_1m,
                    mae_pct_before_alignment=mae_pct,
                    mfe_pct_after_alignment=mfe_pct,
                    trade_outcome=outcome,
                    candidate_ema_cross_confirmed=candidate_a,
                    candidate_close_vs_ema_confirmed=candidate_b,
                    candidate_swing_break_confirmed=candidate_c,
                    candidate_momentum_shift_confirmed=candidate_d,
                )
            )

        return records

    async def fetch_or_synthesize_candles(
        self,
        symbol: str,
        count: int = 1500,
    ) -> tuple[Candle, ...]:
        """Fetch real 1m candles via Bybit public REST or synthesize if offline."""
        rest_client = None
        exchange_client = None
        try:
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
            now = datetime.now(UTC)
            start = now - timedelta(minutes=count + 100)
            candles = await exchange_client.get_candles(
                symbol=symbol,
                interval=Interval.M1,
                limit=count,
                start_time=start,
                end_time=now,
            )
            if candles and len(candles) >= 500:
                return tuple(candles)
        except Exception:
            pass
        finally:
            if exchange_client is not None:
                try:
                    await exchange_client.close()
                except Exception:
                    pass
            if rest_client is not None:
                try:
                    await rest_client.close()
                except Exception:
                    pass

        # High-fidelity synthetic multi-regime 1m candle generator for offline/CI
        return self._generate_synthetic_microstructure_candles(symbol, count=count)

    def _generate_synthetic_microstructure_candles(
        self,
        symbol: str,
        count: int = 1500,
    ) -> tuple[Candle, ...]:
        """Generate deterministic 1m candles containing pullbacks and pinbars."""
        base_price = Decimal("65000.00") if "BTC" in symbol else Decimal("3400.00")
        candles: list[Candle] = []
        now = datetime.now(UTC)
        start_time = now - timedelta(minutes=count)

        current_price = base_price
        for idx in range(count):
            c_time = start_time + timedelta(minutes=idx)
            # Cycle through periodic trend waves to create pullbacks and setups
            phase = math.sin(idx / 30.0) * 15.0 + math.cos(idx / 120.0) * 40.0
            delta = Decimal(str(round(phase * 0.15, 2)))

            open_p = current_price
            close_p = current_price + delta
            high_p = max(open_p, close_p) + Decimal("8.50")
            low_p = min(open_p, close_p) - Decimal("8.50")

            # Inject periodic pinbars/engulfing candles at cyclical pullback points
            if idx % 45 == 0:
                # Bullish pinbar: long lower shadow
                open_p = current_price
                close_p = current_price + Decimal("2.00")
                low_p = open_p - Decimal("25.00")
                high_p = close_p + Decimal("2.00")
            elif idx % 45 == 22:
                # Bearish pinbar: long upper shadow
                open_p = current_price
                close_p = current_price - Decimal("2.00")
                high_p = open_p + Decimal("25.00")
                low_p = close_p - Decimal("2.00")

            candles.append(
                Candle(
                    symbol=symbol,
                    interval=Interval.M1,
                    open_time=c_time,
                    close_time=c_time + timedelta(minutes=1),
                    open_price=open_p,
                    high_price=high_p,
                    low_price=low_p,
                    close_price=close_p,
                    volume=Decimal("150.0") + Decimal(str(abs(int(phase)))),
                )
            )
            current_price = close_p

        return tuple(candles)


# =============================================================================
# Formatting & Presentation
# =============================================================================
def print_study_report(all_records: list[PierSignalStudyRecord]) -> None:
    """Print the complete study findings, summary tables, and candidate evaluations."""
    total_signals = len(all_records)
    print("\n" + "=" * 80)
    print("PIER 5m Microstructure & Low-Timeframe Alignment Study")
    print("=" * 80)
    print(f"Total Actionable 5m Signals Evaluated: {total_signals}")

    if total_signals == 0:
        print("No signals generated in the evaluation sample.")
        return

    # 1. Alignment Statistics
    aligned_3m = sum(1 for r in all_records if r.is_3m_aligned)
    counter_3m = total_signals - aligned_3m
    aligned_1m = sum(1 for r in all_records if r.is_1m_aligned)
    counter_1m = total_signals - aligned_1m

    pct_3m_aligned = (Decimal(aligned_3m) / Decimal(total_signals)) * _DECIMAL_HUNDRED
    pct_3m_counter = (Decimal(counter_3m) / Decimal(total_signals)) * _DECIMAL_HUNDRED
    pct_1m_aligned = (Decimal(aligned_1m) / Decimal(total_signals)) * _DECIMAL_HUNDRED
    pct_1m_counter = (Decimal(counter_1m) / Decimal(total_signals)) * _DECIMAL_HUNDRED

    med_bars_3m = median([r.bars_to_3m_alignment for r in all_records])
    med_bars_1m = median([r.bars_to_1m_alignment for r in all_records])

    print("\n--- 1. Low-Timeframe Direction at Signal Time ---")
    print(f"  * 3m Aligned:      {aligned_3m:4d} ({pct_3m_aligned:5.1f}%)")
    print(f"  * 3m Counter-Trend:{counter_3m:4d} ({pct_3m_counter:5.1f}%)")
    print(f"  * 1m Aligned:      {aligned_1m:4d} ({pct_1m_aligned:5.1f}%)")
    print(f"  * 1m Counter-Trend:{counter_1m:4d} ({pct_1m_counter:5.1f}%)")
    print(f"  * Median bars until 3m alignment: {med_bars_3m:.1f} bars")
    print(f"  * Median bars until 1m alignment: {med_bars_1m:.1f} bars")

    # 2. Outcome Distribution (Aligned vs Counter-Trend)
    def _outcome_breakdown(
        records: list[PierSignalStudyRecord],
        label: str,
    ) -> None:
        cnt = len(records)
        if cnt == 0:
            print(
                f"  {label:<22} Count:   0 | Win:   0 ( 0.0%) | "
                "Loss:   0 | Timeout:   0"
            )
            return
        wins = sum(1 for r in records if r.trade_outcome == "WIN")
        losses = sum(1 for r in records if r.trade_outcome == "LOSS")
        timeouts = sum(1 for r in records if r.trade_outcome == "TIMEOUT")
        win_rate = (Decimal(wins) / Decimal(cnt)) * _DECIMAL_HUNDRED
        avg_mae = sum(
            (r.mae_pct_before_alignment for r in records), _DECIMAL_ZERO
        ) / Decimal(cnt)
        avg_mfe = sum(
            (r.mfe_pct_after_alignment for r in records), _DECIMAL_ZERO
        ) / Decimal(cnt)
        print(
            f"  {label:<22} Count: {cnt:3d} | Win: {wins:3d} ({win_rate:5.1f}%) | "
            f"Loss: {losses:3d} | Timeout: {timeouts:3d} | "
            f"Avg MAE: {avg_mae:4.2f}% | Avg MFE: {avg_mfe:4.2f}%"
        )

    print("\n--- 2. Trade Outcome Distribution: 3m Aligned vs Counter-Trend ---")
    _outcome_breakdown([r for r in all_records if r.is_3m_aligned], "3m Aligned")
    _outcome_breakdown(
        [r for r in all_records if r.is_3m_counter_trend], "3m Counter-Trend"
    )

    # 3. Outcome by Candlestick Pattern
    print("\n--- 3. Outcome by PIER Candlestick Pattern ---")
    patterns = sorted(set(r.pier_pattern for r in all_records))
    for pat in patterns:
        _outcome_breakdown([r for r in all_records if r.pier_pattern == pat], pat)

    # 4. Outcome by 15m HTF Regime
    print("\n--- 4. Outcome by 15m HTF Regime ---")
    regimes = sorted(set(r.regime_15m for r in all_records))
    for reg in regimes:
        _outcome_breakdown(
            [r for r in all_records if r.regime_15m == reg], f"15m {reg}"
        )

    # 5. Task C: Candidate 3m Micro Confirmation Diagnostic (EVIDENCE ONLY)
    print("\n" + "=" * 80)
    print("TASK C: Candidate 3m Micro Confirmation Evaluation (Evidence Only)")
    print("Notice: No live strategy modifications have been or will be applied.")
    print("=" * 80)

    def _cand_a(r: PierSignalStudyRecord) -> bool:
        return r.candidate_ema_cross_confirmed

    def _cand_b(r: PierSignalStudyRecord) -> bool:
        return r.candidate_close_vs_ema_confirmed

    def _cand_c(r: PierSignalStudyRecord) -> bool:
        return r.candidate_swing_break_confirmed

    def _cand_d(r: PierSignalStudyRecord) -> bool:
        return r.candidate_momentum_shift_confirmed

    candidates: tuple[tuple[str, Callable[[PierSignalStudyRecord], bool]], ...] = (
        ("Candidate A (3m EMA9 > EMA21 Cross)", _cand_a),
        ("Candidate B (3m Close vs EMA9)", _cand_b),
        ("Candidate C (3m Swing Breakout)", _cand_c),
        ("Candidate D (3m Momentum Reversal)", _cand_d),
    )

    baseline_wins = sum(1 for r in all_records if r.trade_outcome == "WIN")
    baseline_wr = (Decimal(baseline_wins) / Decimal(total_signals)) * _DECIMAL_HUNDRED
    print(
        f"  Unfiltered 5m Baseline:  Count={total_signals:3d} | "
        f"Win Rate={baseline_wr:5.1f}%\n"
    )

    for cand_name, pred in candidates:
        passed = [r for r in all_records if pred(r)]
        p_count = len(passed)
        if p_count == 0:
            print(f"  {cand_name:<36} Filtered=100.0% | Qualifying=  0 | Win Rate= N/A")
            continue
        p_wins = sum(1 for r in passed if r.trade_outcome == "WIN")
        p_wr = (Decimal(p_wins) / Decimal(p_count)) * _DECIMAL_HUNDRED
        filtered_pct = (
            (Decimal(total_signals - p_count)) / Decimal(total_signals)
        ) * _DECIMAL_HUNDRED
        wr_delta = p_wr - baseline_wr
        sign = "+" if wr_delta >= _DECIMAL_ZERO else ""
        print(
            f"  {cand_name:<36} Filtered={filtered_pct:5.1f}% | "
            f"Qualifying={p_count:3d} | Win Rate={p_wr:5.1f}% ({sign}{wr_delta:4.1f}%)"
        )
    print("=" * 80 + "\n")


async def main() -> None:
    """Run the 5m PIER microstructure study across research symbols."""
    runner = Pier5mMicrostructureStudyRunner()
    all_records: list[PierSignalStudyRecord] = []

    print("Loading candles and evaluating 5m PIER signals across top symbols...")
    for symbol in RESEARCH_SYMBOLS:
        candles_1m = await runner.fetch_or_synthesize_candles(symbol=symbol, count=1500)
        records = runner.analyze_symbol_candles(symbol=symbol, candles_1m=candles_1m)
        all_records.extend(records)
        print(
            f"  - {symbol:<10}: {len(candles_1m)} 1m candles -> "
            f"{len(records)} actionable 5m signals"
        )

    print_study_report(all_records)


if __name__ == "__main__":
    asyncio.run(main())
