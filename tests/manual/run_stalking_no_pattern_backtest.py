"""
Botragram

Description:
    Comparative backtest simulation evaluating the "Pattern-Free Stalking" hypothesis:
    What happens if we IGNORE candlestick patterns (Pinbar / Engulfing / Star)
    and focus purely on Trend + Pullback Zone + RSI Stalking with Limit/Retest Entry?

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from botragram.constants import BYBIT_REST_BASE_URL
from botragram.enums import ExchangeType, Interval, MarketType
from botragram.exchanges import ExchangeFactory
from botragram.exchanges.base import BaseExchangeClient
from botragram.indicators import calculate_atr, calculate_ema, calculate_rsi
from botragram.models import Candle
from botragram.utils.candle_resampler import resample_candles

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_HALF: Final[Decimal] = Decimal("0.5")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DECIMAL_TWO: Final[Decimal] = Decimal("2.0")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")

TOP_SYMBOLS: Final[tuple[str, ...]] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
)

_STALKING_TTL_1M_BARS: Final[int] = 35  # 7 x 5m candles = 35 1m bars
_FORWARD_HORIZON_1M_BARS: Final[int] = 150  # 2.5 hours forward tracking


@dataclass(slots=True, kw_only=True, frozen=True)
class StalkingTradeRecord:
    symbol: str
    side: str
    signal_time: datetime
    setup_close: Decimal
    entry_limit_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal

    # Immediate Entry Results
    immediate_outcome: str  # WIN, LOSS, TIMEOUT
    immediate_pnl_pct: Decimal

    # Stalking Retest Entry Results
    stalking_filled: bool
    bars_to_fill: int
    stalking_outcome: str  # WIN, LOSS, TIMEOUT, MISSED, SAVED_LOSS
    stalking_pnl_pct: Decimal
    risk_reduction_pct: Decimal


async def fetch_candles(
    symbol: str,
    client: BaseExchangeClient,
) -> tuple[Candle, ...]:
    all_candles: list[Candle] = []
    now = datetime.now(UTC)
    curr_end: datetime = now
    for _ in range(4):
        curr_start: datetime = curr_end - timedelta(minutes=1000)
        batch = tuple(
            await client.get_candles(
                symbol=symbol,
                interval=Interval.M1,
                limit=1000,
                start_time=curr_start,
                end_time=curr_end,
            )
        )
        if not batch:
            break
        all_candles = list(batch) + all_candles
        curr_end = batch[0].open_time

    # Deduplicate and sort
    seen: set[datetime] = set()
    dedup: list[Candle] = []
    for c in sorted(all_candles, key=lambda x: x.open_time):
        if c.open_time not in seen:
            seen.add(c.open_time)
            dedup.append(c)
    return tuple(dedup)


def evaluate_symbol(
    symbol: str,
    candles_1m: tuple[Candle, ...],
) -> list[StalkingTradeRecord]:
    if len(candles_1m) < 600:
        return []

    candles_5m = tuple(
        resample_candles(
            candles=candles_1m,
            target_interval=Interval.M5,
            closed_only=True,
        )
    )
    if len(candles_5m) < 220:
        return []

    open_time_to_1m_idx = {c.open_time: idx for idx, c in enumerate(candles_1m)}

    records: list[StalkingTradeRecord] = []
    last_signal_bar = -99

    for i in range(205, len(candles_5m) - 30):
        if i - last_signal_bar < 6:  # 30-minute cooldown between setups on same symbol
            continue

        slice_5m = candles_5m[: i + 1]
        closes_slice = tuple(c.close_price for c in slice_5m)
        highs_slice = tuple(c.high_price for c in slice_5m)
        lows_slice = tuple(c.low_price for c in slice_5m)

        close_curr = closes_slice[-1]
        high_curr = highs_slice[-1]
        low_curr = lows_slice[-1]

        ema_200 = calculate_ema(closes_slice, period=200)
        ema_21 = calculate_ema(closes_slice, period=21)
        rsi_14 = calculate_rsi(closes_slice, period=14)
        atr_14 = calculate_atr(highs_slice, lows_slice, closes_slice, period=14)

        if not ema_200 or not ema_21 or not rsi_14 or not atr_14:
            continue

        curr_ema200 = ema_200[-1]
        curr_ema21 = ema_21[-1]
        curr_rsi = rsi_14[-1]
        curr_atr = atr_14[-1]

        if curr_atr <= _DECIMAL_ZERO or close_curr <= _DECIMAL_ZERO:
            continue

        natr = curr_atr / close_curr
        if natr < Decimal("0.0012"):  # Reject completely dead volatility
            continue

        side: str | None = None

        # BUY Setup: Price > EMA 200, EMA 21 >= EMA 200, Pullback into EMA 21
        # NO CANDLESTICK PATTERN REQUIRED!
        tolerance = Decimal("0.5") * curr_atr
        touches_ema21_buy = (low_curr <= curr_ema21 + tolerance) and (
            high_curr >= curr_ema21 - tolerance
        )
        if (
            close_curr > curr_ema200
            and curr_ema21 >= curr_ema200
            and touches_ema21_buy
            and Decimal("38.0") <= curr_rsi <= Decimal("58.0")
        ):
            side = "BUY"

        # SELL Setup: Price < EMA 200, EMA 21 <= EMA 200, Pullback into EMA 21
        touches_ema21_sell = (high_curr >= curr_ema21 - tolerance) and (
            low_curr <= curr_ema21 + tolerance
        )
        if (
            side is None
            and close_curr < curr_ema200
            and curr_ema21 <= curr_ema200
            and touches_ema21_sell
            and Decimal("42.0") <= curr_rsi <= Decimal("62.0")
        ):
            side = "SELL"

        if side is None:
            continue

        setup_candle = candles_5m[i]
        setup_close = setup_candle.close_price

        # Stalking Limit Price: placed at EMA 21 level (retest sweet spot)
        entry_limit = curr_ema21

        if side == "BUY":
            stop_loss = entry_limit - Decimal("1.2") * curr_atr
            if stop_loss >= entry_limit or stop_loss >= setup_close:
                continue
            risk = entry_limit - stop_loss
            take_profit = entry_limit + (_DECIMAL_TWO * risk)
            imm_sl = stop_loss
            imm_tp = setup_close + (_DECIMAL_TWO * (setup_close - imm_sl))
        else:
            stop_loss = entry_limit + Decimal("1.2") * curr_atr
            if stop_loss <= entry_limit or stop_loss <= setup_close:
                continue
            risk = stop_loss - entry_limit
            take_profit = entry_limit - (_DECIMAL_TWO * risk)
            imm_sl = stop_loss
            imm_tp = setup_close - (_DECIMAL_TWO * (imm_sl - setup_close))

        start_1m_idx = open_time_to_1m_idx.get(setup_candle.close_time)
        if start_1m_idx is None:
            continue

        forward_1m = candles_1m[start_1m_idx : start_1m_idx + _FORWARD_HORIZON_1M_BARS]
        if len(forward_1m) < 35:
            continue

        # 1. Simulate Immediate Market Entry (Baseline)
        imm_outcome = "TIMEOUT"
        imm_pnl = _DECIMAL_ZERO
        imm_risk_pct = abs(setup_close - imm_sl) / setup_close
        for bar in forward_1m:
            if side == "BUY":
                if bar.low_price <= imm_sl:
                    imm_outcome = "LOSS"
                    imm_pnl = -imm_risk_pct
                    break
                if bar.high_price >= imm_tp:
                    imm_outcome = "WIN"
                    imm_pnl = _DECIMAL_TWO * imm_risk_pct
                    break
            else:
                if bar.high_price >= imm_sl:
                    imm_outcome = "LOSS"
                    imm_pnl = -imm_risk_pct
                    break
                if bar.low_price <= imm_tp:
                    imm_outcome = "WIN"
                    imm_pnl = _DECIMAL_TWO * imm_risk_pct
                    break

        # 2. Simulate Stalking Limit Retest Entry (TTL = 35 minutes)
        stalking_filled = False
        fill_idx = -1
        stalking_outcome = "MISSED"
        stalking_pnl = _DECIMAL_ZERO

        ttl_window = forward_1m[:_STALKING_TTL_1M_BARS]
        for idx, bar in enumerate(ttl_window):
            if side == "BUY":
                # If price crashes through SL before filling limit, saved loss
                if bar.low_price <= stop_loss and bar.low_price > entry_limit:
                    stalking_outcome = "SAVED_LOSS"
                    break
                if bar.low_price <= entry_limit:
                    stalking_filled = True
                    fill_idx = idx
                    break
            else:
                if bar.high_price >= stop_loss and bar.high_price < entry_limit:
                    stalking_outcome = "SAVED_LOSS"
                    break
                if bar.high_price >= entry_limit:
                    stalking_filled = True
                    fill_idx = idx
                    break

        if not stalking_filled:
            if imm_outcome == "LOSS" and stalking_outcome != "SAVED_LOSS":
                stalking_outcome = "SAVED_LOSS"
            elif imm_outcome == "WIN":
                stalking_outcome = "MISSED"
        else:
            # Filled! Forward evaluate trade outcome
            stalking_risk_pct = abs(entry_limit - stop_loss) / entry_limit
            stalking_outcome = "TIMEOUT"
            post_fill = forward_1m[fill_idx:]
            for bar in post_fill:
                if side == "BUY":
                    if bar.low_price <= stop_loss:
                        stalking_outcome = "LOSS"
                        stalking_pnl = -stalking_risk_pct
                        break
                    if bar.high_price >= take_profit:
                        stalking_outcome = "WIN"
                        stalking_pnl = _DECIMAL_TWO * stalking_risk_pct
                        break
                else:
                    if bar.high_price >= stop_loss:
                        stalking_outcome = "LOSS"
                        stalking_pnl = -stalking_risk_pct
                        break
                    if bar.low_price <= take_profit:
                        stalking_outcome = "WIN"
                        stalking_pnl = _DECIMAL_TWO * stalking_risk_pct
                        break

        risk_red = (
            (
                (imm_risk_pct - (abs(entry_limit - stop_loss) / entry_limit))
                / imm_risk_pct
            )
            * _DECIMAL_HUNDRED
            if imm_risk_pct > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )

        records.append(
            StalkingTradeRecord(
                symbol=symbol,
                side=side,
                signal_time=setup_candle.close_time,
                setup_close=setup_close,
                entry_limit_price=entry_limit,
                stop_loss=stop_loss,
                take_profit=take_profit,
                immediate_outcome=imm_outcome,
                immediate_pnl_pct=imm_pnl * _DECIMAL_HUNDRED,
                stalking_filled=stalking_filled,
                bars_to_fill=fill_idx + 1 if stalking_filled else 0,
                stalking_outcome=stalking_outcome,
                stalking_pnl_pct=stalking_pnl * _DECIMAL_HUNDRED,
                risk_reduction_pct=risk_red,
            )
        )
        last_signal_bar = i

    return records


async def main() -> None:
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

    print("\n=====================================================================")
    print("BACKTEST: PATTERN-FREE STALKING (Trend + EMA21 + RSI + Stalking Limit)")
    print("=====================================================================")
    print("Evaluating Top Crypto Pairs over ~1,500 5m candles (~5.2 days)\n")

    all_records: list[StalkingTradeRecord] = []

    print(
        f"{'Symbol':<8} | {'Set':<4} | {'Fill%':<5} | {'Imm WR%':<7} | {'Stalk WR%':<9}"
    )
    print("-" * 55)

    for sym in TOP_SYMBOLS:
        candles_1m = await fetch_candles(sym, client)
        recs = evaluate_symbol(sym, candles_1m)
        all_records.extend(recs)

        n_setups = len(recs)
        if n_setups == 0:
            print(f"{sym:<8} | {0:<4} | {'0.0%':<5} | {'0.0%':<7} | {'0.0%':<9}")
            continue

        n_filled = sum(1 for r in recs if r.stalking_filled)
        fill_pct = (n_filled / n_setups) * 100

        imm_wins = sum(1 for r in recs if r.immediate_outcome == "WIN")
        imm_losses = sum(1 for r in recs if r.immediate_outcome == "LOSS")
        imm_resolved = imm_wins + imm_losses
        imm_wr = (imm_wins / imm_resolved * 100) if imm_resolved > 0 else 0.0

        stalk_wins = sum(1 for r in recs if r.stalking_outcome == "WIN")
        stalk_losses = sum(1 for r in recs if r.stalking_outcome == "LOSS")
        stalk_resolved = stalk_wins + stalk_losses
        stalk_wr = (stalk_wins / stalk_resolved * 100) if stalk_resolved > 0 else 0.0

        row_str = (
            f"{sym:<6} | {n_setups:<3} | {fill_pct:<4.1f}% | "
            f"{imm_wr:<5.1f}% | {stalk_wr:<6.1f}%"
        )
        print(row_str)

    await client.close()

    print("=" * 55)
    total_setups = len(all_records)
    total_filled = sum(1 for r in all_records if r.stalking_filled)
    total_imm_wins = sum(1 for r in all_records if r.immediate_outcome == "WIN")
    total_imm_losses = sum(1 for r in all_records if r.immediate_outcome == "LOSS")
    total_imm_res = total_imm_wins + total_imm_losses
    total_imm_wr = (total_imm_wins / total_imm_res * 100) if total_imm_res > 0 else 0.0
    total_imm_pnl = sum(r.immediate_pnl_pct for r in all_records)

    total_stalk_wins = sum(1 for r in all_records if r.stalking_outcome == "WIN")
    total_stalk_losses = sum(1 for r in all_records if r.stalking_outcome == "LOSS")
    total_stalk_res = total_stalk_wins + total_stalk_losses
    total_stalk_wr = (
        (total_stalk_wins / total_stalk_res * 100) if total_stalk_res > 0 else 0.0
    )
    total_stalk_pnl = sum(r.stalking_pnl_pct for r in all_records)

    total_saved_l = sum(1 for r in all_records if r.stalking_outcome == "SAVED_LOSS")
    total_missed_w = sum(1 for r in all_records if r.stalking_outcome == "MISSED")

    print(f"TOTAL SETUPS DETECTED : {total_setups} (vs ~15 setups with patterns)")
    tot_fill_pct = (total_filled / total_setups * 100) if total_setups else 0.0
    print(f"STALKING FILL RATE    : {tot_fill_pct:.1f}%")
    print(f"IMM ENTRY WR : {total_imm_wr:.1f}% | Net PnL: {total_imm_pnl:+.1f}%")
    print(f"STALK WR     : {total_stalk_wr:.1f}% | Net PnL: {total_stalk_pnl:+.1f}%")
    print(f"SAVED LOSSES (TRAPS)  : {total_saved_l} trades")
    print(f"MISSED WINNERS        : {total_missed_w} trades")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
