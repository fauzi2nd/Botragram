"""
Botragram

Description:
    Binance USDⓈ-M Futures private User Data Stream transport.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, cast

import aiohttp

from botragram.enums import FuturesAlgoOrderStatus, OrderSide, OrderStatus, OrderType
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import (
    Balance,
    FuturesUserDataAccountUpdate,
    FuturesUserDataAlgoUpdate,
    FuturesUserDataEvent,
    FuturesUserDataOrderUpdate,
    FuturesUserDataPositionUpdate,
    FuturesUserDataStreamConnected,
    Order,
)

__all__ = [
    "BinanceFuturesUserDataStream",
]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_ACCOUNT_UPDATE_EVENT: Final[str] = "ACCOUNT_UPDATE"
_ALGO_UPDATE_EVENT: Final[str] = "ALGO_UPDATE"
_ORDER_UPDATE_EVENT: Final[str] = "ORDER_TRADE_UPDATE"
_LISTEN_KEY_EXPIRED_EVENT: Final[str] = "listenKeyExpired"
_LISTEN_KEY_PATH: Final[str] = "/fapi/v1/listenKey"
_KEEPALIVE_SECONDS: Final[float] = 30.0 * 60.0
_WEBSOCKET_HEARTBEAT_SECONDS: Final[float] = 30.0


class BinanceFuturesUserDataStream:
    """Yield normalized private Futures events from one managed listen key."""

    __slots__ = (
        "_closed",
        "_heartbeat_seconds",
        "_rest",
        "_session",
        "_websocket_base_url",
    )

    def __init__(
        self,
        *,
        rest: BinanceRestClient,
        websocket_base_url: str,
        heartbeat_seconds: float = _KEEPALIVE_SECONDS,
    ) -> None:
        """Initialize the private stream transport.

        Args:
            rest: Binance REST transport that owns API-key-only listen-key calls.
            websocket_base_url: Existing Futures public WebSocket base URL.
            heartbeat_seconds: Listen-key keepalive interval below Binance expiry.
        """
        if heartbeat_seconds <= 0:
            raise ValueError("User Data Stream heartbeat must be positive")

        normalized_base_url = websocket_base_url.rstrip("/")
        if not normalized_base_url:
            raise ValueError("User Data Stream WebSocket URL must not be empty")

        self._rest = rest
        self._websocket_base_url = self.build_private_websocket_base_url(
            normalized_base_url
        )
        self._heartbeat_seconds = heartbeat_seconds
        self._session: aiohttp.ClientSession | None = None
        self._closed = False

    async def stream_events(self) -> AsyncIterator[FuturesUserDataEvent]:
        """Open one listen key and yield buffered private events until closed."""
        if self._closed:
            return

        listen_key = await self._rest.start_user_data_stream(path=_LISTEN_KEY_PATH)
        socket: aiohttp.ClientWebSocketResponse | None = None
        keepalive_task: asyncio.Task[None] | None = None
        try:
            socket = await self._get_session().ws_connect(
                f"{self._websocket_base_url}/ws/{listen_key}",
                receive_timeout=None,
                heartbeat=_WEBSOCKET_HEARTBEAT_SECONDS,
                autoclose=True,
                autoping=True,
            )
            keepalive_task = asyncio.create_task(
                self._keepalive(listen_key=listen_key, socket=socket),
                name="binance-futures-user-data-keepalive",
            )
            yield FuturesUserDataStreamConnected(observed_at=datetime.now(UTC))
            async for message in socket:
                event = self.parse_event(message)
                if event is not None:
                    yield event
        finally:
            if keepalive_task is not None:
                keepalive_task.cancel()
                await asyncio.gather(keepalive_task, return_exceptions=True)
            if socket is not None and not socket.closed:
                await socket.close()
            try:
                await self._rest.close_user_data_stream(path=_LISTEN_KEY_PATH)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.warning("Binance Futures User Data Stream close failed")

    async def close(self) -> None:
        """Stop the private socket and release its session idempotently."""
        self._closed = True
        session = self._session
        if session is not None and not session.closed:
            await session.close()
        self._session = None

    async def _keepalive(
        self,
        *,
        listen_key: str,
        socket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        """Keep the active listen key alive without exposing it in logs."""
        while not self._closed:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                refreshed_key = await self._rest.keepalive_user_data_stream(
                    path=_LISTEN_KEY_PATH,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.warning("Binance Futures User Data Stream keepalive failed")
                await socket.close()
                return
            if refreshed_key != listen_key:
                _LOGGER.warning("Binance Futures User Data Stream listen key rotated")
                await socket.close()
                return

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the lazily-created private WebSocket session."""
        session = self._session
        if session is None or session.closed:
            session = aiohttp.ClientSession()
            self._session = session
        return session

    @staticmethod
    def build_private_websocket_base_url(public_base_url: str) -> str:
        """Derive Binance's explicit private base from the public market base."""
        return f"{public_base_url.removesuffix('/market')}/private"

    @staticmethod
    def parse_event(message: aiohttp.WSMessage) -> FuturesUserDataEvent | None:
        """Map one Binance WebSocket payload to a validated domain event."""
        if message.type is aiohttp.WSMsgType.TEXT:
            raw_data = message.data
            if not isinstance(raw_data, str):
                raise ValueError("Binance private stream text payload is invalid")
            try:
                payload_object: object = json.loads(raw_data)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "Binance private stream returned invalid JSON"
                ) from error
            if not isinstance(payload_object, Mapping):
                raise ValueError("Binance private stream payload must be a mapping")
            payload = cast(Mapping[str, object], payload_object)
            event_type = payload.get("e")
            if event_type == _ACCOUNT_UPDATE_EVENT:
                return BinanceFuturesUserDataStream.map_account_update(payload=payload)
            if event_type == _ORDER_UPDATE_EVENT:
                try:
                    return BinanceFuturesUserDataStream.map_order_update(
                        payload=payload
                    )
                except ValueError:
                    _LOGGER.warning(
                        "Binance private stream ignored unsupported order update"
                    )
                    return None
            if event_type == _ALGO_UPDATE_EVENT:
                try:
                    return BinanceFuturesUserDataStream.map_algo_update(payload=payload)
                except ValueError:
                    _LOGGER.warning(
                        "Binance private stream ignored unsupported algo update"
                    )
                    return None
            if event_type == _LISTEN_KEY_EXPIRED_EVENT:
                raise RuntimeError("Binance private stream listen key expired")
            return None

        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        }:
            raise RuntimeError("Binance private WebSocket connection was closed")
        return None

    @staticmethod
    def map_account_update(
        *,
        payload: Mapping[str, object],
    ) -> FuturesUserDataAccountUpdate:
        """Map Binance ``ACCOUNT_UPDATE`` without leaking vendor payloads."""
        account_data = BinanceFuturesUserDataStream._require_mapping(
            payload.get("a"),
            label="account update",
        )
        raw_balances = BinanceFuturesUserDataStream._require_sequence(
            account_data.get("B"),
            label="account balances",
        )
        raw_positions = BinanceFuturesUserDataStream._require_sequence(
            account_data.get("P"),
            label="account positions",
        )
        balances = tuple(
            Balance(
                asset=BinanceFuturesUserDataStream._require_text(item, key="a"),
                free=BinanceFuturesUserDataStream._decimal(item, key="cw"),
                locked=max(
                    BinanceFuturesUserDataStream._decimal(item, key="wb")
                    - BinanceFuturesUserDataStream._decimal(item, key="cw"),
                    Decimal("0"),
                ),
            )
            for item in (
                BinanceFuturesUserDataStream._require_mapping(value, label="balance")
                for value in raw_balances
            )
        )
        positions = tuple(
            FuturesUserDataPositionUpdate(
                symbol=BinanceFuturesUserDataStream._require_text(item, key="s"),
                quantity=BinanceFuturesUserDataStream._decimal(item, key="pa"),
                entry_price=BinanceFuturesUserDataStream._decimal(item, key="ep"),
                unrealized_pnl=BinanceFuturesUserDataStream._decimal(item, key="up"),
            )
            for item in (
                BinanceFuturesUserDataStream._require_mapping(value, label="position")
                for value in raw_positions
            )
        )
        return FuturesUserDataAccountUpdate(
            observed_at=BinanceFuturesUserDataStream._timestamp(payload, key="E"),
            balances=balances,
            positions=positions,
        )

    @staticmethod
    def map_algo_update(
        *,
        payload: Mapping[str, object],
    ) -> FuturesUserDataAlgoUpdate:
        """Map Binance ``ALGO_UPDATE`` to a typed conditional-order state."""
        data = BinanceFuturesUserDataStream._require_mapping(
            payload.get("o"),
            label="algo update",
        )
        raw_trigger_price = BinanceFuturesUserDataStream._decimal(data, key="tp")
        return FuturesUserDataAlgoUpdate(
            observed_at=BinanceFuturesUserDataStream._timestamp(payload, key="E"),
            client_algo_id=BinanceFuturesUserDataStream._require_text(
                data,
                key="caid",
            ),
            algo_id=BinanceFuturesUserDataStream._require_text(data, key="aid"),
            symbol=BinanceFuturesUserDataStream._require_text(data, key="s"),
            status=FuturesAlgoOrderStatus(
                BinanceFuturesUserDataStream._require_text(data, key="X").lower()
            ),
            order_type=OrderType(
                BinanceFuturesUserDataStream._require_text(data, key="o").lower()
            ),
            trigger_price=(
                raw_trigger_price if raw_trigger_price != Decimal("0") else None
            ),
        )

    @staticmethod
    def map_order_update(
        *,
        payload: Mapping[str, object],
    ) -> FuturesUserDataOrderUpdate:
        """Map Binance ``ORDER_TRADE_UPDATE`` to the existing immutable Order."""
        data = BinanceFuturesUserDataStream._require_mapping(
            payload.get("o"),
            label="order update",
        )
        raw_stop_price = BinanceFuturesUserDataStream._decimal(data, key="sp")
        raw_price = BinanceFuturesUserDataStream._decimal(data, key="p")
        order = Order(
            order_id=BinanceFuturesUserDataStream._require_text(data, key="i"),
            symbol=BinanceFuturesUserDataStream._require_text(data, key="s"),
            side=OrderSide(BinanceFuturesUserDataStream._require_text(data, key="S")),
            order_type=OrderType(
                BinanceFuturesUserDataStream._require_text(data, key="o").lower()
            ),
            status=OrderStatus(
                BinanceFuturesUserDataStream._require_text(data, key="X").lower()
            ),
            quantity=BinanceFuturesUserDataStream._decimal(data, key="q"),
            executed_quantity=BinanceFuturesUserDataStream._decimal(data, key="z"),
            price=raw_price if raw_price != Decimal("0") else None,
            stop_price=raw_stop_price if raw_stop_price != Decimal("0") else None,
            created_at=BinanceFuturesUserDataStream._timestamp(data, key="T"),
            updated_at=BinanceFuturesUserDataStream._timestamp(payload, key="E"),
            client_order_id=BinanceFuturesUserDataStream._require_text(data, key="c"),
        )
        return FuturesUserDataOrderUpdate(
            observed_at=BinanceFuturesUserDataStream._timestamp(payload, key="E"),
            order=order,
        )

    @staticmethod
    def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
        """Narrow one vendor mapping field or raise a protocol error."""
        if not isinstance(value, Mapping):
            raise ValueError(f"Binance private stream {label} must be a mapping")
        return cast(Mapping[str, object], value)

    @staticmethod
    def _require_sequence(value: object, *, label: str) -> tuple[object, ...]:
        """Narrow one vendor sequence field or raise a protocol error."""
        if not isinstance(value, list):
            raise ValueError(f"Binance private stream {label} must be a list")
        return tuple(cast(list[object], value))

    @staticmethod
    def _require_text(data: Mapping[str, object], *, key: str) -> str:
        """Return a required non-empty string-compatible vendor field."""
        value = data.get(key)
        normalized = str(value).strip() if value is not None else ""
        if not normalized:
            raise ValueError(f"Binance private stream field {key!r} is missing")
        return normalized

    @staticmethod
    def _decimal(data: Mapping[str, object], *, key: str) -> Decimal:
        """Return one required finite Decimal vendor field."""
        try:
            value = Decimal(BinanceFuturesUserDataStream._require_text(data, key=key))
        except InvalidOperation as error:
            raise ValueError(
                f"Binance private stream field {key!r} is invalid"
            ) from error
        if not value.is_finite():
            raise ValueError(f"Binance private stream field {key!r} must be finite")
        return value

    @staticmethod
    def _timestamp(data: Mapping[str, object], *, key: str) -> datetime:
        """Return one required millisecond timestamp in UTC."""
        raw_timestamp = BinanceFuturesUserDataStream._require_text(data, key=key)
        try:
            timestamp_ms = int(raw_timestamp)
        except ValueError as error:
            raise ValueError(
                f"Binance private stream field {key!r} is invalid"
            ) from error
        return datetime.fromtimestamp(timestamp_ms / 1_000, tz=UTC)
