"""
Botragram

Description:
    Immutable Binance Futures private-stream domain events.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from botragram.models.balance import Balance
from botragram.models.order import Order

__all__ = [
    "FuturesUserDataAccountUpdate",
    "FuturesUserDataEvent",
    "FuturesUserDataOrderUpdate",
    "FuturesUserDataPositionUpdate",
]


@dataclass(slots=True, kw_only=True, frozen=True)
class FuturesUserDataPositionUpdate:
    """One real-time Futures exposure update from the account stream."""

    symbol: str
    quantity: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal


@dataclass(slots=True, kw_only=True, frozen=True)
class FuturesUserDataAccountUpdate:
    """One account balance and position update from the private stream."""

    observed_at: datetime
    balances: tuple[Balance, ...]
    positions: tuple[FuturesUserDataPositionUpdate, ...]


@dataclass(slots=True, kw_only=True, frozen=True)
class FuturesUserDataOrderUpdate:
    """One normalized Futures order-status update from the private stream."""

    observed_at: datetime
    order: Order


type FuturesUserDataEvent = FuturesUserDataAccountUpdate | FuturesUserDataOrderUpdate
