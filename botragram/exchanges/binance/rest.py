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
from math import isfinite
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
    "BinanceRestResponseError",
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
_RETRY_AFTER_HEADER: Final[str] = "Retry-After"
_HTTP_AUTO_BAN_STATUS: Final[int] = 418
_HTTP_RATE_LIMIT_STATUS: Final[int] = 429
_HTTP_SERVER_ERROR_STATUS: Final[int] = 500


class BinanceRestResponseError(RuntimeError):
    """Retain structured Binance HTTP response metadata at the transport boundary."""

    __slots__ = ("code", "retry_after_seconds", "status")

    def __init__(
        self,
        *,
        status: int,
        payload: JsonResponse,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Initialize one failed Binance response."""
        super().__init__(message)
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        raw_code = payload.get("code") if isinstance(payload, Mapping) else None
        self.code = raw_code if isinstance(raw_code, int) else None


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

    async def start_user_data_stream(self, *, path: str) -> str:
        """Open a Binance listen key using API-key-only authentication."""
        return await self._user_stream_request(method="POST", path=path)

    async def keepalive_user_data_stream(self, *, path: str) -> str:
        """Refresh the active Binance listen key before its expiry."""
        return await self._user_stream_request(method="PUT", path=path)

    async def close_user_data_stream(self, *, path: str) -> None:
        """Close the active Binance listen key without signing a trade request."""
        await self._user_stream_request(method="DELETE", path=path)

    async def _user_stream_request(self, *, method: str, path: str) -> str:
        """Call one USER_STREAM endpoint that requires an API key but no signature."""
        payload = await self._request(
            method=method,
            path=path,
            headers={_API_KEY_HEADER: self._require_api_key()},
            authenticated=False,
            retryable=False,
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("Binance User Data Stream returned an invalid payload")
        listen_key = payload.get("listenKey")
        if not isinstance(listen_key, str) or not listen_key.strip():
            if method == "DELETE":
                return ""
            raise RuntimeError("Binance User Data Stream response has no listen key")
        return listen_key

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
                        raise BinanceRestResponseError(
                            status=response.status,
                            payload=payload,
                            retry_after_seconds=self._get_retry_after_seconds(
                                response=response,
                            ),
                            message=self._format_http_error(
                                method=method,
                                url=url,
                                status=response.status,
                                payload=payload,
                            ),
                        )

                    return payload

            except BinanceRestResponseError as error:
                if not self._is_retryable_response(error=error):
                    raise

                last_error = error

                if attempt >= maximum_attempts:
                    raise

                delay = self._get_retry_delay_seconds(
                    attempt=attempt,
                    retry_after_seconds=error.retry_after_seconds,
                )
                self._log_retry(
                    attempt=attempt,
                    delay_seconds=delay,
                    method=method,
                    path=path,
                    status=error.status,
                )
                await asyncio.sleep(delay)

            except (aiohttp.ClientError, TimeoutError) as error:
                last_error = error

                if attempt >= maximum_attempts:
                    raise

                delay = self._get_retry_delay_seconds(attempt=attempt)
                self._log_retry(
                    attempt=attempt,
                    delay_seconds=delay,
                    method=method,
                    path=path,
                )
                await asyncio.sleep(delay)

        raise RuntimeError("Binance REST request failed") from last_error

    def _get_retry_delay_seconds(
        self,
        *,
        attempt: int,
        retry_after_seconds: float | None = None,
    ) -> float:
        """Return retry delay while honoring Binance rate-limit guidance."""
        retry_delay = self._retry_delay_seconds * attempt

        if retry_after_seconds is None:
            return retry_delay

        return max(retry_delay, retry_after_seconds)

    @staticmethod
    def _get_retry_after_seconds(
        *,
        response: aiohttp.ClientResponse,
    ) -> float | None:
        """Return a valid numeric Retry-After response header, when supplied."""
        raw_retry_after = response.headers.get(_RETRY_AFTER_HEADER)
        if raw_retry_after is None:
            return None

        try:
            retry_after_seconds = float(raw_retry_after)
        except ValueError:
            return None

        if not isfinite(retry_after_seconds) or retry_after_seconds < 0:
            return None

        return retry_after_seconds

    @staticmethod
    def _is_retryable_response(*, error: BinanceRestResponseError) -> bool:
        """Return whether a read response represents a transient failure."""
        return (
            error.status in {_HTTP_AUTO_BAN_STATUS, _HTTP_RATE_LIMIT_STATUS}
            or error.status >= _HTTP_SERVER_ERROR_STATUS
        )

    @staticmethod
    def _log_retry(
        *,
        attempt: int,
        delay_seconds: float,
        method: str,
        path: str,
        status: int | None = None,
    ) -> None:
        """Log one bounded retry without credentials or payloads."""
        _LOGGER.warning(
            "Binance REST request failed; retrying",
            extra={
                "attempt": attempt,
                "delay_seconds": delay_seconds,
                "method": method,
                "path": path,
                "status": status,
            },
        )

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

    def _require_api_key(self) -> str:
        """Return the API key required by Binance USER_STREAM endpoints."""
        if not self._api_key:
            raise ValueError("Binance API key is required for User Data Stream")
        return self._api_key

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
