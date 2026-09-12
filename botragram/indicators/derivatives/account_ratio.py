"""
Botragram

Description:
    Account Long-Short Ratio sentiment indicator for derivatives positioning.

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
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

__all__ = [
    "AccountRatioSentiment",
    "evaluate_account_ratio_sentiment",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DEFAULT_MAX_LONG_RATIO: Final[Decimal] = Decimal("0.75")
_DEFAULT_MIN_SHORT_RATIO: Final[Decimal] = Decimal("0.25")


# =============================================================================
# Data Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class AccountRatioSentiment:
    """Institutional crowd positioning sentiment derived from account ratio."""

    buy_ratio: Decimal
    sell_ratio: Decimal
    is_crowded_long: bool
    is_crowded_short: bool
    is_neutral: bool
    reason: str


# =============================================================================
# Public Functions
# =============================================================================
def evaluate_account_ratio_sentiment(
    *,
    buy_ratio: Decimal,
    sell_ratio: Decimal | None = None,
    max_long_ratio: Decimal = _DEFAULT_MAX_LONG_RATIO,
    min_short_ratio: Decimal = _DEFAULT_MIN_SHORT_RATIO,
) -> AccountRatioSentiment:
    """Evaluate institutional crowd positioning sentiment.

    Args:
        buy_ratio: Fraction of accounts net long (between 0.0 and 1.0).
        sell_ratio: Optional fraction of accounts net short
            (defaults to 1 - buy_ratio).
        max_long_ratio: Threshold above which crowd is crowded long
            (default 0.75 / 75%).
        min_short_ratio: Threshold below which crowd is crowded short
            (default 0.25 / 25%).

    Returns:
        AccountRatioSentiment classification.
    """
    resolved_sell_ratio = (
        sell_ratio if sell_ratio is not None else (_DECIMAL_ONE - buy_ratio)
    )

    if buy_ratio > max_long_ratio:
        return AccountRatioSentiment(
            buy_ratio=buy_ratio,
            sell_ratio=resolved_sell_ratio,
            is_crowded_long=True,
            is_crowded_short=False,
            is_neutral=False,
            reason=(
                f"CROWDED_LONG: {buy_ratio:.1%} accounts long (>{max_long_ratio:.1%})"
            ),
        )

    if buy_ratio < min_short_ratio:
        return AccountRatioSentiment(
            buy_ratio=buy_ratio,
            sell_ratio=resolved_sell_ratio,
            is_crowded_long=False,
            is_crowded_short=True,
            is_neutral=False,
            reason=(
                f"CROWDED_SHORT: {buy_ratio:.1%} accounts long (<{min_short_ratio:.1%})"
            ),
        )

    return AccountRatioSentiment(
        buy_ratio=buy_ratio,
        sell_ratio=resolved_sell_ratio,
        is_crowded_long=False,
        is_crowded_short=False,
        is_neutral=True,
        reason=f"BALANCED: {buy_ratio:.1%} accounts long",
    )
