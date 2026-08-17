"""
Botragram

Description:
    Binance REST transport client.

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
import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from time import time
from typing import Final, cast
from urllib.parse import urlencode

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RECV_WINDOW_MS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RETRY_DELAY_SECONDS,
)
from botragram.exchanges.base.rest import (
    BaseRestClient,
    JsonObject,
    JsonResponse,
    QueryParams,
    RequestHeaders,
)

__all__ = [
    "BinanceRestClient",
]


# =============================================================================
# Type Aliases
# =============================================================================
type MutableQueryParams = dict[str, str | int | float | bool]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_API_KEY_HEADER: Final[str] = "X-MBX-APIKEY"
_SIGNATURE_PARAMETER: Final[str] = "signature"
_TIMESTAMP_PARAMETER: Final[str] = "timestamp"
_RECV_WINDOW_PARAMETER: Final[str] = "recvWindow"


# =============================================================================
# Binance REST Client
# =============================================================================
class BinanceRestClient(BaseRestClient):
    """Send public and authenticated requests to the Binance REST API."""

    __slots__ = (
        "_api_key",
        "_api_secret",
        "_base_url",
        "_max_retries",
        "_recv_window_ms",
        "_retry_delay_seconds",
        "_session",
        "_timeout",
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        recv_window_ms: int = DEFAULT_RECV_WINDOW_MS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ) -> None:
        """Initialize the Binance REST client."""
        normalized_base_url = base_url.rstrip("/")

        if not normalized_base_url:
            raise ValueError("Base URL must not be empty")

        if recv_window_ms <= 0:
            raise ValueError("Receive window must be greater than zero")

        if request_timeout_seconds <= 0:
            raise ValueError("Request timeout must be greater than zero")

        if max_retries <= 0:
            raise ValueError("Maximum retries must be greater than zero")

        if retry_delay_seconds < 0:
            raise ValueError("Retry delay must not be negative")

        self._base_url = normalized_base_url
        self._api_key = api_key
        self._api_secret = api_secret
        self._recv_window_ms = recv_window_ms
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._timeout = aiohttp.ClientTimeout(
            total=request_timeout_seconds,
        )
        self._session: aiohttp.ClientSession | None = None

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP GET request."""
        return await self._request(
            method="GET",
            path=path,
            params=params,
            headers=headers,
            authenticated=authenticated,
            retryable=True,
        )

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP POST request."""
        return await self._request(
            method="POST",
            path=path,
            params=params,
            data=data,
            headers=headers,
            authenticated=authenticated,
            retryable=False,
        )

    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP DELETE request."""
        return await self._request(
            method="DELETE",
            path=path,
            params=params,
            headers=headers,
            authenticated=authenticated,
            retryable=False,
        )

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        session = self._session

        if session is not None and not session.closed:
            await session.close()

        self._session = None

    async def _request(
        self,
        *,
        method: str,
        path: str,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
        retryable: bool,
    ) -> JsonResponse:
        """Send a Binance REST request using an explicit retry policy."""
        url = self._build_url(path)
        maximum_attempts = self._max_retries if retryable else 1

        last_error: BaseException | None = None

        for attempt in range(1, maximum_attempts + 1):
            try:
                request_params = self._prepare_params(
                    params,
                    authenticated=authenticated,
                )
                request_headers = self._prepare_headers(
                    headers,
                    authenticated=authenticated,
                )
                session = self._get_session()

                async with session.request(
                    method=method,
                    url=url,
                    params=request_params,
                    json=data,
                    headers=request_headers,
                ) as response:
                    payload = await self._read_response(response)

                    if response.status >= 400:
                        raise RuntimeError(
                            self._format_http_error(
                                method=method,
                                url=url,
                                status=response.status,
                                payload=payload,
                            )
                        )

                    return payload

            except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
                last_error = error

                if attempt >= maximum_attempts:
                    raise

                delay = self._retry_delay_seconds * attempt

                _LOGGER.warning(
                    "Binance REST request failed; retrying",
                    extra={
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "method": method,
                        "path": path,
                    },
                )

                await asyncio.sleep(delay)

        raise RuntimeError("Binance REST request failed") from last_error

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the active HTTP session, creating it when necessary."""
        session = self._session

        if session is None or session.closed:
            session = aiohttp.ClientSession(
                timeout=self._timeout,
            )
            self._session = session

        return session

    def _prepare_params(
        self,
        params: QueryParams | None,
        *,
        authenticated: bool,
    ) -> MutableQueryParams:
        """Copy parameters and add Binance authentication fields."""
        prepared: MutableQueryParams = dict(params) if params is not None else {}

        if not authenticated:
            return prepared

        self._require_credentials()

        prepared[_TIMESTAMP_PARAMETER] = self._timestamp_ms()
        prepared[_RECV_WINDOW_PARAMETER] = self._recv_window_ms
        prepared[_SIGNATURE_PARAMETER] = self._create_signature(prepared)

        return prepared

    def _prepare_headers(
        self,
        headers: RequestHeaders | None,
        *,
        authenticated: bool,
    ) -> dict[str, str]:
        """Copy headers and add the Binance API key when required."""
        prepared = dict(headers) if headers is not None else {}

        if authenticated:
            self._require_credentials()
            prepared[_API_KEY_HEADER] = self._api_key

        return prepared

    def _create_signature(
        self,
        params: QueryParams,
    ) -> str:
        """Create the Binance HMAC SHA-256 query signature."""
        query_string = urlencode(params)

        return hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _require_credentials(self) -> None:
        """Raise when an authenticated request lacks credentials."""
        if not self._api_key:
            raise ValueError("Binance API key is required for authenticated requests")

        if not self._api_secret:
            raise ValueError(
                "Binance API secret is required for authenticated requests"
            )

    def _build_url(
        self,
        path: str,
    ) -> str:
        """Build an absolute Binance API URL."""
        normalized_path = path if path.startswith("/") else f"/{path}"

        return f"{self._base_url}{normalized_path}"

    @staticmethod
    async def _read_response(
        response: aiohttp.ClientResponse,
    ) -> JsonResponse:
        """Read and validate a top-level JSON object or array."""
        text = await response.text()

        if not text:
            return {}

        try:
            payload: object = json.loads(text)
        except json.JSONDecodeError as error:
            raise RuntimeError("Binance returned a non-JSON response") from error

        if isinstance(payload, dict):
            return cast(JsonObject, payload)

        if isinstance(payload, list):
            return cast(list[object], payload)

        raise RuntimeError("Binance returned an unexpected JSON response type")

    @staticmethod
    def _format_http_error(
        *,
        method: str,
        url: str,
        status: int,
        payload: JsonResponse,
    ) -> str:
        """Format a Binance HTTP error message."""
        code: object = None
        message: object = None

        if isinstance(payload, Mapping):
            code = payload.get("code")
            message = payload.get("msg")

        return (
            "Binance REST request failed: "
            f"method={method}, url={url}, status={status}, "
            f"code={code!r}, message={message!r}"
        )

    @staticmethod
    def _timestamp_ms() -> int:
        """Return the current Unix timestamp in milliseconds."""
        return int(time() * 1_000)

    async def __aenter__(self) -> BinanceRestClient:
        """Enter the asynchronous context manager."""
        self._get_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Exit the asynchronous context manager."""
        del exc_type, exc_value, traceback
        await self.close()
