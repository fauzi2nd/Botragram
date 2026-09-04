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
# Local Imports
# =============================================================================
from botragram.enums import ExchangeType, MarketType
from botragram.exchanges.base import (
    BaseExchangeClient,
    BaseRestClient,
    BaseStreamClient,
)
from botragram.exchanges.binance.authoritative_futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.client import BinanceExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.exchanges.binance.stream import BinanceStreamClient
from botragram.exchanges.bybit import (
    BybitExchangeClient,
    BybitExchangeMapper,
    BybitFuturesExchangeClient,
    BybitRestClient,
    BybitStreamClient,
)

__all__ = [
    "ExchangeFactory",
]


# =============================================================================
# Exchange Factory
# =============================================================================
class ExchangeFactory:
    """Create exchange transports and clients from an exchange type."""

    __slots__ = ()

    @staticmethod
    def create_rest_client(
        *,
        exchange_type: ExchangeType,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
    ) -> BaseRestClient:
        """Create a REST transport for an exchange.

        Args:
            exchange_type: Exchange implementation to create.
            base_url: REST API base URL.
            api_key: Exchange API key.
            api_secret: Exchange API secret.

        Returns:
            Exchange REST transport.

        Raises:
            ValueError: If the exchange type is unsupported.
        """
        match exchange_type:
            case ExchangeType.BINANCE:
                return BinanceRestClient(
                    base_url=base_url,
                    api_key=api_key,
                    api_secret=api_secret,
                )
            case ExchangeType.BYBIT:
                return BybitRestClient(
                    base_url=base_url,
                    api_key=api_key,
                    api_secret=api_secret,
                )
            case _:
                raise ExchangeFactory._unsupported_exchange(exchange_type)

    @staticmethod
    def create_exchange_client(
        *,
        exchange_type: ExchangeType,
        rest_client: BaseRestClient,
        market_type: MarketType = MarketType.SPOT,
    ) -> BaseExchangeClient:
        """Create a high-level exchange client.

        Args:
            exchange_type: Exchange implementation to create.
            rest_client: REST transport used by the client.

        Returns:
            High-level exchange client.

        Raises:
            TypeError: If the REST transport does not match the exchange.
            ValueError: If the exchange type is unsupported.
        """
        match exchange_type:
            case ExchangeType.BINANCE:
                if not isinstance(rest_client, BinanceRestClient):
                    raise TypeError(
                        "Binance exchange client requires BinanceRestClient"
                    )

                mapper = BinanceExchangeMapper()

                if market_type is MarketType.FUTURES:
                    return BinanceFuturesExchangeClient(
                        rest=rest_client,
                        mapper=mapper,
                    )

                return BinanceExchangeClient(rest=rest_client, mapper=mapper)
            case ExchangeType.BYBIT:
                if not isinstance(rest_client, BybitRestClient):
                    raise TypeError("Bybit exchange client requires BybitRestClient")

                bybit_mapper = BybitExchangeMapper()

                if market_type is MarketType.FUTURES:
                    return BybitFuturesExchangeClient(
                        rest=rest_client,
                        mapper=bybit_mapper,
                    )

                return BybitExchangeClient(rest=rest_client, mapper=bybit_mapper)
            case _:
                raise ExchangeFactory._unsupported_exchange(exchange_type)

    @staticmethod
    def create_stream_client(
        *,
        exchange_type: ExchangeType,
        base_url: str,
    ) -> BaseStreamClient:
        """Create a streaming client for an exchange.

        Args:
            exchange_type: Exchange implementation to create.
            base_url: WebSocket API base URL.

        Returns:
            Exchange streaming client.

        Raises:
            ValueError: If the exchange type is unsupported.
        """
        match exchange_type:
            case ExchangeType.BINANCE:
                return BinanceStreamClient(
                    base_url=base_url,
                    mapper=BinanceExchangeMapper(),
                )
            case ExchangeType.BYBIT:
                return BybitStreamClient(
                    websocket_url=base_url,
                    mapper=BybitExchangeMapper(),
                )
            case _:
                raise ExchangeFactory._unsupported_exchange(exchange_type)

    @staticmethod
    def create(
        *,
        exchange_type: ExchangeType,
        rest_base_url: str,
        websocket_base_url: str,
        api_key: str = "",
        api_secret: str = "",
        market_type: MarketType = MarketType.SPOT,
    ) -> tuple[BaseExchangeClient, BaseStreamClient]:
        """Create matching REST-backed and streaming exchange clients.

        Args:
            exchange_type: Exchange implementation to create.
            rest_base_url: REST API base URL.
            websocket_base_url: WebSocket API base URL.
            api_key: Exchange API key.
            api_secret: Exchange API secret.

        Returns:
            Tuple containing the exchange client and stream client.
        """
        rest_client = ExchangeFactory.create_rest_client(
            exchange_type=exchange_type,
            base_url=rest_base_url,
            api_key=api_key,
            api_secret=api_secret,
        )
        exchange_client = ExchangeFactory.create_exchange_client(
            exchange_type=exchange_type,
            rest_client=rest_client,
            market_type=market_type,
        )
        stream_client = ExchangeFactory.create_stream_client(
            exchange_type=exchange_type,
            base_url=websocket_base_url,
        )

        return exchange_client, stream_client

    @staticmethod
    def _unsupported_exchange(
        exchange_type: ExchangeType,
    ) -> ValueError:
        """Build an unsupported-exchange error."""
        return ValueError(f"Unsupported exchange type: {exchange_type.value!r}")
