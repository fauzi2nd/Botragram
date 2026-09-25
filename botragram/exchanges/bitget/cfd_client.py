"""
Botragram

Description:
    Bitget CFD exchange client implementing BaseExchangeClient.

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
import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final, cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.cfd_financing_engine import CfdFinancingEngine
from botragram.engine.cfd_sizing_engine import CfdSizingEngine
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exceptions.exchange import (
    ExchangeError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bitget.cfd_mapper import BitgetCfdMapper
from botragram.exchanges.bitget.rest import (
    BitgetRestClient,
    BitgetRestResponseError,
)
from botragram.models import (
    Account,
    Candle,
    CfdContractSpec,
    CfdFinancingSchedule,
    CfdMarginRequirement,
    CfdOvernightSwapEstimate,
    ExchangeSymbolRules,
    MarketSession,
    Order,
    PipCalculationResult,
    Position,
    Ticker,
    Trade,
)
from botragram.utils.candle_resampler import resample_candles

__all__ = [
    "BITGET_CFD_INTERVAL_MAP",
    "BitgetCfdExchangeClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_PING_ENDPOINT: Final[str] = "/api/v2/public/time"
_CFD_ACCOUNT_ENDPOINT: Final[str] = "/api/v3/cfd/account/fund-detail"
_CFD_INSTRUMENTS_ENDPOINT: Final[str] = "/api/v3/cfd/account/instruments"
_CFD_TICKERS_ENDPOINT: Final[str] = "/api/v3/cfd/market/tickers"
_CFD_CANDLES_ENDPOINT: Final[str] = "/api/v3/cfd/market/history-candlestick"
_CFD_SYMBOLS_ENDPOINT: Final[str] = "/api/v3/cfd/market/tickers"
_CFD_PLACE_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/place-order"
_CFD_CANCEL_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/cancel-order"
_CFD_HISTORY_ORDERS_ENDPOINT: Final[str] = "/api/v3/cfd/trade/history-order"
_CFD_OPEN_ORDERS_ENDPOINT: Final[str] = "/api/v3/cfd/trade/unfilled-order"
_CFD_TRADES_ENDPOINT: Final[str] = _CFD_HISTORY_ORDERS_ENDPOINT
_CFD_POSITIONS_ENDPOINT: Final[str] = "/api/v3/cfd/trade/current-positions"
_CFD_CLOSE_POSITION_ENDPOINT: Final[str] = "/api/v3/cfd/trade/close-positions"

_CFD_PLACE_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/place-strategy-order"
_CFD_CANCEL_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/cancel-strategy-order"
_CFD_PLAN_OPEN_ENDPOINT: Final[str] = "/api/v3/cfd/trade/unfilled-strategy-orders"
_CFD_PLAN_HISTORY_ENDPOINT: Final[str] = "/api/v3/cfd/trade/history-strategy-orders"

_INSTRUMENTS_CACHE_TTL_SECONDS: Final[int] = 300
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_CFD_CLOSE_RECONCILIATION_ATTEMPTS: Final[int] = 3
_CFD_CLOSE_RECONCILIATION_DELAY_SECONDS: Final[float] = 0.05

BITGET_CFD_INTERVAL_MAP: Final[dict[Interval, str]] = {
    Interval.M1: "1m",
    Interval.M15: "15m",
    Interval.H1: "1h",
    Interval.H4: "4h",
    Interval.D1: "1d",
}
_CFD_NATIVE_INTERVALS: Final[frozenset[Interval]] = frozenset(
    BITGET_CFD_INTERVAL_MAP.keys()
)


# =============================================================================
# Bitget CFD Exchange Client Class
# =============================================================================
class BitgetCfdExchangeClient(BaseExchangeClient):
    """Bitget CFD exchange client providing TradFi CFD capabilities."""

    __slots__ = (
        "_calendar",
        "_close_reconciliation_attempts",
        "_close_reconciliation_delay_seconds",
        "_financing",
        "_instruments_cache",
        "_instruments_cache_time",
        "_is_live",
        "_mapper",
        "_mode",
        "_rest",
        "_sizing",
    )

    def __init__(
        self,
        *,
        rest: BitgetRestClient,
        mapper: BitgetCfdMapper,
        mode: str = "ecn",
        calendar: MarketCalendarEngine | None = None,
        sizing: CfdSizingEngine | None = None,
        financing: CfdFinancingEngine | None = None,
        is_live: bool = False,
        close_reconciliation_attempts: int = _CFD_CLOSE_RECONCILIATION_ATTEMPTS,
        close_reconciliation_delay_seconds: float = (
            _CFD_CLOSE_RECONCILIATION_DELAY_SECONDS
        ),
    ) -> None:
        """Initialize the Bitget CFD client.

        Args:
            rest: Bitget REST transport client.
            mapper: Bitget CFD payload mapper.
            mode: CFD instrument mode ('ecn', 'zero_fee', or 'pro').
            calendar: Optional market calendar engine for session evaluation.
            sizing: Optional CFD sizing engine for pip/lot calculations.
            financing: Optional CFD financing engine for rollover swap calculations.
            is_live: Whether trading in live mode requiring authoritative metadata.
            close_reconciliation_attempts: Bounded retry attempts for position close.
            close_reconciliation_delay_seconds: Delay between reconciliation checks.
        """
        normalized_mode = mode.strip().lower()
        if normalized_mode in ("zero_fee", "zerofee", "zero"):
            normalized_mode = "zero_fee"
        elif normalized_mode == "pro":
            normalized_mode = "pro"
        elif normalized_mode == "ecn":
            normalized_mode = "ecn"
        else:
            raise ValueError(
                f"Invalid CFD mode: {mode!r}. Accepted values are: "
                "'ecn', 'zero_fee', 'pro'."
            )
        self._rest = rest
        self._mapper = mapper
        self._mode = normalized_mode
        self._is_live = is_live
        self._close_reconciliation_attempts = max(1, close_reconciliation_attempts)
        self._close_reconciliation_delay_seconds = max(
            0.0, close_reconciliation_delay_seconds
        )
        self._calendar = calendar if calendar is not None else MarketCalendarEngine()
        self._instruments_cache: dict[str, CfdContractSpec] = {}
        self._instruments_cache_time: datetime | None = None
        self._sizing = (
            sizing
            if sizing is not None
            else CfdSizingEngine(
                calendar=self._calendar,
                is_live=self._is_live,
                spec_provider=self.get_cached_contract_spec,
            )
        )
        self._financing = (
            financing
            if financing is not None
            else CfdFinancingEngine(calendar=self._calendar, sizing=self._sizing)
        )

    @property
    def mode(self) -> str:
        """Return the active CFD mode."""
        return self._mode

    @property
    def calendar(self) -> MarketCalendarEngine:
        """Return the market calendar engine."""
        return self._calendar

    @property
    def sizing(self) -> CfdSizingEngine:
        """Return the CFD sizing engine."""
        return self._sizing

    @property
    def financing(self) -> CfdFinancingEngine:
        """Return the CFD financing and rollover engine."""
        return self._financing

    @property
    def supported_intervals(self) -> frozenset[Interval]:
        """Return candlestick intervals natively supported by Bitget CFD."""
        return _CFD_NATIVE_INTERVALS

    def get_cached_contract_spec(self, symbol: str) -> CfdContractSpec | None:
        """Return cached authoritative contract spec if available and unexpired."""
        if not self._is_cache_valid():
            return None
        clean = self._mapper.normalize_symbol(symbol)
        upper = symbol.strip().upper()
        return self._instruments_cache.get(clean) or self._instruments_cache.get(upper)

    def _is_cache_valid(self) -> bool:
        """Return True if instruments cache is populated and unexpired."""
        if not self._instruments_cache or self._instruments_cache_time is None:
            return False
        age = (
            datetime.now(timezone.utc) - self._instruments_cache_time
        ).total_seconds()
        return age < _INSTRUMENTS_CACHE_TTL_SECONDS

    async def _fetch_and_cache_instruments(self) -> Mapping[str, CfdContractSpec]:
        """Fetch authoritative CFD instruments from exchange and refresh cache."""
        payload = await self._rest.get(_CFD_INSTRUMENTS_ENDPOINT, authenticated=True)
        if not isinstance(payload, dict):
            raise ExchangeError(f"Invalid instruments response payload: {payload}")
        raw_data = payload.get("data")
        raw_list: list[object] = []
        if isinstance(raw_data, list):
            raw_list = cast(list[object], raw_data)
        elif isinstance(raw_data, dict):
            ent_list = cast(dict[str, object], raw_data).get("list")
            if isinstance(ent_list, list):
                raw_list = cast(list[object], ent_list)
            else:
                raw_list = [raw_data]

        specs: dict[str, CfdContractSpec] = {}
        for item in raw_list:
            if isinstance(item, dict):
                try:
                    spec = self._mapper.map_instrument_spec(cast(ExchangePayload, item))
                    specs[spec.symbol] = spec
                    specs[self._mapper.normalize_symbol(spec.symbol)] = spec
                    self._sizing.register_contract_spec(spec)
                except Exception as error:
                    _LOGGER.warning("Failed to map CFD instrument spec item: %s", error)

        if specs:
            self._instruments_cache.update(specs)
            self._instruments_cache_time = datetime.now(timezone.utc)
        elif self._is_live:
            raise ExchangeError(
                "Authoritative CFD instrument metadata list returned empty in LIVE mode"
            )
        return specs

    async def refresh_instrument_metadata(
        self,
        *,
        symbol: str,
        force_refresh: bool = False,
    ) -> None:
        """Refresh authoritative CFD instrument metadata if cache is expired."""
        await self.get_instrument_spec(symbol, force_refresh=force_refresh)

    async def get_instrument_spec(
        self,
        symbol: str,
        *,
        force_refresh: bool = False,
    ) -> CfdContractSpec:
        """Return authoritative contract specification for a symbol."""
        clean = self._mapper.normalize_symbol(symbol)
        upper = symbol.strip().upper()

        if not force_refresh and self._is_cache_valid():
            if clean in self._instruments_cache:
                spec = self._instruments_cache[clean]
                if self._is_live and not spec.enable:
                    raise ExchangeError(f"Bitget CFD instrument {symbol} is disabled")
                return spec
            if upper in self._instruments_cache:
                spec = self._instruments_cache[upper]
                if self._is_live and not spec.enable:
                    raise ExchangeError(f"Bitget CFD instrument {symbol} is disabled")
                return spec

        try:
            await self._fetch_and_cache_instruments()
        except Exception as error:
            if self._is_live:
                raise ExchangeError(
                    f"Failed to fetch authoritative CFD instruments"
                    f" for {symbol}: {error}"
                ) from error
            _LOGGER.debug(
                "Unable to query Bitget CFD instruments for %s: %s",
                symbol,
                error,
            )

        if self._is_cache_valid():
            if clean in self._instruments_cache:
                spec = self._instruments_cache[clean]
                if self._is_live and not spec.enable:
                    raise ExchangeError(f"Bitget CFD instrument {symbol} is disabled")
                return spec
            if upper in self._instruments_cache:
                spec = self._instruments_cache[upper]
                if self._is_live and not spec.enable:
                    raise ExchangeError(f"Bitget CFD instrument {symbol} is disabled")
                return spec

        if self._is_live:
            raise ExchangeError(
                f"Authoritative CFD instrument metadata unavailable"
                f" for {symbol} in LIVE mode"
            )

        return self._sizing.get_fallback_contract_spec(symbol)

    def get_contract_spec(self, symbol: str) -> CfdContractSpec:
        """Return the contract and pip specifications for a symbol."""
        cached = self.get_cached_contract_spec(symbol)
        if cached is not None:
            if self._is_live and not cached.enable:
                raise ExchangeError(f"Bitget CFD instrument {symbol} is disabled")
            return cached
        if self._is_live:
            raise ExchangeError(
                f"Authoritative CFD instrument metadata unavailable or expired"
                f" for {symbol} in LIVE mode"
            )
        return self._sizing.get_contract_spec(symbol)

    def get_financing_schedule(self, symbol: str) -> CfdFinancingSchedule:
        """Return the financing interest and rollover schedule for a symbol."""
        return self._financing.get_financing_schedule(symbol)

    def estimate_overnight_swap(
        self,
        *,
        symbol: str,
        side: PositionSide,
        lots: Decimal,
        price: Decimal,
        at: datetime | None = None,
    ) -> CfdOvernightSwapEstimate:
        """Estimate overnight rollover swap interest for holding a CFD position."""
        return self._financing.estimate_overnight_swap(
            symbol=symbol,
            side=side,
            lots=lots,
            price=price,
            at=at,
        )

    def calculate_margin_requirement(
        self,
        *,
        symbol: str,
        lots: Decimal,
        price: Decimal,
        leverage: int,
        free_margin: Decimal,
    ) -> CfdMarginRequirement:
        """Calculate margin requirements and capital sufficiency for a CFD trade."""
        return self._financing.calculate_margin_requirement(
            symbol=symbol,
            lots=lots,
            price=price,
            leverage=leverage,
            free_margin=free_margin,
        )

    def calculate_lot_size(
        self,
        *,
        symbol: str,
        entry_price: Decimal,
        stop_loss: Decimal,
        risk_amount: Decimal,
        quote_to_account_rate: Decimal = Decimal("1.0"),
    ) -> PipCalculationResult:
        """Calculate dynamic lot sizing based on stop-loss distance and risk capital."""
        return self._sizing.calculate_lot_size(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
            quote_to_account_rate=quote_to_account_rate,
        )

    async def is_market_open(
        self,
        *,
        symbol: str,
        at: datetime | None = None,
    ) -> bool:
        """Return whether the TradFi CFD market is open for the given symbol."""
        return self._calendar.is_market_open(symbol=symbol, at=at)

    async def get_market_session(
        self,
        *,
        symbol: str,
        at: datetime | None = None,
    ) -> MarketSession:
        """Return the market trading session details for the symbol."""
        return self._calendar.get_session(symbol=symbol, at=at)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        """Initialize connections and verify connectivity."""
        await self.ping()
        try:
            await self._fetch_and_cache_instruments()
        except Exception as error:
            if self._is_live:
                raise ExchangeError(
                    "Bitget CFD connection failed: unable to fetch"
                    f" authoritative instruments in LIVE mode: {error}"
                ) from error
            _LOGGER.debug(
                "Non-live Bitget CFD client could not prefetch instruments: %s",
                error,
            )

    async def close(self) -> None:
        """Release underlying REST sessions."""
        await self._rest.close()

    async def ping(self) -> bool:
        """Return whether Bitget API is reachable."""
        try:
            payload = await self._rest.get(_PING_ENDPOINT, authenticated=False)
            return isinstance(payload, dict) and payload.get("code") == "00000"
        except Exception as error:
            _LOGGER.debug("Bitget CFD ping failed: %s", error)
            return False

    # =========================================================================
    # Account & Market Data
    # =========================================================================

    async def get_account(self) -> Account:
        """Return current CFD account fund details."""
        payload = await self._rest.get(_CFD_ACCOUNT_ENDPOINT, authenticated=True)
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_account(cast(ExchangePayload, raw_data))
        return self._mapper.map_account({})

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return latest ticker for a CFD symbol."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        payload = await self._rest.get(
            _CFD_TICKERS_ENDPOINT,
            params={"symbol": vendor_symbol},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)
                if raw_list and isinstance(raw_list[0], dict):
                    return self._mapper.map_ticker(cast(ExchangePayload, raw_list[0]))
            elif isinstance(raw_data, dict):
                return self._mapper.map_ticker(cast(ExchangePayload, raw_data))

        raise ExchangeError(f"No ticker returned for CFD symbol {symbol}")

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return quantity and pricing rules for a CFD symbol."""
        spec = await self.get_instrument_spec(symbol)
        return ExchangeSymbolRules(
            symbol=self._mapper.normalize_symbol(symbol),
            market_min_quantity=spec.min_lot,
            market_max_quantity=spec.max_lot,
            market_quantity_step=spec.lot_step,
            price_tick_size=spec.tick_size,
        )

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        """Return list of active CFD trading symbols."""
        try:
            payload = await self._rest.get(_CFD_TICKERS_ENDPOINT, authenticated=False)
            if isinstance(payload, dict):
                raw_data = payload.get("data")
                if isinstance(raw_data, list):
                    result: list[str] = []
                    seen: set[str] = set()
                    quote_upper = quote_asset.strip().upper()
                    for item in cast(list[object], raw_data):
                        if isinstance(item, dict):
                            item_payload = cast(ExchangePayload, item)
                            sym = str(item_payload.get("symbol", ""))
                            clean_sym = self._mapper.normalize_symbol(sym)
                            if not clean_sym:
                                continue
                            if clean_sym in seen:
                                continue
                            if quote_upper in ("USD", "USDT") or clean_sym.endswith(
                                quote_upper
                            ):
                                seen.add(clean_sym)
                                result.append(clean_sym)
                    return tuple(result)
        except Exception as error:
            _LOGGER.warning("Failed to fetch CFD trading symbols: %s", error)
        return ()

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return historical CFD candlestick data with pagination support.

        For intervals not natively supported by Bitget CFD (e.g. 5m), lower
        timeframe native candles (1m) are fetched and resampled into the target
        interval.
        """
        target_limit = max(1, limit)

        # Handle non-native intervals by fetching 1m base candles and resampling
        if interval not in self.supported_intervals:
            base_interval = Interval.M1
            multiplier = max(1, interval.seconds // base_interval.seconds)
            base_limit = (target_limit + 2) * multiplier
            base_candles = await self.get_candles(
                symbol=symbol,
                interval=base_interval,
                limit=base_limit,
                start_time=start_time,
                end_time=end_time,
            )
            if not base_candles:
                return ()
            resampled = resample_candles(
                candles=base_candles,
                target_interval=interval,
                closed_only=False,
            )
            return resampled[-target_limit:]

        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        interval_str = BITGET_CFD_INTERVAL_MAP.get(interval, "15m")
        all_candles: list[Candle] = []
        current_end_time_ms: int | None = (
            int(end_time.timestamp() * 1000) if end_time is not None else None
        )
        min_start_time_ms: int | None = (
            int(start_time.timestamp() * 1000) if start_time is not None else None
        )

        while len(all_candles) < target_limit:
            batch_limit = min(target_limit - len(all_candles), 100)
            params: dict[str, str | int] = {
                "symbol": vendor_symbol,
                "interval": interval_str,
                "side": "buy",
                "limit": batch_limit,
            }
            if min_start_time_ms is not None:
                params["startTime"] = min_start_time_ms
            if current_end_time_ms is not None:
                params["endTime"] = current_end_time_ms

            payload = await self._rest.get(
                _CFD_CANDLES_ENDPOINT,
                params=params,
                authenticated=False,
            )
            batch_candles: list[Candle] = []
            if isinstance(payload, dict):
                raw_data = payload.get("data")
                if isinstance(raw_data, list):
                    for row in cast(list[object], raw_data):
                        if isinstance(row, (list, tuple)):
                            row_items = cast(Sequence[object], row)
                            batch_candles.append(
                                self._mapper.map_candle(
                                    tuple(row_items),
                                    symbol=symbol,
                                    interval=interval,
                                )
                            )
            if not batch_candles:
                break

            all_candles = batch_candles + all_candles

            oldest_open_time_ms = int(batch_candles[0].open_time.timestamp() * 1000)
            new_end_time_ms = oldest_open_time_ms - 1
            if (
                current_end_time_ms is not None
                and new_end_time_ms >= current_end_time_ms
            ):
                break
            current_end_time_ms = new_end_time_ms
            if (
                min_start_time_ms is not None
                and current_end_time_ms <= min_start_time_ms
            ):
                break
            if len(batch_candles) < batch_limit:
                break

        if len(all_candles) > target_limit:
            all_candles = all_candles[-target_limit:]

        return tuple(all_candles)

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return recent CFD executions/fills."""
        params: dict[str, str | int] = {"limit": min(max(1, limit), 50)}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_TRADES_ENDPOINT,
            params=params,
            authenticated=True,
        )
        trades: list[Trade] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    trades.append(self._mapper.map_trade(cast(ExchangePayload, item)))
        return tuple(trades)

    # =========================================================================
    # Orders
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
        bypass_calendar_guard: bool = False,
    ) -> Order:
        """Create a new CFD order."""
        if not bypass_calendar_guard:
            session = self._calendar.get_session(symbol)
            if not session.is_open:
                raise ExchangeOrderRejectedError(
                    f"TradFi CFD market is closed for {symbol} "
                    f"(status: {session.status.value}, reason: {session.reason})"
                )

        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        side_str = "buy" if side is OrderSide.BUY else "sell"
        type_str = "market" if order_type is OrderType.MARKET else "limit"
        body: dict[str, object] = {
            "symbol": vendor_symbol,
            "side": side_str,
            "orderType": type_str,
            "qty": str(quantity),
        }
        if price is not None:
            body["price"] = str(price)

        try:
            payload = await self._rest.post(
                _CFD_PLACE_ORDER_ENDPOINT,
                data=body,
                authenticated=True,
            )
        except BitgetRestResponseError as error:
            raise ExchangeOrderRejectedError(
                f"Bitget CFD order was rejected: {error}"
            ) from error
        except (TimeoutError, ConnectionError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                f"Bitget CFD order outcome is unknown: {error}"
            ) from error

        if not isinstance(payload, dict):
            raise ExchangeOrderRejectedError(
                f"Bitget CFD order submission failed for {symbol}: {payload}"
            )

        raw_data = payload.get("data")
        if not isinstance(raw_data, dict):
            raise ExchangeOrderRejectedError(
                f"Bitget CFD order submission returned invalid data"
                f" for {symbol}: {payload}"
            )

        raw_payload = cast(ExchangePayload, raw_data)
        raw_order_id = self._to_string(
            raw_payload.get("orderId", raw_payload.get("order_id", ""))
        ).strip()
        trx_id = (
            self._to_string(
                raw_payload.get("trxId", raw_payload.get("trx_id", ""))
            ).strip()
            or None
        )

        matched_order: Order | None = None

        # Case 1: Order ID returned directly in response
        if raw_order_id:
            try:
                matched_order = await self.get_order(
                    symbol=symbol, order_id=raw_order_id
                )
            except ExchangeError, ExchangeOrderNotFoundError, BitgetRestResponseError:
                now = datetime.now(timezone.utc)
                matched_order = Order(
                    order_id=raw_order_id,
                    client_order_id=client_order_id,
                    execution_order_id=trx_id,
                    symbol=self._mapper.normalize_symbol(symbol),
                    side=side,
                    order_type=order_type,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=_DECIMAL_ZERO,
                    price=price,
                    created_at=now,
                    updated_at=now,
                )

        # Case 2: Trace flow through unfilled-order, then history-order
        if matched_order is None and trx_id:
            try:
                open_orders = await self.get_open_orders(symbol=symbol)
                for o in open_orders:
                    if o.execution_order_id == trx_id and o.order_id:
                        matched_order = o
                        break
                    if (
                        client_order_id
                        and o.client_order_id == client_order_id
                        and o.order_id
                    ):
                        matched_order = o
                        break
            except ExchangeError, BitgetRestResponseError:
                pass

        if matched_order is None and trx_id:
            try:
                history_orders = await self.get_history_orders(symbol=symbol, limit=50)
                for o in history_orders:
                    if o.execution_order_id == trx_id and o.order_id:
                        matched_order = o
                        break
                    if (
                        client_order_id
                        and o.client_order_id == client_order_id
                        and o.order_id
                    ):
                        matched_order = o
                        break
            except ExchangeError, BitgetRestResponseError:
                pass

        if matched_order is not None and matched_order.order_id:
            if trx_id and not matched_order.execution_order_id:
                matched_order = replace(matched_order, execution_order_id=trx_id)
            if client_order_id and not matched_order.client_order_id:
                matched_order = replace(matched_order, client_order_id=client_order_id)
            return matched_order

        # Fail closed: never fabricate order_id from trx_id
        raise ExchangeOrderOutcomeUnknownError(
            f"Bitget CFD order placed with trxId={trx_id}, but order identity could not"
            " be resolved from venue (unfilled-order or history-order). "
            "Fail closed for reconciliation."
        )

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
        bypass_calendar_guard: bool = False,
    ) -> Sequence[Order]:
        """Create conditional stop-loss and take-profit plan orders for CFD."""
        if not bypass_calendar_guard:
            session = self._calendar.get_session(symbol)
            if not session.is_open:
                raise ExchangeOrderRejectedError(
                    f"Cannot place protection orders: TradFi CFD market is closed "
                    f"for {symbol} (status: {session.status.value}, "
                    f"reason: {session.reason})"
                )

        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        pos_side = "long" if side is OrderSide.SELL else "short"

        # Case 1: Both legs requested - combined TPSL submission
        if stop_loss is not None and take_profit is not None:
            data: dict[str, object] = {
                "symbol": vendor_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "qty": str(quantity),
                "size": str(quantity),
                "stopLoss": str(stop_loss),
                "takeProfit": str(take_profit),
            }
            if stop_loss_client_algo_id:
                data["clientOid"] = stop_loss_client_algo_id
            elif take_profit_client_algo_id:
                data["clientOid"] = take_profit_client_algo_id

            try:
                resp = await self._rest.post(
                    _CFD_PLACE_PLAN_ORDER_ENDPOINT,
                    data=data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD protection orders rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget CFD protection orders outcome unknown: {error}"
                ) from error

            order_id = ""
            if isinstance(resp, dict):
                raw_data = resp.get("data")
                if isinstance(raw_data, dict):
                    data_dict = cast(ExchangePayload, raw_data)
                    order_id = str(data_dict.get("orderId", ""))

            now = datetime.now(timezone.utc)
            return (
                Order(
                    order_id=f"{order_id}-sl" if order_id else "bitget-cfd-sl",
                    symbol=self._mapper.normalize_symbol(symbol),
                    side=side,
                    order_type=OrderType.STOP_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=stop_loss,
                    client_order_id=stop_loss_client_algo_id,
                    created_at=now,
                    updated_at=now,
                ),
                Order(
                    order_id=f"{order_id}-tp" if order_id else "bitget-cfd-tp",
                    symbol=self._mapper.normalize_symbol(symbol),
                    side=side,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=take_profit,
                    client_order_id=take_profit_client_algo_id,
                    created_at=now,
                    updated_at=now,
                ),
            )

        orders: list[Order] = []

        # Case 2: Only stop-loss requested
        if stop_loss is not None:
            sl_data: dict[str, object] = {
                "symbol": vendor_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "qty": str(quantity),
                "size": str(quantity),
                "stopLoss": str(stop_loss),
            }
            if stop_loss_client_algo_id:
                sl_data["clientOid"] = stop_loss_client_algo_id

            try:
                open_orders = await self.get_open_protection_orders(symbol=symbol)
            except (TimeoutError, ConnectionError, RuntimeError) as error:
                raise ExchangeError(
                    "Bitget CFD network failure while querying "
                    f"existing protection orders: {error}"
                ) from error

            existing_tp = next(
                (
                    o
                    for o in open_orders
                    if o.order_type
                    in (OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT)
                    and o.status is OrderStatus.NEW
                    and o.side is side
                    and o.stop_price is not None
                ),
                None,
            )
            if existing_tp is not None and existing_tp.stop_price is not None:
                sl_data["takeProfit"] = str(existing_tp.stop_price)

            try:
                resp = await self._rest.post(
                    _CFD_PLACE_PLAN_ORDER_ENDPOINT,
                    data=sl_data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD stop-loss was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget CFD stop-loss outcome is unknown: {error}"
                ) from error

            order_id = ""
            if isinstance(resp, dict):
                raw_data = resp.get("data")
                if isinstance(raw_data, dict):
                    data_dict = cast(ExchangePayload, raw_data)
                    order_id = str(data_dict.get("orderId", ""))

            now = datetime.now(timezone.utc)
            orders.append(
                Order(
                    order_id=order_id or "bitget-cfd-sl",
                    symbol=self._mapper.normalize_symbol(symbol),
                    side=side,
                    order_type=OrderType.STOP_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=stop_loss,
                    client_order_id=stop_loss_client_algo_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        # Case 3: Only take-profit requested
        if take_profit is not None:
            tp_data: dict[str, object] = {
                "symbol": vendor_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "qty": str(quantity),
                "size": str(quantity),
                "takeProfit": str(take_profit),
            }
            if take_profit_client_algo_id:
                tp_data["clientOid"] = take_profit_client_algo_id

            try:
                open_orders = await self.get_open_protection_orders(symbol=symbol)
            except (TimeoutError, ConnectionError, RuntimeError) as error:
                raise ExchangeError(
                    "Bitget CFD network failure while querying "
                    f"existing protection orders: {error}"
                ) from error

            existing_sl = next(
                (
                    o
                    for o in open_orders
                    if o.order_type in (OrderType.STOP_MARKET, OrderType.STOP)
                    and o.status is OrderStatus.NEW
                    and o.side is side
                    and o.stop_price is not None
                ),
                None,
            )
            if existing_sl is not None and existing_sl.stop_price is not None:
                tp_data["stopLoss"] = str(existing_sl.stop_price)

            try:
                resp = await self._rest.post(
                    _CFD_PLACE_PLAN_ORDER_ENDPOINT,
                    data=tp_data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD take-profit was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget CFD take-profit outcome is unknown: {error}"
                ) from error

            order_id = ""
            if isinstance(resp, dict):
                raw_data = resp.get("data")
                if isinstance(raw_data, dict):
                    tp_dict = cast(ExchangePayload, raw_data)
                    order_id = str(tp_dict.get("orderId", ""))

            now = datetime.now(timezone.utc)
            orders.append(
                Order(
                    order_id=order_id or "bitget-cfd-tp",
                    symbol=self._mapper.normalize_symbol(symbol),
                    side=side,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=take_profit,
                    client_order_id=take_profit_client_algo_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        return tuple(orders)

    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel an open CFD order."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        body: dict[str, object] = {
            "symbol": vendor_symbol,
            "orderId": order_id,
        }
        payload = await self._rest.post(
            _CFD_CANCEL_ORDER_ENDPOINT,
            data=body,
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

        return await self.get_order(symbol=symbol, order_id=order_id)

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel all open CFD orders."""
        open_orders = await self.get_open_orders(symbol=symbol)
        canceled: list[Order] = []
        for order in open_orders:
            try:
                canceled.append(
                    await self.cancel_order(
                        symbol=order.symbol,
                        order_id=order.order_id,
                    )
                )
            except Exception as error:
                _LOGGER.warning(
                    "Failed to cancel CFD order %s: %s",
                    order.order_id,
                    error,
                )
        return tuple(canceled)

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return CFD order detail by searching unfilled and history orders."""
        open_orders = await self.get_open_orders(symbol=symbol)
        for order in open_orders:
            if order.order_id == order_id:
                return order

        history_orders = await self.get_history_orders(symbol=symbol, limit=50)
        for order in history_orders:
            if order.order_id == order_id:
                return order

        raise ExchangeOrderNotFoundError(
            f"CFD order {order_id} for {symbol} was not found"
        )

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return CFD order detail by client order ID."""
        open_orders = await self.get_open_orders(symbol=symbol)
        for order in open_orders:
            if order.client_order_id == client_order_id:
                return order

        history_orders = await self.get_history_orders(symbol=symbol, limit=50)
        for order in history_orders:
            if order.client_order_id == client_order_id:
                return order

        raise ExchangeOrderNotFoundError(
            f"CFD client order {client_order_id} for {symbol} not found"
        )

    async def get_history_orders(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> Sequence[Order]:
        """Return history CFD orders."""
        normalized_limit = min(max(1, limit), 50)
        params: dict[str, str | int] = {"limit": normalized_limit}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_HISTORY_ORDERS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    orders.append(self._mapper.map_order(cast(ExchangePayload, item)))
        return tuple(orders)

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return open CFD orders."""
        params: dict[str, str] = {}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_OPEN_ORDERS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)
            elif isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                if isinstance(ent_list, list):
                    raw_list = cast(list[object], ent_list)
                else:
                    raw_list = [raw_data]

            for item in raw_list:
                if isinstance(item, dict):
                    orders.append(self._mapper.map_order(cast(ExchangePayload, item)))
        return tuple(orders)

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return open CFD conditional protection orders."""
        params: dict[str, str] = {}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_PLAN_OPEN_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    orders.extend(
                        self._mapper.map_protection_orders(cast(ExchangePayload, item))
                    )
        return tuple(orders)

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Find pending CFD protection plan order by client_id."""
        orders = await self.get_open_protection_orders(symbol=symbol)
        for order in orders:
            if order.client_order_id == client_id:
                return order

        # Handle companion leg for combined TPSL
        if client_id.startswith("btp-"):
            for order in orders:
                if order.order_type in (
                    OrderType.TAKE_PROFIT_MARKET,
                    OrderType.TAKE_PROFIT,
                ) and (order.client_order_id is None or order.order_id.endswith("-tp")):
                    return replace(order, client_order_id=client_id)

        if client_id.startswith("bsl-"):
            for order in orders:
                if order.order_type in (
                    OrderType.STOP_MARKET,
                    OrderType.STOP,
                ) and (order.client_order_id is None or order.order_id.endswith("-sl")):
                    return replace(order, client_order_id=client_id)

        raise ExchangeOrderNotFoundError(
            f"CFD protection order with client_id {client_id!r} not found "
            f"for symbol {symbol!r}"
        )

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str | None = None,
        order_id: str | None = None,
    ) -> None:
        """Cancel conditional plan order by order_id or client_id."""
        if client_id is None and order_id is None:
            raise ValueError(
                "Either client_id or order_id must be provided to cancel "
                "protection order"
            )
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        data: dict[str, object] = {
            "symbol": vendor_symbol,
        }
        if order_id is not None:
            clean_id = order_id[:-3] if order_id.endswith(("-tp", "-sl")) else order_id
            data["orderId"] = clean_id
        elif client_id is not None:
            resolved_order_id: str | None = None
            try:
                matched = await self.get_protection_order_by_client_id(
                    symbol=symbol,
                    client_id=client_id,
                )
                clean_id = (
                    matched.order_id[:-3]
                    if matched.order_id.endswith(("-tp", "-sl"))
                    else matched.order_id
                )
                if clean_id and not clean_id.startswith("bitget-cfd-"):
                    resolved_order_id = clean_id
            except ExchangeOrderNotFoundError:
                resolved_order_id = None

            if resolved_order_id is not None:
                data["orderId"] = resolved_order_id
            else:
                data["clientOid"] = client_id

        try:
            await self._rest.post(
                _CFD_CANCEL_PLAN_ORDER_ENDPOINT,
                data=data,
                authenticated=True,
            )
        except BitgetRestResponseError as error:
            if (
                error.code in ("25204", "40004", "40404", "43025")
                or "not exist" in error.message.lower()
                or "canceled" in error.message.lower()
                or "cancelled" in error.message.lower()
                or "finished" in error.message.lower()
                or error.http_status == 404
            ):
                _LOGGER.info(
                    "Bitget CFD protection order %s already finished/not found: %s",
                    order_id or client_id,
                    error.message,
                )
                return
            raise ExchangeError(
                f"Failed to cancel CFD protection order {order_id or client_id}: "
                f"{error.message}"
            ) from error
        except (TimeoutError, ConnectionError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                f"Bitget CFD protection cancellation outcome is unknown: {error}"
            ) from error

    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
        previous_client_algo_id: str | None = None,
        bypass_calendar_guard: bool = False,
    ) -> Order:
        """Replace or ensure a stop-loss plan order using new-stop-first sequence."""
        if quantity <= Decimal("0"):
            raise ValueError("Stop-loss quantity must be greater than zero")
        if stop_loss <= Decimal("0"):
            raise ValueError("Stop-loss trigger price must be greater than zero")

        target: Order | None = None
        if client_algo_id is not None:
            try:
                existing = await self.get_protection_order_by_client_id(
                    symbol=symbol,
                    client_id=client_algo_id,
                )
                if (
                    existing.status is OrderStatus.NEW
                    and existing.stop_price == stop_loss
                ):
                    target = existing
            except ExchangeOrderNotFoundError:
                target = None

        if target is None:
            orders = await self.create_protection_orders(
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_loss=stop_loss,
                stop_loss_client_algo_id=client_algo_id,
                bypass_calendar_guard=bypass_calendar_guard,
            )
            if not orders:
                raise ExchangeOrderRejectedError(
                    f"Failed to place stop loss order for CFD {symbol} at {stop_loss}"
                )
            target = orders[0]

        if (
            previous_client_algo_id is not None
            and previous_client_algo_id != target.client_order_id
        ):
            await self.cancel_protection_order(
                symbol=symbol,
                client_id=previous_client_algo_id,
            )

        return target

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> Sequence[Order]:
        """Return conditional protection order history for one CFD symbol."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        start_ms = int(start_time.timestamp() * 1000)
        params: dict[str, str | int] = {
            "symbol": vendor_symbol,
            "startTime": start_ms,
            "limit": 100,
        }
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        payload = await self._rest.get(
            _CFD_PLAN_HISTORY_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    orders.extend(
                        self._mapper.map_protection_orders(cast(ExchangePayload, item))
                    )

        return tuple(orders)

    # =========================================================================
    # Positions
    # =========================================================================

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return open CFD positions."""
        params: dict[str, str] = {}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_POSITIONS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        positions: list[Position] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                for item in cast(list[object], raw_data):
                    if isinstance(item, dict):
                        positions.append(
                            self._mapper.map_position(cast(ExchangePayload, item))
                        )
        return tuple(positions)

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
        bypass_calendar_guard: bool = False,
        side: PositionSide | None = None,
        position_id: str | None = None,
        quantity: Decimal | None = None,
        initial_quantity: Decimal | None = None,
    ) -> Order:
        """Close an open CFD position."""
        if not bypass_calendar_guard:
            session = self._calendar.get_session(symbol)
            if not session.is_open:
                raise ExchangeOrderRejectedError(
                    f"Cannot close position: TradFi CFD market is closed for {symbol} "
                    f"(status: {session.status.value}, reason: {session.reason})"
                )

        target_position_id = position_id
        target_quantity = quantity
        target_side = side
        target_initial_quantity = initial_quantity

        if (
            target_position_id is None
            or target_quantity is None
            or target_initial_quantity is None
        ):
            open_positions = await self.get_positions(symbol=symbol)
            if target_position_id is not None:
                matched_positions = [
                    p for p in open_positions if p.position_id == target_position_id
                ]
            elif side is not None:
                matched_positions = [p for p in open_positions if p.side is side]
            else:
                matched_positions = list(open_positions)

            if len(matched_positions) > 1:
                raise RuntimeError(
                    f"Multiple active CFD positions found for {symbol!r}. "
                    "Explicit side/position_id parameter is required to close."
                )
            if not matched_positions:
                raise ExchangeError(
                    f"No active CFD position found for {symbol!r} to close"
                )

            matched_pos = matched_positions[0]
            if target_position_id is None:
                target_position_id = matched_pos.position_id
            if target_quantity is None:
                target_quantity = matched_pos.quantity
            if target_side is None:
                target_side = matched_pos.side
            if target_initial_quantity is None:
                target_initial_quantity = matched_pos.quantity

        if not target_position_id:
            raise ExchangeError(
                f"Missing authoritative positionId for CFD position {symbol!r}"
            )
        if target_quantity <= _DECIMAL_ZERO:
            raise ExchangeError(
                f"Invalid quantity {target_quantity} for CFD position {symbol!r}"
            )
        if target_quantity > target_initial_quantity:
            raise ExchangeError(
                f"Requested close quantity {target_quantity} exceeds position "
                f"quantity {target_initial_quantity} for CFD position {symbol!r}"
            )

        body: dict[str, object] = {
            "positionId": target_position_id,
            "qty": str(target_quantity),
        }

        try:
            payload = await self._rest.post(
                _CFD_CLOSE_POSITION_ENDPOINT,
                data=body,
                authenticated=True,
            )
        except BitgetRestResponseError as error:
            raise ExchangeOrderRejectedError(
                f"Bitget CFD close position was rejected: {error}"
            ) from error
        except (TimeoutError, ConnectionError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                f"Bitget CFD close position outcome is unknown: {error}"
            ) from error

        if isinstance(payload, dict):
            raw_code = payload.get("code")
            code = str(raw_code) if raw_code is not None else ""
            if code not in ("00000", ""):
                raw_msg = payload.get("msg")
                msg = str(raw_msg) if raw_msg is not None else ""
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD close position was rejected with code {code}: {msg}"
                )

            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                data_dict = dict(cast(ExchangePayload, raw_data))
                if not data_dict.get("symbol"):
                    data_dict["symbol"] = symbol
                mapped = self._mapper.map_order(cast(ExchangePayload, data_dict))
                if client_order_id and not mapped.client_order_id:
                    return replace(mapped, client_order_id=client_order_id)
                return mapped

            if raw_data is None:
                expected_remaining_qty = target_initial_quantity - target_quantity
                is_full_close = expected_remaining_qty <= _DECIMAL_ZERO

                confirmed = False
                for attempt in range(self._close_reconciliation_attempts):
                    try:
                        reconciled_positions = await self.get_positions(symbol=symbol)
                    except Exception as error:
                        _LOGGER.warning(
                            "Bitget CFD close position reconciliation read "
                            "failed on attempt %s: %s",
                            attempt + 1,
                            error,
                        )
                        reconciled_positions = None

                    if reconciled_positions is not None:
                        active_pos = next(
                            (
                                p
                                for p in reconciled_positions
                                if p.position_id == target_position_id
                            ),
                            None,
                        )
                        if is_full_close:
                            if (
                                active_pos is None
                                or active_pos.quantity <= _DECIMAL_ZERO
                            ):
                                confirmed = True
                                break
                        else:
                            if (
                                active_pos is not None
                                and active_pos.quantity == expected_remaining_qty
                            ):
                                confirmed = True
                                break

                    if attempt + 1 < self._close_reconciliation_attempts:
                        if self._close_reconciliation_delay_seconds > 0:
                            await asyncio.sleep(
                                self._close_reconciliation_delay_seconds
                            )

                if not confirmed:
                    rem_target = (
                        expected_remaining_qty if not is_full_close else _DECIMAL_ZERO
                    )
                    raise ExchangeOrderOutcomeUnknownError(
                        f"Bitget CFD close position outcome could not be confirmed "
                        f"for position {target_position_id!r} ({symbol}): expected "
                        f"remaining quantity {rem_target}"
                    )

                now = datetime.now(timezone.utc)
                close_side = (
                    OrderSide.BUY
                    if target_side is PositionSide.SHORT
                    else OrderSide.SELL
                )
                return Order(
                    order_id="",
                    symbol=self._mapper.normalize_symbol(symbol),
                    side=close_side,
                    order_type=OrderType.MARKET,
                    status=OrderStatus.FILLED,
                    quantity=target_quantity,
                    executed_quantity=target_quantity,
                    client_order_id=client_order_id,
                    created_at=now,
                    updated_at=now,
                )

        raise ExchangeError(f"Failed to close CFD position for {symbol}: {payload}")

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        """Submit one close from an authoritative CFD position snapshot."""
        return await self.close_position(
            symbol=position.symbol,
            client_order_id=client_order_id,
            side=position.side,
            position_id=position.position_id,
            quantity=position.quantity,
            initial_quantity=position.quantity,
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active CFD positions."""
        open_positions = await self.get_positions()
        closed_orders: list[Order] = []
        for position in open_positions:
            try:
                closed_orders.append(
                    await self.close_position(
                        symbol=position.symbol,
                        side=position.side,
                        position_id=position.position_id,
                        quantity=position.quantity,
                        initial_quantity=position.quantity,
                    )
                )
            except Exception as error:
                _LOGGER.warning(
                    "Failed to close CFD position for %s: %s",
                    position.symbol,
                    error,
                )
        return tuple(closed_orders)

    @staticmethod
    def _to_string(value: object | None) -> str:
        """Safely convert object to string."""
        if value is None:
            return ""
        return str(value)
