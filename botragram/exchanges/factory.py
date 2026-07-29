"""
Botragram

Description:
    Exchange client factory.

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
import logging

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.exchange_settings import ExchangeSettings
from botragram.enums.exchange_type import ExchangeType
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.binance.client import BinanceClient
from botragram.exchanges.bybit.client import BybitClient

logger = logging.getLogger(__name__)


# =============================================================================
# Factory Function
# =============================================================================
def create_exchange_client(settings: ExchangeSettings) -> BaseExchangeClient:
    """Instantiate the correct exchange client based on settings.

    Args:
        settings: ExchangeSettings with exchange_type and credentials.

    Returns:
        Initialized BaseExchangeClient instance.

    Raises:
        NotImplementedError: If exchange_type is not yet implemented.
    """
    if settings.exchange_type == ExchangeType.BYBIT:
        logger.info(
            f"Creating BybitClient (testnet={settings.testnet})"
        )
        return BybitClient(
            api_key=settings.api_key,
            api_secret=settings.api_secret,
            testnet=settings.testnet,
        )

    if settings.exchange_type == ExchangeType.BINANCE:
        logger.info(
            f"Creating BinanceClient (testnet={settings.testnet})"
        )
        return BinanceClient(
            api_key=settings.api_key,
            api_secret=settings.api_secret,
            testnet=settings.testnet,
        )

    if settings.exchange_type in (ExchangeType.OKX, ExchangeType.BITGET):
        raise NotImplementedError(
            f"{settings.exchange_type.value.upper()} connector is not implemented."
        )

    raise NotImplementedError(
        f"Exchange type '{settings.exchange_type}' is not supported."
    )
