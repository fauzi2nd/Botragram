"""
Botragram

Description:
    Bitget exchange client implementing BaseExchangeClient.

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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Final, cast

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderSide, OrderType, PositionSide
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
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
    "BITGET_INTERVAL_MAP",
    "BitgetClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")

BITGET_INTERVAL_MAP: Final[dict[Interval, str]] = {
    Interval.M1: "1m",
    Interval.M3: "3m",
    Interval.M5: "5m",
    Interval.M15: "15m",
    Interval.M30: "30m",
    Interval.H1: "1H",
    Interval.H2: "2H",
    Interval.H4: "4H",
    Interval.H6: "6H",
    Interval.H12: "12H",
    Interval.D1: "1D",
    Interval.W1: "1W",
    Interval.MN1: "1M",
}

_PRODUCT_TYPE: Final[str] = "USDT-FUTURES"

_PING_ENDPOINT: Final[str] = "/api/v2/public/time"
_ACCOUNTS_ENDPOINT: Final[str] = "/api/v3/account/assets"
_TICKER_ENDPOINT: Final[str] = "/api/v2/mix/market/ticker"
_TICKERS_ENDPOINT: Final[str] = "/api/v2/mix/market/tickers"
_CANDLES_ENDPOINT: Final[str] = "/api/v2/mix/market/candles"
_CONTRACTS_ENDPOINT: Final[str] = "/api/v2/mix/market/contracts"
_OPEN_INTEREST_ENDPOINT: Final[str] = "/api/v2/mix/market/open-interest"
_ACCOUNT_RATIO_ENDPOINT: Final[str] = "/api/v2/mix/market/account-long-short"
_FILLS_ENDPOINT: Final[str] = "/api/v3/trade/fills"

_ACCOUNT_RATIO_PERIOD_MAP: Final[dict[str, str]] = {
    "5min": "5m",
    "5m": "5m",
    "15min": "15m",
    "15m": "15m",
    "30min": "30m",
    "30m": "30m",
    "1h": "1h",
    "1hour": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "1day": "1d",
}


# =============================================================================
# Bitget Exchange Client
# =============================================================================
class BitgetClient(BaseExchangeClient):
    """Bitget base exchange client providing core market and account capabilities."""

    __slots__ = (
        "_mapper",
        "_oi_history",
        "_rest",
    )

    def __init__(
        self,
        *,
        rest: BitgetRestClient,
        mapper: BitgetExchangeMapper,
    ) -> None:
        """Initialize the Bitget exchange client."""
        self._rest = rest
        self._mapper = mapper
        self._oi_history: dict[str, list[tuple[datetime, Decimal]]] = {}

    @property
    def rest_transport(self) -> BitgetRestClient:
        """Return the vendor REST transport."""
        return self._rest

    @property
    def mapper(self) -> BitgetExchangeMapper:
        """Return the payload mapper."""
        return self._mapper

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        """Initialize exchange resources, ping server, and synchronize clock."""
        await self.ping()
        try:
            await self._rest.synchronize_time()
        except Exception as error:
            _LOGGER.warning("Bitget initial server time sync failed: %s", error)

    async def close(self) -> None:
        """Close exchange resources."""
        await self._rest.close()

    async def ping(self) -> bool:
        """Return whether Bitget is reachable."""
        try:
            payload = await self._rest.get(_PING_ENDPOINT, authenticated=False)
            if isinstance(payload, dict):
                return str(payload.get("code", "")) == "00000"
            return False
        except (
            aiohttp.ClientError,
            TimeoutError,
            RuntimeError,
            ValueError,
            BitgetRestResponseError,
        ):
            return False

    # =========================================================================
    # Account and Market Data
    # =========================================================================

    async def get_account(self) -> Account:
        """Return current exchange account wallet balances."""
        payload = await self._rest.get(
            _ACCOUNTS_ENDPOINT,
            authenticated=True,
        )
        if isinstance(payload, dict):
            return self._mapper.map_account(cast(ExchangePayload, payload))
        return self._mapper.map_account({})

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return the latest ticker for a trading symbol."""
        payload = await self._rest.get(
            _TICKER_ENDPOINT,
            params={"productType": _PRODUCT_TYPE, "symbol": symbol.strip().upper()},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list) and raw_data:
                first = cast(list[object], raw_data)[0]
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

    async def get_reference_price(self, *, symbol: str) -> Decimal:
        """Return current reference/mark price."""
        return await self.get_mark_price(symbol=symbol)

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return the current mark price for a symbol."""
        ticker = await self.get_ticker(symbol=symbol)
        return ticker.last_price

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return quantity and price rules for an instrument."""
        payload = await self._rest.get(
            _CONTRACTS_ENDPOINT,
            params={"productType": _PRODUCT_TYPE, "symbol": symbol.strip().upper()},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list) and raw_data:
                first = cast(list[object], raw_data)[0]
                if isinstance(first, dict):
                    return self._mapper.map_symbol_rules(cast(ExchangePayload, first))

        raise ValueError(f"No instrument rules found for symbol {symbol!r}")

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        """Return active trading symbols for one quote asset."""
        normalized_quote = quote_asset.strip().upper()
        payload = await self._rest.get(
            _CONTRACTS_ENDPOINT,
            params={"productType": _PRODUCT_TYPE},
            authenticated=False,
        )
        symbols: list[str] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                for item in cast(list[object], raw_data):
                    if not isinstance(item, dict):
                        continue
                    item_map = cast(ExchangePayload, item)
                    sym = str(item_map.get("symbol", "")).strip().upper()
                    quote_coin = str(item_map.get("quoteCoin", "")).strip().upper()
                    status = str(item_map.get("symbolStatus", "")).strip().lower()
                    if quote_coin == normalized_quote and status == "normal":
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
            params={"productType": _PRODUCT_TYPE},
            authenticated=False,
        )
        entries: list[MarketUniverseEntry] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                filtered: list[ExchangePayload] = []

                def _get_turnover(d: ExchangePayload) -> Decimal:
                    raw_val = d.get(
                        "quoteVolume", d.get("usdtVolume", d.get("baseVolume", "0"))
                    )
                    try:
                        return Decimal(str(raw_val))
                    except InvalidOperation, TypeError, ValueError:
                        return _DECIMAL_ZERO

                for item in cast(list[object], raw_data):
                    if not isinstance(item, dict):
                        continue
                    item_map = cast(ExchangePayload, item)
                    sym = str(item_map.get("symbol", "")).strip().upper()
                    if (
                        sym.endswith(normalized_quote)
                        and _get_turnover(item_map) > _DECIMAL_ZERO
                    ):
                        filtered.append(item_map)

                filtered.sort(key=_get_turnover, reverse=True)
                for item in filtered:
                    entries.append(self._mapper.map_market_universe_entry(item))

        return tuple(entries)

    @property
    def supported_intervals(self) -> frozenset[Interval]:
        """Return candlestick intervals natively supported by Bitget."""
        return frozenset(BITGET_INTERVAL_MAP.keys())

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

        if interval not in BITGET_INTERVAL_MAP:
            raise ValueError(
                f"Interval {interval.value} is not natively supported by Bitget"
            )

        granularity = BITGET_INTERVAL_MAP[interval]
        symbol_upper = symbol.strip().upper()

        params: dict[str, str | int] = {
            "productType": _PRODUCT_TYPE,
            "symbol": symbol_upper,
            "granularity": granularity,
            "limit": min(limit, 1000),
        }
        if start_time is not None:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        payload = await self._rest.get(
            _CANDLES_ENDPOINT,
            params=params,
            authenticated=False,
        )

        candles: list[Candle] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                for raw_candle in cast(list[object], raw_data):
                    if isinstance(raw_candle, list):
                        candle_raw_list = cast(list[object], raw_candle)
                        candle_seq = tuple(candle_raw_list)
                        candles.append(
                            self._mapper.map_candle(
                                candle_seq,
                                symbol=symbol_upper,
                                interval=interval,
                            )
                        )

        # Ensure candles are sorted ascending by open_time
        candles.sort(key=lambda c: c.open_time)
        return tuple(candles[-limit:])

    async def get_open_interest(
        self,
        *,
        symbol: str,
        interval: Interval | None = None,
        limit: int = 50,
    ) -> Sequence[tuple[datetime, Decimal]]:
        """Return historical and current Open Interest points."""
        del interval
        norm_symbol = symbol.strip().upper()
        payload = await self._rest.get(
            _OPEN_INTEREST_ENDPOINT,
            params={"productType": _PRODUCT_TYPE, "symbol": norm_symbol},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                data_map = cast(ExchangePayload, raw_data)
                oi_list = data_map.get("openInterestList")
                ts_raw = data_map.get("ts")
                ts = datetime.now(timezone.utc)
                if ts_raw is not None:
                    try:
                        ts = datetime.fromtimestamp(
                            int(str(ts_raw)) / 1000, tz=timezone.utc
                        )
                    except (ValueError, TypeError) as error:
                        _LOGGER.debug(
                            "Could not parse Bitget OI timestamp %r: %s", ts_raw, error
                        )
                if isinstance(oi_list, list):
                    for item in cast(list[object], oi_list):
                        if isinstance(item, dict):
                            item_map = cast(ExchangePayload, item)
                            size_raw = item_map.get("size")
                            try:
                                oi_dec = Decimal(str(size_raw))
                                history = self._oi_history.setdefault(norm_symbol, [])
                                if not history or history[-1][0] != ts:
                                    history.append((ts, oi_dec))
                                    if len(history) > 100:
                                        del history[:-100]
                                elif history and history[-1][0] == ts:
                                    history[-1] = (ts, oi_dec)
                            except (InvalidOperation, TypeError, ValueError) as error:
                                _LOGGER.debug(
                                    "Could not parse Bitget OI size %r: %s",
                                    size_raw,
                                    error,
                                )

        stored_history = self._oi_history.get(norm_symbol)
        if stored_history:
            return tuple(stored_history[-max(1, limit) :])
        return ()

    async def get_account_ratio(
        self,
        *,
        symbol: str,
        period: str = "15min",
        limit: int = 50,
    ) -> Sequence[tuple[datetime, Decimal, Decimal]]:
        """Return historical Long-Short Account Ratio points.

        Each point is a tuple of (timestamp, buy_ratio, sell_ratio).
        """
        if limit <= 0:
            return ()

        norm_symbol = symbol.strip().upper()
        norm_period = _ACCOUNT_RATIO_PERIOD_MAP.get(period.lower(), period)
        payload = await self._rest.get(
            _ACCOUNT_RATIO_ENDPOINT,
            params={
                "symbol": norm_symbol,
                "productType": _PRODUCT_TYPE,
                "period": norm_period,
            },
            authenticated=False,
        )
        if not isinstance(payload, dict):
            return ()

        raw_data = payload.get("data")
        if not isinstance(raw_data, list):
            return ()

        points: list[tuple[datetime, Decimal, Decimal]] = []
        for item in cast(list[object], raw_data):
            if isinstance(item, dict):
                points.append(
                    self._mapper.map_account_ratio(cast(ExchangePayload, item))
                )

        points.sort(key=lambda x: x[0])
        return tuple(points[-limit:])

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return bounded account fills."""
        params: dict[str, str | int] = {
            "category": "USDT-FUTURES",
            "limit": min(limit, 100),
        }
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()

        payload = await self._rest.get(
            _FILLS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        trades: list[Trade] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object]
            if isinstance(raw_data, dict):
                data_dict = cast(dict[str, object], raw_data)
                fill_list = data_dict.get("list") or data_dict.get("fillList")
                raw_list = (
                    cast(list[object], fill_list) if isinstance(fill_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)
            else:
                raw_list = []

            for item in raw_list:
                if isinstance(item, dict):
                    trades.append(self._mapper.map_trade(cast(ExchangePayload, item)))

        return tuple(trades)

    # =========================================================================
    # Abstract Order & Position Methods (Implemented by Subclasses)
    # =========================================================================

    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        raise NotImplementedError("create_order must be implemented by subclass")

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
        raise NotImplementedError(
            "create_protection_orders must be implemented by subclass"
        )

    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        raise NotImplementedError("cancel_order must be implemented by subclass")

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        raise NotImplementedError("cancel_all_orders must be implemented by subclass")

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        raise NotImplementedError("get_order must be implemented by subclass")

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        raise NotImplementedError(
            "get_order_by_client_order_id must be implemented by subclass"
        )

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        raise NotImplementedError("get_open_orders must be implemented by subclass")

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        raise NotImplementedError(
            "get_open_protection_orders must be implemented by subclass"
        )

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        raise NotImplementedError(
            "get_protection_order_by_client_id must be implemented by subclass"
        )

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> Sequence[Order]:
        del symbol, start_time, end_time
        raise NotImplementedError(
            "get_protection_order_history must be implemented by subclass"
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
        raise NotImplementedError(
            "ensure_stop_loss_order must be implemented by subclass"
        )

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        raise NotImplementedError("get_positions must be implemented by subclass")

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
        side: PositionSide | None = None,
    ) -> Order:
        del side
        raise NotImplementedError("close_position must be implemented by subclass")

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        raise NotImplementedError(
            "close_position_exact must be implemented by subclass"
        )

    async def close_all_positions(self) -> Sequence[Order]:
        raise NotImplementedError("close_all_positions must be implemented by subclass")
