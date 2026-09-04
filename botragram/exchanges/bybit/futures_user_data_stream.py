"""
Botragram

Description:
    Bybit V5 private WebSocket user data stream transport.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncGenerator, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, cast

import aiohttp

from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.models import (
    Balance,
    FuturesUserDataAccountUpdate,
    FuturesUserDataEvent,
    FuturesUserDataOrderUpdate,
    FuturesUserDataPositionUpdate,
    FuturesUserDataStreamConnected,
    Order,
)

__all__ = [
    "BybitFuturesUserDataStream",
]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_PING_INTERVAL_SECONDS: Final[float] = 20.0
_WEBSOCKET_HEARTBEAT_SECONDS: Final[float] = 30.0

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")

# Bybit V5 private topic names
_TOPIC_WALLET: Final[str] = "wallet"
_TOPIC_POSITION: Final[str] = "position"
_TOPIC_ORDER: Final[str] = "order"

_SUBSCRIBE_TOPICS: Final[tuple[str, ...]] = (
    _TOPIC_WALLET,
    _TOPIC_POSITION,
    _TOPIC_ORDER,
)

# Bybit V5 order side / type / status maps
_SIDE_MAP: Final[Mapping[str, OrderSide]] = {
    "Buy": OrderSide.BUY,
    "BUY": OrderSide.BUY,
    "Sell": OrderSide.SELL,
    "SELL": OrderSide.SELL,
}

_ORDER_TYPE_MAP: Final[Mapping[str, OrderType]] = {
    "Market": OrderType.MARKET,
    "MARKET": OrderType.MARKET,
    "Limit": OrderType.LIMIT,
    "LIMIT": OrderType.LIMIT,
    "Stop": OrderType.STOP,
    "STOP": OrderType.STOP,
    "StopMarket": OrderType.STOP_MARKET,
    "STOP_MARKET": OrderType.STOP_MARKET,
    "TakeProfit": OrderType.TAKE_PROFIT,
    "TAKE_PROFIT": OrderType.TAKE_PROFIT,
    "TakeProfitMarket": OrderType.TAKE_PROFIT_MARKET,
    "TAKE_PROFIT_MARKET": OrderType.TAKE_PROFIT_MARKET,
}

_STATUS_MAP: Final[Mapping[str, OrderStatus]] = {
    "New": OrderStatus.NEW,
    "NEW": OrderStatus.NEW,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "Filled": OrderStatus.FILLED,
    "FILLED": OrderStatus.FILLED,
    "Cancelled": OrderStatus.CANCELED,
    "CANCELLED": OrderStatus.CANCELED,
    "Canceled": OrderStatus.CANCELED,
    "CANCELED": OrderStatus.CANCELED,
    "Rejected": OrderStatus.REJECTED,
    "REJECTED": OrderStatus.REJECTED,
    "Expired": OrderStatus.EXPIRED,
    "EXPIRED": OrderStatus.EXPIRED,
    "Untriggered": OrderStatus.NEW,
    "UNTRIGGERED": OrderStatus.NEW,
    "Triggered": OrderStatus.NEW,
    "TRIGGERED": OrderStatus.NEW,
}

_POSITION_SIDE_MAP: Final[Mapping[str, PositionSide]] = {
    "Buy": PositionSide.LONG,
    "BUY": PositionSide.LONG,
    "Sell": PositionSide.SHORT,
    "SELL": PositionSide.SHORT,
    "None": PositionSide.LONG,
    "NONE": PositionSide.LONG,
}


def _to_decimal(value: object) -> Decimal:
    """Safely parse a Decimal from an object, returning zero on failure."""
    if value is None or value == "":
        return _DECIMAL_ZERO
    try:
        return Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        return _DECIMAL_ZERO


def _to_ms_timestamp(value: object) -> datetime:
    """Parse a millisecond-integer timestamp into a UTC datetime."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=UTC)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return datetime.fromtimestamp(int(stripped) / 1000.0, tz=UTC)
    return datetime.now(UTC)


def _build_auth_signature(*, api_secret: str, expires: int) -> str:
    """Return HMAC-SHA256 hex signature for Bybit V5 WebSocket auth."""
    message = f"GET/realtime{expires}"
    return hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class BybitFuturesUserDataStream:
    """Yield normalized private Futures events from the Bybit V5 private WebSocket."""

    __slots__ = (
        "_api_key",
        "_api_secret",
        "_closed",
        "_private_websocket_url",
        "_session",
    )

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        private_websocket_url: str,
    ) -> None:
        """Initialize the Bybit private stream transport.

        Args:
            api_key: Bybit API key for HMAC authentication.
            api_secret: Bybit API secret for HMAC authentication.
            private_websocket_url: Full Bybit V5 private WebSocket URL
                (e.g. ``wss://stream-demo.bybit.com/v5/private``).
        """
        normalized_url = private_websocket_url.rstrip("/")
        if not normalized_url:
            raise ValueError("Bybit private WebSocket URL must not be empty")
        if not api_key.strip():
            raise ValueError("Bybit API key must not be empty")
        if not api_secret.strip():
            raise ValueError("Bybit API secret must not be empty")

        self._api_key = api_key
        self._api_secret = api_secret
        self._private_websocket_url = normalized_url
        self._session: aiohttp.ClientSession | None = None
        self._closed = False

    async def stream_events(self) -> AsyncGenerator[FuturesUserDataEvent, None]:
        """Authenticate, subscribe, and yield private account events until closed."""
        if self._closed:
            return

        socket: aiohttp.ClientWebSocketResponse | None = None
        ping_task: asyncio.Task[None] | None = None
        try:
            socket = await self._get_session().ws_connect(
                self._private_websocket_url,
                receive_timeout=None,
                heartbeat=_WEBSOCKET_HEARTBEAT_SECONDS,
                autoclose=True,
                autoping=True,
            )

            # Authenticate
            expires = int((time.time() + 10) * 1000)
            signature = _build_auth_signature(
                api_secret=self._api_secret,
                expires=expires,
            )
            auth_msg = json.dumps(
                {"op": "auth", "args": [self._api_key, expires, signature]}
            )
            await socket.send_str(auth_msg)

            # Wait for auth response
            auth_resp_raw = await socket.receive()
            if auth_resp_raw.type is aiohttp.WSMsgType.TEXT:
                auth_resp_data = json.loads(auth_resp_raw.data)
                if not auth_resp_data.get("success", False):
                    raise RuntimeError(
                        f"Bybit private stream authentication failed: "
                        f"{auth_resp_data.get('ret_msg', 'unknown error')}"
                    )
            else:
                raise RuntimeError(
                    "Bybit private stream: unexpected message type during auth"
                )

            # Subscribe to private topics
            sub_msg = json.dumps({"op": "subscribe", "args": list(_SUBSCRIBE_TOPICS)})
            await socket.send_str(sub_msg)

            # Wait for subscribe confirmation
            sub_resp_raw = await socket.receive()
            if sub_resp_raw.type is aiohttp.WSMsgType.TEXT:
                sub_resp_data = json.loads(sub_resp_raw.data)
                if not sub_resp_data.get("success", False):
                    raise RuntimeError(
                        f"Bybit private stream subscription failed: "
                        f"{sub_resp_data.get('ret_msg', 'unknown error')}"
                    )

            # Start ping heartbeat
            ping_task = asyncio.create_task(
                self._ping_forever(socket=socket),
                name="bybit-futures-user-data-ping",
            )

            # Signal ready
            yield FuturesUserDataStreamConnected(observed_at=datetime.now(UTC))

            # Consume events
            async for message in socket:
                event = self._parse_message(message)
                if event is not None:
                    yield event

        finally:
            if ping_task is not None:
                ping_task.cancel()
                await asyncio.gather(ping_task, return_exceptions=True)
            if socket is not None and not socket.closed:
                await socket.close()

    async def close(self) -> None:
        """Stop the private socket and release its session idempotently."""
        self._closed = True
        session = self._session
        if session is not None and not session.closed:
            await session.close()
        self._session = None

    async def _ping_forever(
        self,
        *,
        socket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        """Send periodic pings to keep the Bybit private WebSocket alive."""
        while not self._closed:
            await asyncio.sleep(_PING_INTERVAL_SECONDS)
            if socket.closed:
                return
            try:
                await socket.send_str(json.dumps({"op": "ping"}))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOGGER.warning(
                    "Bybit private stream ping failed: %s",
                    error,
                )
                await socket.close()
                return

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the lazily-created private WebSocket session."""
        session = self._session
        if session is None or session.closed:
            session = aiohttp.ClientSession()
            self._session = session
        return session

    def _parse_message(
        self,
        message: aiohttp.WSMessage,
    ) -> FuturesUserDataEvent | None:
        """Map one Bybit V5 private WebSocket payload to a domain event."""
        if message.type is aiohttp.WSMsgType.TEXT:
            raw_data = message.data
            if not isinstance(raw_data, str):
                raise ValueError("Bybit private stream text payload is invalid")
            try:
                payload_object: object = json.loads(raw_data)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "Bybit private stream returned invalid JSON"
                ) from error
            if not isinstance(payload_object, Mapping):
                # pong / other control frames — silently ignore
                return None
            payload = cast(Mapping[str, object], payload_object)

            # Ignore heartbeat pong and op-level responses (success/fail)
            if "op" in payload or "ret_msg" in payload:
                return None

            topic = str(payload.get("topic", ""))
            if topic == _TOPIC_WALLET:
                return self._map_wallet_event(payload=payload)
            if topic == _TOPIC_POSITION:
                return self._map_position_event(payload=payload)
            if topic == _TOPIC_ORDER:
                return self._map_order_event(payload=payload)
            return None

        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        }:
            raise RuntimeError("Bybit private WebSocket connection was closed")
        return None

    @staticmethod
    def _map_wallet_event(
        *,
        payload: Mapping[str, object],
    ) -> FuturesUserDataAccountUpdate:
        """Map Bybit V5 ``wallet`` topic push to a domain account update."""
        observed_at = _to_ms_timestamp(payload.get("creationTime"))
        data = payload.get("data")
        if not isinstance(data, list):
            return FuturesUserDataAccountUpdate(
                observed_at=observed_at,
                balances=(),
                positions=(),
            )

        balances: list[Balance] = []
        for acc in cast(list[object], data):
            if not isinstance(acc, dict):
                continue
            acc_map = cast(Mapping[str, object], acc)
            coins = acc_map.get("coin")
            if not isinstance(coins, list):
                continue
            for coin_data in cast(list[object], coins):
                if not isinstance(coin_data, dict):
                    continue
                coin_map = cast(Mapping[str, object], coin_data)
                coin_name = str(coin_map.get("coin", "")).strip().upper()
                if not coin_name:
                    continue
                wallet_balance = _to_decimal(coin_map.get("walletBalance"))
                raw_available = coin_map.get("availableToWithdraw")
                if raw_available is None or raw_available == "":
                    raw_available = coin_map.get("availableBalance")
                available = _to_decimal(
                    raw_available if raw_available is not None else wallet_balance
                )
                locked = max(_DECIMAL_ZERO, wallet_balance - available)
                balances.append(
                    Balance(
                        asset=coin_name,
                        free=available,
                        locked=locked,
                    )
                )

        return FuturesUserDataAccountUpdate(
            observed_at=observed_at,
            balances=tuple(balances),
            positions=(),
        )

    @staticmethod
    def _map_position_event(
        *,
        payload: Mapping[str, object],
    ) -> FuturesUserDataAccountUpdate:
        """Map Bybit V5 ``position`` topic push to a domain account update."""
        observed_at = _to_ms_timestamp(payload.get("creationTime"))
        data = payload.get("data")
        if not isinstance(data, list):
            return FuturesUserDataAccountUpdate(
                observed_at=observed_at,
                balances=(),
                positions=(),
            )

        positions: list[FuturesUserDataPositionUpdate] = []
        for item in cast(list[object], data):
            if not isinstance(item, dict):
                continue
            pos = cast(Mapping[str, object], item)
            symbol = str(pos.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            raw_side = str(pos.get("side", "Buy")).strip()
            position_side = _POSITION_SIDE_MAP.get(raw_side, PositionSide.LONG)
            qty = _to_decimal(pos.get("size"))
            # Negative quantity signals SHORT direction for the cache
            signed_qty = qty if position_side is PositionSide.LONG else -qty
            entry_price = _to_decimal(pos.get("avgPrice", pos.get("entryPrice")))
            unrealized_pnl = _to_decimal(pos.get("unrealisedPnl"))
            positions.append(
                FuturesUserDataPositionUpdate(
                    symbol=symbol,
                    quantity=signed_qty,
                    entry_price=entry_price,
                    unrealized_pnl=unrealized_pnl,
                )
            )

        return FuturesUserDataAccountUpdate(
            observed_at=observed_at,
            balances=(),
            positions=tuple(positions),
        )

    @staticmethod
    def _map_order_event(
        *,
        payload: Mapping[str, object],
    ) -> FuturesUserDataOrderUpdate | None:
        """Map Bybit V5 ``order`` topic push to a domain order update."""
        observed_at = _to_ms_timestamp(payload.get("creationTime"))
        data = payload.get("data")
        if not isinstance(data, list):
            return None

        # Yield the first parseable order; each topic push is typically one order
        for item in cast(list[object], data):
            if not isinstance(item, dict):
                continue
            order_payload = cast(Mapping[str, object], item)
            try:
                return BybitFuturesUserDataStream._parse_order(
                    payload=order_payload,
                    observed_at=observed_at,
                )
            except ValueError:
                _LOGGER.warning("Bybit private stream ignored unsupported order update")
                continue
        return None

    @staticmethod
    def _parse_order(
        *,
        payload: Mapping[str, object],
        observed_at: datetime,
    ) -> FuturesUserDataOrderUpdate:
        """Map one Bybit V5 order push payload to a FuturesUserDataOrderUpdate."""
        order_id = str(payload.get("orderId", "")).strip()
        if not order_id:
            raise ValueError("Bybit order update missing orderId")

        symbol = str(payload.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError("Bybit order update missing symbol")

        raw_side = str(payload.get("side", "")).strip()
        side = _SIDE_MAP.get(raw_side)
        if side is None:
            raise ValueError(f"Bybit order update unknown side: {raw_side!r}")

        raw_order_type = str(payload.get("orderType", "")).strip()
        order_type = _ORDER_TYPE_MAP.get(raw_order_type)
        if order_type is None:
            raise ValueError(
                f"Bybit order update unknown order type: {raw_order_type!r}"
            )

        raw_status = str(payload.get("orderStatus", "")).strip()
        status = _STATUS_MAP.get(raw_status)
        if status is None:
            raise ValueError(f"Bybit order update unknown status: {raw_status!r}")

        qty = _to_decimal(payload.get("qty"))
        executed_qty = _to_decimal(payload.get("cumExecQty", payload.get("leavesQty")))
        raw_price = _to_decimal(payload.get("price"))
        price = raw_price if raw_price > _DECIMAL_ZERO else None
        raw_stop_price = _to_decimal(
            payload.get("triggerPrice", payload.get("stopPrice"))
        )
        stop_price = raw_stop_price if raw_stop_price > _DECIMAL_ZERO else None
        client_order_id = str(payload.get("orderLinkId", "")).strip() or None

        created_at = _to_ms_timestamp(payload.get("createdTime"))
        updated_at = _to_ms_timestamp(
            payload.get("updatedTime", payload.get("createdTime"))
        )

        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            quantity=qty,
            executed_quantity=executed_qty,
            price=price,
            stop_price=stop_price,
            client_order_id=client_order_id,
            created_at=created_at,
            updated_at=updated_at,
        )
        return FuturesUserDataOrderUpdate(
            observed_at=observed_at,
            order=order,
        )
