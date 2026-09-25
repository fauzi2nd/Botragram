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


@dataclass(slots=True, kw_only=True, frozen=True)
class LtfMicroResult:
    """Result of low-timeframe micro-confirmation evaluation."""

    latest_close: Decimal
    latest_open: Decimal
    ema_value: Decimal | None
    is_aligned_with_buy: bool
    is_aligned_with_sell: bool
    mode: LtfConfirmationMode


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
        mode: Confirmation mode - 'direction' (candle direction), 'ema' (close vs EMA),
            or 'both' (both direction and EMA alignment).
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
            parsed_mode = LtfConfirmationMode(str(mode).lower().strip())
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
        )

    latest_candle = candles[-1]
    latest_close = latest_candle.close_price
    latest_open = latest_candle.open_price

    # 1. Micro candle direction (bullish if close >= open, bearish if close <= open)
    is_dir_buy = latest_close >= latest_open
    is_dir_sell = latest_close <= latest_open

    # 2. Micro EMA alignment (bullish if close >= EMA, bearish if close <= EMA)
    ema_value: Decimal | None = None
    if parsed_mode in (LtfConfirmationMode.EMA, LtfConfirmationMode.BOTH):
        if len(candles) < ema_period:
            if fail_closed:
                is_ema_buy = False
                is_ema_sell = False
            else:
                is_ema_buy = True
                is_ema_sell = True
        else:
            close_prices = [c.close_price for c in candles]
            ema_series = calculate_ema(close_prices, period=ema_period)
            ema_value = ema_series[-1]
            is_ema_buy = latest_close >= ema_value
            is_ema_sell = latest_close <= ema_value
    else:
        is_ema_buy = True
        is_ema_sell = True

    # 3. Combine checks based on mode
    if parsed_mode is LtfConfirmationMode.DIRECTION:
        aligned_buy = is_dir_buy
        aligned_sell = is_dir_sell
    elif parsed_mode is LtfConfirmationMode.EMA:
        aligned_buy = is_ema_buy
        aligned_sell = is_ema_sell
    else:  # BOTH
        aligned_buy = is_dir_buy and is_ema_buy
        aligned_sell = is_dir_sell and is_ema_sell

    return LtfMicroResult(
        latest_close=latest_close,
        latest_open=latest_open,
        ema_value=ema_value,
        is_aligned_with_buy=aligned_buy,
        is_aligned_with_sell=aligned_sell,
        mode=parsed_mode,
    )
