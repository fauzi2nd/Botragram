"""
Botragram

Description:
    Bybit exchange client implementing BaseExchangeClient.

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
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final, cast

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderSide, OrderType
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.exchanges.bybit.rest import BybitRestClient
from botragram.models import (
    Account,
    Candle,
    ExchangeSymbolRules,
    ExecutableQuote,
    MarketUniverseEntry,
    Order,
    Position,
    Ticker,
    Trade,
)

__all__ = [
    "BYBIT_INTERVAL_MAP",
    "BybitExchangeClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

BYBIT_INTERVAL_MAP: Final[dict[Interval, str]] = {
    Interval.M1: "1",
    Interval.M3: "3",
    Interval.M5: "5",
    Interval.M15: "15",
    Interval.M30: "30",
    Interval.H1: "60",
    Interval.H2: "120",
    Interval.H4: "240",
    Interval.H6: "360",
    Interval.H12: "720",
    Interval.D1: "D",
    Interval.W1: "W",
    Interval.MN1: "M",
}

_PING_ENDPOINT: Final[str] = "/v5/market/time"
_WALLET_BALANCE_ENDPOINT: Final[str] = "/v5/account/wallet-balance"
_TICKERS_ENDPOINT: Final[str] = "/v5/market/tickers"
_KLINE_ENDPOINT: Final[str] = "/v5/market/kline"
_TRADES_ENDPOINT: Final[str] = "/v5/market/recent-trade"
_INSTRUMENTS_INFO_ENDPOINT: Final[str] = "/v5/market/instruments-info"


# =============================================================================
# Bybit Exchange Client
# =============================================================================
class BybitExchangeClient(BaseExchangeClient):
    """Bybit base exchange client providing core market and account capabilities."""

    __slots__ = (
        "_mapper",
        "_rest",
    )

    def __init__(
        self,
        *,
        rest: BybitRestClient,
        mapper: BybitExchangeMapper,
    ) -> None:
        """Initialize the Bybit exchange client."""
        self._rest = rest
        self._mapper = mapper

    @property
    def rest_transport(self) -> BybitRestClient:
        """Return the vendor REST transport."""
        return self._rest

    @property
    def mapper(self) -> BybitExchangeMapper:
        """Return the payload mapper."""
        return self._mapper

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        """Initialize exchange resources and synchronize server time."""
        await self._rest.synchronize_time()

    async def close(self) -> None:
        """Close exchange resources."""
        await self._rest.close()

    async def ping(self) -> bool:
        """Return whether Bybit is reachable."""
        try:
            await self._rest.get(_PING_ENDPOINT, authenticated=False)
        except aiohttp.ClientError, TimeoutError, RuntimeError, ValueError:
            return False
        return True

    # =========================================================================
    # Account and Market Data
    # =========================================================================

    async def get_account(self) -> Account:
        """Return current exchange account wallet balances."""
        payload = await self._rest.get(
            _WALLET_BALANCE_ENDPOINT,
            params={"accountType": "UNIFIED"},
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                return self._mapper.map_account(cast(ExchangePayload, raw_result))
        return self._mapper.map_account({})

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return the latest ticker for a trading symbol."""
        payload = await self._rest.get(
            _TICKERS_ENDPOINT,
            params={"category": "linear", "symbol": symbol.strip().upper()},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                ticker_list = result_map.get("list")
                if isinstance(ticker_list, list) and ticker_list:
                    first = cast(list[object], ticker_list)[0]
                    if isinstance(first, dict):
                        return self._mapper.map_ticker(cast(ExchangePayload, first))

        raise ValueError(f"No ticker found for symbol {symbol!r}")

    async def get_executable_quote(self, *, symbol: str) -> ExecutableQuote:
        """Return an exchange-provided bid/ask reference."""
        ticker = await self.get_ticker(symbol=symbol)
        return ExecutableQuote(
            symbol=ticker.symbol,
            bid_price=ticker.bid_price,
            ask_price=ticker.ask_price,
            timestamp=ticker.timestamp,
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return the current mark price for a symbol."""
        ticker = await self.get_ticker(symbol=symbol)
        return ticker.last_price

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return quantity and price rules for an instrument."""
        payload = await self._rest.get(
            _INSTRUMENTS_INFO_ENDPOINT,
            params={"category": "linear", "symbol": symbol.strip().upper()},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                inst_list = result_map.get("list")
                if isinstance(inst_list, list) and inst_list:
                    first = cast(list[object], inst_list)[0]
                    if isinstance(first, dict):
                        return self._mapper.map_symbol_rules(
                            cast(ExchangePayload, first)
                        )

        raise ValueError(f"No instrument rules found for symbol {symbol!r}")

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        """Return active trading symbols for one quote asset."""
        normalized_quote = quote_asset.strip().upper()
        payload = await self._rest.get(
            _INSTRUMENTS_INFO_ENDPOINT,
            params={"category": "linear"},
            authenticated=False,
        )
        symbols: list[str] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                inst_list = result_map.get("list")
                if isinstance(inst_list, list):
                    for item in cast(list[object], inst_list):
                        if not isinstance(item, dict):
                            continue
                        item_map = cast(ExchangePayload, item)
                        sym = str(item_map.get("symbol", "")).strip().upper()
                        status = str(item_map.get("status", "")).strip().upper()
                        if sym.endswith(normalized_quote) and status in (
                            "TRADING",
                            "SETTLING",
                        ):
                            symbols.append(sym)

        return tuple(sorted(symbols))

    async def get_market_universe(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[MarketUniverseEntry]:
        """Return ranked market-universe facts by 24h turnover/volume."""
        normalized_quote = quote_asset.strip().upper()
        payload = await self._rest.get(
            _TICKERS_ENDPOINT,
            params={"category": "linear"},
            authenticated=False,
        )
        entries: list[MarketUniverseEntry] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                ticker_list = result_map.get("list")
                if isinstance(ticker_list, list):
                    filtered: list[ExchangePayload] = []

                    def _get_turnover(d: ExchangePayload) -> Decimal:
                        try:
                            turnover = Decimal(str(d.get("turnover24h", "0")))
                        except Exception:
                            turnover = Decimal("0")
                        try:
                            volume = Decimal(str(d.get("volume24h", "0")))
                        except Exception:
                            volume = Decimal("0")
                        return max(turnover, volume)

                    for item in cast(list[object], ticker_list):
                        if not isinstance(item, dict):
                            continue
                        item_map = cast(ExchangePayload, item)
                        sym = str(item_map.get("symbol", "")).strip().upper()
                        if sym.endswith(normalized_quote) and _get_turnover(
                            item_map
                        ) > Decimal("0"):
                            filtered.append(item_map)

                    filtered.sort(key=_get_turnover, reverse=True)

                    for item in filtered:
                        entries.append(self._mapper.map_market_universe_entry(item))

        return tuple(entries)

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return candlestick market data."""
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        interval_code = BYBIT_INTERVAL_MAP.get(interval, "15")
        symbol_upper = symbol.strip().upper()
        candles: list[Candle] = []
        current_end_ms: int | None = (
            int(end_time.timestamp() * 1000) if end_time is not None else None
        )
        remaining = limit

        while remaining > 0:
            batch_limit = min(remaining, 1000)
            params: dict[str, str | int] = {
                "category": "linear",
                "symbol": symbol_upper,
                "interval": interval_code,
                "limit": batch_limit,
            }
            if start_time is not None:
                params["start"] = int(start_time.timestamp() * 1000)
            if current_end_ms is not None:
                params["end"] = current_end_ms

            payload = await self._rest.get(
                _KLINE_ENDPOINT,
                params=params,
                authenticated=False,
            )
            batch_candles: list[Candle] = []
            if isinstance(payload, dict):
                raw_result = payload.get("result")
                if isinstance(raw_result, dict):
                    result_map = cast(ExchangePayload, raw_result)
                    kline_list = result_map.get("list")
                    if isinstance(kline_list, list):
                        for raw_candle in cast(list[object], kline_list):
                            if isinstance(raw_candle, (list, tuple)):
                                seq = cast(
                                    list[object] | tuple[object, ...], raw_candle
                                )
                                batch_candles.append(
                                    self._mapper.map_candle(
                                        tuple(seq),
                                        symbol=symbol_upper,
                                        interval=interval,
                                    )
                                )

            if not batch_candles:
                break

            candles.extend(batch_candles)
            remaining -= len(batch_candles)

            if len(batch_candles) < batch_limit or remaining <= 0:
                break

            # Bybit returns klines newest first; oldest candle is batch_candles[-1]
            oldest_open_ms = int(batch_candles[-1].open_time.timestamp() * 1000)
            next_end_ms = oldest_open_ms - 1
            if current_end_ms is not None and next_end_ms >= current_end_ms:
                break
            current_end_ms = next_end_ms

        candles.sort(key=lambda c: c.open_time)
        return tuple(candles[-limit:])

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int = 50,
    ) -> Sequence[Trade]:
        """Return recent public trades."""
        if symbol is None:
            raise NotImplementedError("Bybit trade history requires a symbol")
        payload = await self._rest.get(
            _TRADES_ENDPOINT,
            params={
                "category": "linear",
                "symbol": symbol.strip().upper(),
                "limit": min(limit, 1000),
            },
            authenticated=False,
        )
        trades: list[Trade] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                trade_list = result_map.get("list")
                if isinstance(trade_list, list):
                    for item in cast(list[object], trade_list):
                        if isinstance(item, dict):
                            trades.append(
                                self._mapper.map_trade(cast(ExchangePayload, item))
                            )

        return tuple(trades)

    # Base stubs for non-futures client; overridden in BybitFuturesExchangeClient
    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> Order:
        _ = (
            symbol,
            side,
            order_type,
            quantity,
            price,
            client_order_id,
            time_in_force,
            reduce_only,
        )
        raise NotImplementedError("Use BybitFuturesExchangeClient for order execution")

    async def create_protection_orders(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        stop_loss_client_algo_id: str | None = None,
        take_profit_client_algo_id: str | None = None,
    ) -> Sequence[Order]:
        _ = (
            symbol,
            side,
            quantity,
            stop_loss,
            take_profit,
            stop_loss_client_algo_id,
            take_profit_client_algo_id,
        )
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for protection orders"
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> Order:
        _ = (symbol, order_id)
        raise NotImplementedError("Use BybitFuturesExchangeClient for cancel_order")

    async def cancel_all_orders(self, *, symbol: str | None = None) -> Sequence[Order]:
        _ = symbol
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for cancel_all_orders"
        )

    async def get_order(self, *, symbol: str, order_id: str) -> Order:
        _ = (symbol, order_id)
        raise NotImplementedError("Use BybitFuturesExchangeClient for get_order")

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        _ = (symbol, client_order_id)
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for get_order_by_client_order_id"
        )

    async def get_open_orders(self, *, symbol: str | None = None) -> Sequence[Order]:
        _ = symbol
        raise NotImplementedError("Use BybitFuturesExchangeClient for get_open_orders")

    async def get_open_protection_orders(
        self, *, symbol: str | None = None
    ) -> Sequence[Order]:
        _ = symbol
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for get_open_protection_orders"
        )

    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
        previous_client_algo_id: str | None = None,
    ) -> Order:
        _ = (
            symbol,
            side,
            quantity,
            stop_loss,
            client_algo_id,
            previous_client_algo_id,
        )
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for ensure_stop_loss_order"
        )

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        _ = (symbol, client_id)
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for get_protection_order_by_client_id"
        )

    async def get_positions(self, *, symbol: str | None = None) -> Sequence[Position]:
        _ = symbol
        raise NotImplementedError("Use BybitFuturesExchangeClient for get_positions")

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
    ) -> Order:
        _ = (symbol, client_order_id)
        raise NotImplementedError("Use BybitFuturesExchangeClient for close_position")

    async def close_all_positions(self) -> Sequence[Order]:
        raise NotImplementedError(
            "Use BybitFuturesExchangeClient for close_all_positions"
        )
