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

from botragram.enums import FuturesAlgoOrderStatus, OrderType
from botragram.models.balance import Balance
from botragram.models.order import Order

__all__ = [
    "FuturesUserDataAccountUpdate",
    "FuturesUserDataAlgoUpdate",
    "FuturesUserDataEvent",
    "FuturesUserDataOrderUpdate",
    "FuturesUserDataPositionUpdate",
    "FuturesUserDataStreamConnected",
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
class FuturesUserDataAlgoUpdate:
    """One conditional SL/TP order-state update from the private stream."""

    observed_at: datetime
    client_algo_id: str
    algo_id: str
    symbol: str
    status: FuturesAlgoOrderStatus
    order_type: OrderType
    trigger_price: Decimal | None


@dataclass(slots=True, kw_only=True, frozen=True)
class FuturesUserDataOrderUpdate:
    """One normalized Futures order-status update from the private stream."""

    observed_at: datetime
    order: Order


@dataclass(slots=True, kw_only=True, frozen=True)
class FuturesUserDataStreamConnected:
    """Signal that a private stream session is ready to buffer events."""

    observed_at: datetime


type FuturesUserDataEvent = (
    FuturesUserDataAccountUpdate
    | FuturesUserDataAlgoUpdate
    | FuturesUserDataOrderUpdate
    | FuturesUserDataStreamConnected
)
