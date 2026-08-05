"""
Botragram

Description:
    Base exchange payload mapper interface.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from abc import ABC, abstractmethod
from collections.abc import Mapping

from botragram.enums import Interval

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import Account, Candle, Order, Position, Ticker, Trade

__all__ = [
    "BaseExchangeMapper",
    "ExchangePayload",
    "ExchangeSequencePayload",
]


# =============================================================================
# Type Aliases
# =============================================================================
type ExchangePayload = Mapping[str, object]
type ExchangeSequencePayload = tuple[object, ...]


# =============================================================================
# Abstract Base Mapper Class
# =============================================================================
class BaseExchangeMapper(ABC):
    """Convert exchange-specific payloads into domain models."""

    @abstractmethod
    def map_account(
        self,
        payload: ExchangePayload,
    ) -> Account:
        """Map an account payload into an Account model.

        Args:
            payload: Raw exchange account payload.

        Returns:
            Standardized account model.
        """

    @abstractmethod
    def map_ticker(
        self,
        payload: ExchangePayload,
    ) -> Ticker:
        """Map a ticker payload into a Ticker model.

        Args:
            payload: Raw exchange ticker payload.

        Returns:
            Standardized ticker model.
        """

    @abstractmethod
    def map_candle(
        self,
        payload: ExchangeSequencePayload,
        *,
        symbol: str,
        interval: Interval,
    ) -> Candle:
        """Map a candle payload into a Candle model.

        Args:
            payload: Raw exchange candle payload.
            symbol: Trading pair associated with the candle.
            interval: Candle interval.

        Returns:
            Standardized candle model.
        """

    @abstractmethod
    def map_order(
        self,
        payload: ExchangePayload,
    ) -> Order:
        """Map an order payload into an Order model.

        Args:
            payload: Raw exchange order payload.

        Returns:
            Standardized order model.
        """

    @abstractmethod
    def map_position(
        self,
        payload: ExchangePayload,
    ) -> Position:
        """Map a position payload into a Position model.

        Args:
            payload: Raw exchange position payload.

        Returns:
            Standardized position model.
        """

    @abstractmethod
    def map_trade(
        self,
        payload: ExchangePayload,
    ) -> Trade:
        """Map a trade payload into a Trade model.

        Args:
            payload: Raw exchange trade payload.

        Returns:
            Standardized trade model.
        """
