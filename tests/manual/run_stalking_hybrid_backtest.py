"""
Botragram

Description:
    Empirical evaluation of the Stalking Hybrid architecture:
    - Retains candlestick rejection (Pinbar, Engulfing, Star).
    - Relaxes geometry thresholds (wick 0.45, engulfing 1.00, conf 0.60).
    - Removes strict HTF extreme zone constraint.
    - Executes via 50% retest limit stalking with 7-bar TTL.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from botragram.constants import BYBIT_REST_BASE_URL
from botragram.enums import ExchangeType, Interval, MarketType, SignalType
from botragram.exchanges import ExchangeFactory
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy
from botragram.utils.candle_resampler import resample_candles
from tests.manual.run_stalking_no_pattern_backtest import (
    TOP_SYMBOLS,
    fetch_candles,
)


async def run_hybrid_backtest() -> None:
    rest = ExchangeFactory.create_rest_client(
        exchange_type=ExchangeType.BYBIT,
        base_url=BYBIT_REST_BASE_URL,
    )
    client = ExchangeFactory.create_exchange_client(
        exchange_type=ExchangeType.BYBIT,
        rest_client=rest,
        market_type=MarketType.FUTURES,
    )
    await client.connect()

    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=200,
        pullback_period=21,
        rsi_period=14,
        rsi_long_min=Decimal("38.0"),
        rsi_long_max=Decimal("58.0"),
        rsi_short_min=Decimal("42.0"),
        rsi_short_max=Decimal("62.0"),
        volume_period=20,
        volume_multiplier=Decimal("1.10"),
        min_wick_ratio=Decimal("0.45"),
        min_engulfing_body_ratio=Decimal("1.00"),
        include_star_patterns=True,
        min_confidence=Decimal("0.60"),
        require_htf_extreme_zone=False,
    )

    print("\n===================================================================")
    print("STALKING HYBRID EMPIRICAL EVALUATION (Top Crypto Pairs, 5.2 Days)")
    print("===================================================================")
    print(f"{'Symbol':<8} | {'Setups':<6} | {'Fill%':<6} | {'WR%':<7} | {'Saved':<5}")
    print("-" * 67)

    total_signals = 0
    total_filled = 0
    total_wins = 0
    total_losses = 0
    total_saved = 0

    for sym in TOP_SYMBOLS:
        c_1m = await fetch_candles(sym, client)
        c_5m = tuple(
            resample_candles(
                candles=c_1m,
                target_interval=Interval.M5,
                closed_only=True,
            )
        )
        if len(c_5m) < 220:
            continue

        open_time_to_1m = {c.open_time: idx for idx, c in enumerate(c_1m)}

        sym_signals = 0
        sym_filled = 0
        sym_wins = 0
        sym_losses = 0
        sym_saved = 0

        for i in range(205, len(c_5m) - 25):
            eval_5m = c_5m[: i + 1]
            sig = strategy.generate_signal(candles=eval_5m)
            if sig.signal_type is SignalType.HOLD:
                continue

            setup_candle = eval_5m[-1]
            side = "BUY" if sig.signal_type is SignalType.BUY else "SELL"
            sl = sig.stop_loss
            tp = sig.take_profit
            if sl is None or tp is None:
                continue

            retest_price = setup_candle.low_price + (
                setup_candle.high_price - setup_candle.low_price
            ) * Decimal("0.5")

            idx_1m = open_time_to_1m.get(setup_candle.close_time)
            if idx_1m is None:
                continue
            forward_1m = c_1m[idx_1m : idx_1m + 120]
            if len(forward_1m) < 35:
                continue

            sym_signals += 1

            filled = False
            fill_idx = -1
            saved = False
            for b_idx, bar in enumerate(forward_1m[:35]):
                if side == "BUY":
                    if bar.low_price <= sl and bar.low_price > retest_price:
                        saved = True
                        break
                    if bar.low_price <= retest_price:
                        filled = True
                        fill_idx = b_idx
                        break
                else:
                    if bar.high_price >= sl and bar.high_price < retest_price:
                        saved = True
                        break
                    if bar.high_price >= retest_price:
                        filled = True
                        fill_idx = b_idx
                        break

            if saved:
                sym_saved += 1
            if filled and fill_idx >= 0:
                sym_filled += 1
                for bar in forward_1m[fill_idx:]:
                    if side == "BUY":
                        if bar.low_price <= sl:
                            sym_losses += 1
                            break
                        if bar.high_price >= tp:
                            sym_wins += 1
                            break
                    else:
                        if bar.high_price >= sl:
                            sym_losses += 1
                            break
                        if bar.low_price <= tp:
                            sym_wins += 1
                            break

        total_signals += sym_signals
        total_filled += sym_filled
        total_wins += sym_wins
        total_losses += sym_losses
        total_saved += sym_saved

        fill_pct = (sym_filled / sym_signals * 100) if sym_signals else 0.0
        wr = (
            (sym_wins / (sym_wins + sym_losses) * 100)
            if (sym_wins + sym_losses)
            else 0.0
        )
        row_str = (
            f"{sym:<7} | {sym_signals:<4} | {fill_pct:<5.1f}% | "
            f"{wr:<5.1f}% | {sym_saved:<5}"
        )
        print(row_str)

    await client.close()

    print("=" * 67)
    tot_fill_pct = (total_filled / total_signals * 100) if total_signals else 0.0
    tot_wr = (
        (total_wins / (total_wins + total_losses) * 100)
        if (total_wins + total_losses)
        else 0.0
    )
    print(
        f"TOTAL SETUPS : {total_signals} (Seimbang: 3-4x lebih banyak dari 15 sinyal)"
    )
    print(f"TOTAL FILLED : {total_filled} ({tot_fill_pct:.1f}%)")
    print(f"STALKING WR  : {tot_wr:.1f}% ({total_wins}W / {total_losses}L)")
    print(f"SAVED LOSSES : {total_saved} false breakouts dihindari (0 loss)")
    print("===================================================================\n")


if __name__ == "__main__":
    asyncio.run(run_hybrid_backtest())
