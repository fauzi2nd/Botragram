"""
Botragram

Description:
    Low-timeframe (LTF) micro-confirmation and directional filter.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators.trend.ema import calculate_ema
from botragram.models import Candle

# =============================================================================
# Public Exports
# =============================================================================
__all__ = [
    "LtfConfirmationMode",
    "LtfMicroResult",
    "evaluate_ltf_micro_confirmation",
]


class LtfConfirmationMode(StrEnum):
    """Evaluation mode for low-timeframe micro-confirmation."""

    DIRECTION = "direction"
    EMA = "ema"
    BOTH = "both"
    MACD = "macd"
    CONFLUENCE = "confluence"


@dataclass(slots=True, kw_only=True, frozen=True)
class LtfMicroResult:
    """Result of low-timeframe micro-confirmation evaluation."""

    latest_close: Decimal
    latest_open: Decimal
    ema_value: Decimal | None
    is_aligned_with_buy: bool
    is_aligned_with_sell: bool
    mode: LtfConfirmationMode
    macd_histogram: Decimal | None = None


def evaluate_ltf_micro_confirmation(
    candles: Sequence[Candle],
    *,
    mode: LtfConfirmationMode | str = LtfConfirmationMode.DIRECTION,
    ema_period: int = 9,
    fail_closed: bool = False,
) -> LtfMicroResult:
    """Evaluate micro confirmation on a lower timeframe using closed candles.

    Args:
        candles: Sequence of closed candles from lower timeframe (e.g. 3m or 1m).
        mode: Confirmation mode - 'direction', 'ema', 'both', 'macd', or 'confluence'.
        ema_period: Lookback period for micro EMA (default 9).
        fail_closed: If True and data is insufficient, deny both buy and sell.

    Returns:
        LtfMicroResult detailing directional alignment with BUY and SELL.
    """
    parsed_mode: LtfConfirmationMode
    if isinstance(mode, LtfConfirmationMode):
        parsed_mode = mode
    else:
        try:
            parsed_mode = LtfConfirmationMode(mode.lower().strip())
        except ValueError:
            parsed_mode = LtfConfirmationMode.DIRECTION

    if not candles:
        return LtfMicroResult(
            latest_close=Decimal("0"),
            latest_open=Decimal("0"),
            ema_value=None,
            is_aligned_with_buy=not fail_closed,
            is_aligned_with_sell=not fail_closed,
            mode=parsed_mode,
            macd_histogram=None,
        )

    latest_candle = candles[-1]
    latest_close = latest_candle.close_price
    latest_open = latest_candle.open_price
    close_prices = [c.close_price for c in candles]

    # 1. Micro candle direction (bullish if close >= open, bearish if close <= open)
    is_dir_buy = latest_close >= latest_open
    is_dir_sell = latest_close <= latest_open

    # 2. Micro EMA alignment (bullish if close >= EMA, bearish if close <= EMA)
    ema_value: Decimal | None = None
    if parsed_mode in (
        LtfConfirmationMode.EMA,
        LtfConfirmationMode.BOTH,
        LtfConfirmationMode.CONFLUENCE,
    ):
        if len(candles) < ema_period:
            if fail_closed:
                is_ema_buy = False
                is_ema_sell = False
            else:
                is_ema_buy = True
                is_ema_sell = True
        else:
            ema_series = calculate_ema(close_prices, period=ema_period)
            ema_value = ema_series[-1]
            is_ema_buy = latest_close >= ema_value
            is_ema_sell = latest_close <= ema_value
    else:
        is_ema_buy = True
        is_ema_sell = True

    # 3. Micro MACD Momentum alignment (solid green for BUY, solid red for SELL)
    macd_hist_value: Decimal | None = None
    is_macd_buy = True
    is_macd_sell = True
    if parsed_mode in (LtfConfirmationMode.MACD, LtfConfirmationMode.CONFLUENCE):
        min_macd_candles = 34
        if len(candles) < min_macd_candles:
            if fail_closed:
                is_macd_buy = False
                is_macd_sell = False
        else:
            from botragram.indicators.momentum.macd import calculate_macd

            macd_res = calculate_macd(
                close_prices,
                fast_period=12,
                slow_period=26,
                signal_period=9,
            )
            if len(macd_res.histogram) >= 1:
                curr_h = macd_res.histogram[-1]
                macd_hist_value = curr_h
                prev_h = (
                    macd_res.histogram[-2] if len(macd_res.histogram) >= 2 else None
                )
                # BUY requires positive histogram and non-decaying (solid green)
                is_macd_buy = curr_h > Decimal("0") and (
                    prev_h is None or curr_h >= prev_h
                )
                # SELL requires negative histogram and non-rising (solid red)
                is_macd_sell = curr_h < Decimal("0") and (
                    prev_h is None or curr_h <= prev_h
                )

    # 4. Micro Bollinger Bands alignment (discount zone for BUY, premium for SELL)
    is_bb_buy = True
    is_bb_sell = True
    if parsed_mode is LtfConfirmationMode.CONFLUENCE:
        bb_period = 20
        if len(candles) < bb_period:
            if fail_closed:
                is_bb_buy = False
                is_bb_sell = False
        else:
            from botragram.indicators.volatility.bollinger_bands import (
                calculate_bollinger_bands,
            )

            bb_res = calculate_bollinger_bands(
                close_prices,
                period=bb_period,
                standard_deviation=Decimal("2.0"),
            )
            curr_mid = bb_res.middle[-1]
            curr_upper = bb_res.upper[-1]
            curr_lower = bb_res.lower[-1]
            # BUY: close <= mid and no bearish rejection from upper band
            is_bb_buy = (latest_close <= curr_mid) and not (
                latest_candle.high_price >= curr_upper and latest_close < latest_open
            )
            # SELL: close >= mid and no bullish rejection from lower band
            is_bb_sell = (latest_close >= curr_mid) and not (
                latest_candle.low_price <= curr_lower and latest_close > latest_open
            )

    # 5. Combine checks based on mode
    if parsed_mode is LtfConfirmationMode.DIRECTION:
        aligned_buy = is_dir_buy
        aligned_sell = is_dir_sell
    elif parsed_mode is LtfConfirmationMode.EMA:
        aligned_buy = is_ema_buy
        aligned_sell = is_ema_sell
    elif parsed_mode is LtfConfirmationMode.BOTH:
        aligned_buy = is_dir_buy and is_ema_buy
        aligned_sell = is_dir_sell and is_ema_sell
    elif parsed_mode is LtfConfirmationMode.MACD:
        aligned_buy = is_macd_buy
        aligned_sell = is_macd_sell
    else:  # CONFLUENCE
        aligned_buy = is_dir_buy and is_ema_buy and is_macd_buy and is_bb_buy
        aligned_sell = is_dir_sell and is_ema_sell and is_macd_sell and is_bb_sell

    return LtfMicroResult(
        latest_close=latest_close,
        latest_open=latest_open,
        ema_value=ema_value,
        is_aligned_with_buy=aligned_buy,
        is_aligned_with_sell=aligned_sell,
        mode=parsed_mode,
        macd_histogram=macd_hist_value,
    )
