"""
Botragram

Description:
    Binance Futures conditional-order status enumeration.

Python:
    3.14+
"""

from __future__ import annotations

from enum import unique

from botragram.enums.base import BaseEnum

__all__ = ["FuturesAlgoOrderStatus"]


@unique
class FuturesAlgoOrderStatus(BaseEnum):
    """Conditional-order statuses published by Binance Futures."""

    NEW = "new"
    CANCELED = "canceled"
    TRIGGERING = "triggering"
    TRIGGERED = "triggered"
    FINISHED = "finished"
    REJECTED = "rejected"
    EXPIRED = "expired"
