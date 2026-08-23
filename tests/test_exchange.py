"""
Botragram

Description:
    Exchange factory and Binance payload mapping tests.

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
import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    ExchangeType,
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exchanges.base.rest import (
    JsonResponse,
    QueryParams,
    RequestHeaders,
)
from botragram.exchanges.binance.client import BinanceExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.exchanges.binance.stream import BinanceStreamClient
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import MarketUniverseEntry


class ExchangeInfoRestClient(BinanceRestClient):
    """Return deterministic public exchange metadata."""

    __slots__ = ("requested_path",)

    def __init__(self) -> None:
        """Initialize an isolated metadata transport."""
        super().__init__(base_url="https://example.test")
        self.requested_path = ""

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Return mixed symbols so the client must filter them."""
        del params, headers
        assert not authenticated
        self.requested_path = path
        return {
            "symbols": [
                {"symbol": "ETHUSDT", "status": "TRADING", "quoteAsset": "USDT"},
                {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT"},
                {"symbol": "OLDUSDT", "status": "BREAK", "quoteAsset": "USDT"},
                {"symbol": "ETHBTC", "status": "TRADING", "quoteAsset": "BTC"},
            ]
        }


# =============================================================================
# Market Universe Model Tests
# =============================================================================
def test_market_universe_entry_normalizes_symbol_and_accepts_zero() -> None:
    """Preserve a zero-volume fact while normalizing its immutable identity."""
    entry = MarketUniverseEntry(
        symbol=" btcusdt ",
        quote_volume=Decimal("0"),
    )

    assert entry.symbol == "BTCUSDT"
    assert entry.quote_volume == Decimal("0")

    with pytest.raises(FrozenInstanceError):
        setattr(entry, "symbol", "ETHUSDT")


@pytest.mark.parametrize("symbol", ("", "   "))
def test_market_universe_entry_rejects_empty_symbol(symbol: str) -> None:
    """Require a provable symbol identity for every universe fact."""
    with pytest.raises(ValueError, match="symbol must not be empty"):
        MarketUniverseEntry(symbol=symbol, quote_volume=Decimal("1"))


@pytest.mark.parametrize(
    "quote_volume",
    (
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("-0.01"),
    ),
)
def test_market_universe_entry_rejects_invalid_quote_volume(
    quote_volume: Decimal,
) -> None:
    """Reject non-finite and negative quote-volume facts."""
    with pytest.raises(ValueError):
        MarketUniverseEntry(symbol="BTCUSDT", quote_volume=quote_volume)


# =============================================================================
# Factory Tests
# =============================================================================
def test_exchange_factory_builds_matching_binance_dependencies() -> None:
    """Verify factory creates one matching Binance client pair."""
    exchange_client, stream_client = ExchangeFactory.create(
        exchange_type=ExchangeType.BINANCE,
        rest_base_url="https://example.test",
        websocket_base_url="wss://example.test",
    )

    assert isinstance(exchange_client, BinanceExchangeClient)
    assert isinstance(stream_client, BinanceStreamClient)


@pytest.mark.parametrize(
    "exchange_type",
    (ExchangeType.BITGET, ExchangeType.BYBIT, ExchangeType.OKX),
)
def test_exchange_factory_rejects_unimplemented_exchange_types(
    exchange_type: ExchangeType,
) -> None:
    """Verify incomplete exchange integrations cannot be selected silently."""
    with pytest.raises(ValueError, match="Unsupported exchange type"):
        ExchangeFactory.create_rest_client(
            exchange_type=exchange_type,
            base_url="https://example.test",
        )


def test_exchange_factory_accepts_a_binance_transport_subclass() -> None:
    """Verify compatible Binance transport extensions preserve the contract."""

    class OtherRestClient(BinanceRestClient):
        """Test transport used to retain the required abstract contract."""

    rest_client = OtherRestClient(base_url="https://example.test")

    assert isinstance(
        ExchangeFactory.create_exchange_client(
            exchange_type=ExchangeType.BINANCE,
            rest_client=rest_client,
        ),
        BinanceExchangeClient,
    )


def test_binance_spot_reads_active_symbols_from_exchange_info() -> None:
    """Return sorted active USDT symbols instead of a local fixed list."""
    rest = ExchangeInfoRestClient()
    client = BinanceExchangeClient(rest=rest, mapper=BinanceExchangeMapper())

    symbols = asyncio.run(client.get_trading_symbols(quote_asset="usdt"))

    assert symbols == ("BTCUSDT", "ETHUSDT")
    assert rest.requested_path == "/api/v3/exchangeInfo"


def test_binance_spot_market_universe_is_explicitly_unsupported() -> None:
    """Keep the optional universe capability unsupported outside Futures."""
    client = BinanceExchangeClient(
        rest=ExchangeInfoRestClient(),
        mapper=BinanceExchangeMapper(),
    )

    with pytest.raises(NotImplementedError, match="Market-universe discovery"):
        asyncio.run(client.get_market_universe(quote_asset="USDT"))


# =============================================================================
# Mapper Tests
# =============================================================================
def test_binance_mapper_maps_account_and_balances() -> None:
    """Verify account capabilities and Decimal balances are normalized."""
    account = BinanceExchangeMapper().map_account(
        {
            "canTrade": True,
            "canDeposit": "true",
            "canWithdraw": 1,
            "balances": [
                {
                    "asset": "USDT",
                    "free": "100.25",
                    "locked": "2.5",
                }
            ],
        }
    )

    assert account.can_trade
    assert account.can_deposit
    assert account.can_withdraw
    assert len(account.balances) == 1
    assert account.balances[0].asset == "USDT"
    assert account.balances[0].free == Decimal("100.25")
    assert account.balances[0].locked == Decimal("2.5")


def test_binance_mapper_maps_rest_ticker_and_candle() -> None:
    """Verify REST market payloads become timezone-aware domain models."""
    mapper = BinanceExchangeMapper()
    ticker = mapper.map_ticker(
        {
            "symbol": "BTCUSDT",
            "bidPrice": "99.5",
            "askPrice": "100.5",
            "lastPrice": "100",
            "closeTime": 1_700_000_000_000,
        }
    )
    candle = mapper.map_candle(
        (
            1_700_000_000_000,
            "99",
            "102",
            "98",
            "101",
            "12.5",
            1_700_000_060_000,
        ),
        symbol="BTCUSDT",
        interval=Interval.M1,
    )

    assert ticker.symbol == "BTCUSDT"
    assert ticker.bid_price == Decimal("99.5")
    assert ticker.timestamp.tzinfo is timezone.utc
    assert ticker.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert candle.interval is Interval.M1
    assert candle.open_price == Decimal("99")
    assert candle.close_price == Decimal("101")
    assert candle.close_time.tzinfo is timezone.utc


def test_binance_mapper_maps_market_universe_entry() -> None:
    """Parse Binance quoteVolume as an exact normalized Decimal fact."""
    entry = BinanceExchangeMapper().map_market_universe_entry(
        {
            "symbol": " btcusdt ",
            "quoteVolume": "123.4500",
        }
    )

    assert entry == MarketUniverseEntry(
        symbol="BTCUSDT",
        quote_volume=Decimal("123.4500"),
    )


@pytest.mark.parametrize(
    "payload",
    (
        {
            "symbol": "BTCUSDT",
            "bidPrice": "99.5",
            "askPrice": "100.5",
            "lastPrice": "100",
        },
        {
            "symbol": "BTCUSDT",
            "bidPrice": "99.5",
            "askPrice": "100.5",
            "lastPrice": "100",
            "closeTime": "",
        },
    ),
)
def test_binance_mapper_rejects_rest_ticker_without_close_time(
    payload: dict[str, object],
) -> None:
    """Require exchange temporal provenance instead of fabricating local time."""
    mapper = BinanceExchangeMapper()

    with pytest.raises(ValueError, match="must contain a valid closeTime"):
        mapper.map_ticker(payload)


def test_binance_mapper_maps_futures_book_ticker_without_last_price() -> None:
    """Map Futures executable bid/ask data without fabricating a last price."""
    quote = BinanceExchangeMapper().map_futures_executable_quote(
        {
            "symbol": "BTCUSDT",
            "bidPrice": "99.5",
            "askPrice": "100.5",
            "time": 1_700_000_000_000,
        }
    )

    assert quote.symbol == "BTCUSDT"
    assert quote.bid_price == Decimal("99.5")
    assert quote.ask_price == Decimal("100.5")
    assert quote.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


@pytest.mark.parametrize("time", (None, ""))
def test_binance_mapper_rejects_futures_book_ticker_without_time(
    time: object,
) -> None:
    """Require timestamp provenance for a Futures executable quote."""
    with pytest.raises(ValueError, match="must contain a valid time"):
        BinanceExchangeMapper().map_futures_executable_quote(
            {
                "symbol": "BTCUSDT",
                "bidPrice": "99.5",
                "askPrice": "100.5",
                "time": time,
            }
        )


def test_binance_mapper_rejects_futures_book_ticker_with_invalid_time() -> None:
    """Reject a non-numeric executable quote timestamp."""
    with pytest.raises(ValueError):
        BinanceExchangeMapper().map_futures_executable_quote(
            {
                "symbol": "BTCUSDT",
                "bidPrice": "99.5",
                "askPrice": "100.5",
                "time": "not-a-time",
            }
        )


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("bidPrice", None),
        ("askPrice", ""),
        ("bidPrice", "not-a-decimal"),
    ),
)
def test_binance_mapper_rejects_malformed_futures_book_ticker_price(
    key: str,
    value: object,
) -> None:
    """Never coerce malformed executable bid or ask values into valid prices."""
    payload: dict[str, object] = {
        "symbol": "BTCUSDT",
        "bidPrice": "99.5",
        "askPrice": "100.5",
        "time": 1_700_000_000_000,
    }
    payload[key] = value

    with pytest.raises(ValueError, match=key):
        BinanceExchangeMapper().map_futures_executable_quote(payload)


def test_binance_mapper_maps_optional_order_prices() -> None:
    """Verify zero or absent Binance order prices remain optional."""
    order = BinanceExchangeMapper().map_order(
        {
            "orderId": 123,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "status": "FILLED",
            "origQty": "1.2",
            "executedQty": "1.2",
            "price": "0",
            "stopPrice": "",
            "transactTime": 1_700_000_000_000,
        }
    )

    assert order.order_id == "123"
    assert order.side is OrderSide.BUY
    assert order.order_type is OrderType.MARKET
    assert order.status is OrderStatus.FILLED
    assert order.price is None
    assert order.stop_price is None


def test_binance_mapper_maps_short_position_and_trade_fallbacks() -> None:
    """Verify signed positions and buyer flags map to domain enum values."""
    mapper = BinanceExchangeMapper()
    position = mapper.map_position(
        {
            "symbol": "BTCUSDT",
            "positionSide": "BOTH",
            "positionAmt": "-2",
            "entryPrice": "100",
            "markPrice": "90",
            "unRealizedProfit": "20",
            "leverage": "3",
            "updateTime": 1_700_000_000_000,
        }
    )
    trade = mapper.map_trade(
        {
            "id": 5,
            "orderId": 7,
            "symbol": "BTCUSDT",
            "isBuyer": False,
            "price": "100",
            "qty": "2",
            "commission": "0.1",
            "commissionAsset": "USDT",
            "time": 1_700_000_000_000,
        }
    )

    assert position.side is PositionSide.SHORT
    assert position.quantity == Decimal("2")
    assert trade.side is OrderSide.SELL
    assert trade.quote_quantity == Decimal("200")


def test_binance_mapper_rejects_malformed_payloads() -> None:
    """Verify malformed vendor payloads fail at the exchange boundary."""
    mapper = BinanceExchangeMapper()

    with pytest.raises(ValueError, match="at least 7 elements"):
        mapper.map_candle(
            (1, "1"),
            symbol="BTCUSDT",
            interval=Interval.M1,
        )

    with pytest.raises(ValueError, match="balances"):
        mapper.map_account({"balances": {}})
