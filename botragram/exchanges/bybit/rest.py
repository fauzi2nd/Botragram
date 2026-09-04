"""
Botragram

Description:
    Bybit V5 REST transport client.

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
    "BybitRestClient",
    "BybitRestResponseError",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_HEADER_API_KEY: Final[str] = "X-BAPI-API-KEY"
_HEADER_TIMESTAMP: Final[str] = "X-BAPI-TIMESTAMP"
_HEADER_SIGNATURE: Final[str] = "X-BAPI-SIGN"
_HEADER_RECV_WINDOW: Final[str] = "X-BAPI-RECV-WINDOW"
_HEADER_SIGN_TYPE: Final[str] = "X-BAPI-SIGN-TYPE"

_RET_CODE_OK: Final[int] = 0
_SERVER_TIME_PATH: Final[str] = "/v5/market/time"
_RETRYABLE_RATE_LIMIT_RET_CODES: Final[frozenset[int]] = frozenset({10006, 10018})
_RETRYABLE_SERVER_RET_CODES: Final[frozenset[int]] = frozenset({10000, 10016})
_RETRYABLE_RET_CODES: Final[frozenset[int]] = (
    _RETRYABLE_RATE_LIMIT_RET_CODES | _RETRYABLE_SERVER_RET_CODES
)
_RATE_LIMIT_MIN_BACKOFF_SECONDS: Final[float] = 1.5


# =============================================================================
# Exceptions
# =============================================================================
class BybitRestResponseError(RuntimeError):
    """Raised when Bybit returns a non-zero return code."""

    def __init__(self, *, ret_code: int, ret_msg: str) -> None:
        super().__init__(f"Bybit V5 error {ret_code}: {ret_msg}")
        self.ret_code = ret_code
        self.ret_msg = ret_msg


# =============================================================================
# Bybit REST Client
# =============================================================================
class BybitRestClient(BaseRestClient):
    """Asynchronous HTTP transport for Bybit V5 API."""

    __slots__ = (
        "_api_key",
        "_api_secret",
        "_base_url",
        "_max_retries",
        "_recv_window_ms",
        "_retry_delay_seconds",
        "_server_time_offset_ms",
        "_session",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        recv_window_ms: int = DEFAULT_RECV_WINDOW_MS,
    ) -> None:
        """Initialize the Bybit V5 REST transport."""
        normalized_url = base_url.rstrip("/")
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid Bybit base URL: {base_url!r}")

        self._base_url: str = normalized_url
        self._api_key: str = api_key.strip()
        self._api_secret: str = api_secret.strip()
        self._timeout_seconds: float = timeout_seconds
        self._max_retries: int = max(0, max_retries)
        self._retry_delay_seconds: float = max(0.0, retry_delay_seconds)
        self._recv_window_ms: int = recv_window_ms
        self._server_time_offset_ms: int = 0
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        """Return the target REST base URL."""
        return self._base_url

    @property
    def has_credentials(self) -> bool:
        """Return whether API credentials are provided."""
        return bool(self._api_key and self._api_secret)

    @property
    def server_time_offset_ms(self) -> int:
        """Return the synchronized clock offset in milliseconds."""
        return self._server_time_offset_ms

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return or lazily initialize the HTTP client session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    def _current_timestamp_ms(self) -> int:
        """Return local time adjusted by the synchronized server offset."""
        return int(time() * 1000) + self._server_time_offset_ms

    async def synchronize_time(self, *, path: str = _SERVER_TIME_PATH) -> int:
        """Synchronize client time offset with Bybit server time."""
        response = await self.get(path=path, authenticated=False)
        if not isinstance(response, dict):
            raise ValueError("Bybit server time response is not a valid JSON object")

        server_time_ms: int | None = None
        raw_time = response.get("time")
        if isinstance(raw_time, (int, float, str)):
            server_time_ms = int(raw_time)
        else:
            raw_result = response.get("result")
            if isinstance(raw_result, dict):
                result_obj = cast(JsonObject, raw_result)
                raw_time_second = result_obj.get("timeSecond")
                if isinstance(raw_time_second, (int, float, str)):
                    server_time_ms = int(raw_time_second) * 1000

        if server_time_ms is None:
            raise ValueError("Bybit server time could not be parsed from response")

        local_time_ms = int(time() * 1000)
        self._server_time_offset_ms = server_time_ms - local_time_ms
        _LOGGER.debug(
            "Bybit server time offset synchronized: %d ms", self._server_time_offset_ms
        )
        return self._server_time_offset_ms

    def _sign(self, *, timestamp_str: str, payload_str: str) -> str:
        """Compute Bybit V5 HMAC-SHA256 signature."""
        if not self._api_secret:
            raise ValueError("Cannot sign Bybit request without API secret")

        message = f"{timestamp_str}{self._api_key}{self._recv_window_ms}{payload_str}"
        return hmac.new(
            self._api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _prepare_headers(
        self,
        *,
        authenticated: bool,
        payload_str: str,
        custom_headers: RequestHeaders | None = None,
    ) -> dict[str, str]:
        """Build request headers, optionally injecting Bybit V5 auth."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if custom_headers:
            headers.update(custom_headers)

        if authenticated:
            if not self.has_credentials:
                raise ValueError(
                    "Authenticated request requires Bybit API key and secret"
                )

            timestamp_str = str(self._current_timestamp_ms())
            signature = self._sign(
                timestamp_str=timestamp_str,
                payload_str=payload_str,
            )
            headers[_HEADER_API_KEY] = self._api_key
            headers[_HEADER_TIMESTAMP] = timestamp_str
            headers[_HEADER_SIGNATURE] = signature
            headers[_HEADER_RECV_WINDOW] = str(self._recv_window_ms)
            headers[_HEADER_SIGN_TYPE] = "2"

        return headers

    @staticmethod
    async def _read_response(response: aiohttp.ClientResponse) -> JsonResponse:
        """Read and validate a top-level JSON object or array."""
        text = await response.text()
        if not text:
            if response.status == 429:
                raise BybitRestResponseError(
                    ret_code=10006,
                    ret_msg="HTTP 429 Too Many Requests (empty body)",
                )
            return {}

        try:
            payload: object = json.loads(text)
        except json.JSONDecodeError as error:
            if response.status == 429:
                raise BybitRestResponseError(
                    ret_code=10006,
                    ret_msg=f"HTTP 429 Too Many Requests: {text[:200]}",
                ) from error
            raise RuntimeError("Bybit returned a non-JSON response") from error

        if isinstance(payload, dict):
            return cast(JsonObject, payload)

        if isinstance(payload, list):
            return cast(list[object], payload)

        raise RuntimeError("Bybit returned an unexpected JSON response type")

    @staticmethod
    def _validate_response_envelope(payload: JsonResponse) -> JsonResponse:
        """Validate Bybit V5 standard response envelope and return payload."""
        if isinstance(payload, dict):
            ret_code = payload.get("retCode")
            if isinstance(ret_code, int) and ret_code != _RET_CODE_OK:
                ret_msg_val = payload.get("retMsg")
                ret_msg = (
                    str(ret_msg_val) if ret_msg_val is not None else "Unknown error"
                )
                raise BybitRestResponseError(ret_code=ret_code, ret_msg=ret_msg)

        return payload

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP GET request to Bybit V5."""
        clean_params = {k: str(v) for k, v in params.items()} if params else {}
        query_string = urlencode(clean_params) if clean_params else ""
        request_headers = self._prepare_headers(
            authenticated=authenticated,
            payload_str=query_string,
            custom_headers=headers,
        )

        url = f"{self._base_url}{path}"
        session = await self._get_session()

        for attempt in range(self._max_retries + 1):
            try:
                async with session.get(
                    url,
                    params=clean_params or None,
                    headers=request_headers,
                ) as resp:
                    payload = await self._read_response(resp)
                    return self._validate_response_envelope(payload)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt >= self._max_retries:
                    raise
                _LOGGER.warning(
                    "Bybit GET %s failed (attempt %d/%d): %s",
                    path,
                    attempt + 1,
                    self._max_retries,
                    error,
                )
                await asyncio.sleep(self._retry_delay_seconds * (2**attempt))
            except BybitRestResponseError as error:
                if (
                    attempt >= self._max_retries
                    or error.ret_code not in _RETRYABLE_RET_CODES
                ):
                    raise
                backoff = (
                    max(
                        _RATE_LIMIT_MIN_BACKOFF_SECONDS,
                        self._retry_delay_seconds * (2**attempt),
                    )
                    if error.ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES
                    else self._retry_delay_seconds * (2**attempt)
                )
                _LOGGER.warning(
                    "Bybit GET %s returned retryable error %d (attempt %d/%d), "
                    "backing off %.1fs: %s",
                    path,
                    error.ret_code,
                    attempt + 1,
                    self._max_retries,
                    backoff,
                    error.ret_msg,
                )
                await asyncio.sleep(backoff)

        raise RuntimeError("Unreachable request loop termination")

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP POST request to Bybit V5."""
        clean_params = {k: str(v) for k, v in params.items()} if params else None
        body_str = (
            json.dumps(data, separators=(",", ":"), ensure_ascii=True)
            if data is not None
            else ""
        )
        request_headers = self._prepare_headers(
            authenticated=authenticated,
            payload_str=body_str,
            custom_headers=headers,
        )

        url = f"{self._base_url}{path}"
        session = await self._get_session()

        for attempt in range(self._max_retries + 1):
            try:
                async with session.post(
                    url,
                    params=clean_params,
                    data=body_str if data is not None else None,
                    headers=request_headers,
                ) as resp:
                    payload = await self._read_response(resp)
                    return self._validate_response_envelope(payload)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt >= self._max_retries:
                    raise
                _LOGGER.warning(
                    "Bybit POST %s failed (attempt %d/%d): %s",
                    path,
                    attempt + 1,
                    self._max_retries,
                    error,
                )
                await asyncio.sleep(self._retry_delay_seconds * (2**attempt))
            except BybitRestResponseError as error:
                if (
                    attempt >= self._max_retries
                    or error.ret_code not in _RETRYABLE_RET_CODES
                ):
                    raise
                backoff = (
                    max(
                        _RATE_LIMIT_MIN_BACKOFF_SECONDS,
                        self._retry_delay_seconds * (2**attempt),
                    )
                    if error.ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES
                    else self._retry_delay_seconds * (2**attempt)
                )
                _LOGGER.warning(
                    "Bybit POST %s returned retryable error %d (attempt %d/%d), "
                    "backing off %.1fs: %s",
                    path,
                    error.ret_code,
                    attempt + 1,
                    self._max_retries,
                    backoff,
                    error.ret_msg,
                )
                await asyncio.sleep(backoff)

        raise RuntimeError("Unreachable request loop termination")

    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP DELETE request to Bybit V5."""
        clean_params = {k: str(v) for k, v in params.items()} if params else {}
        query_string = urlencode(clean_params) if clean_params else ""
        request_headers = self._prepare_headers(
            authenticated=authenticated,
            payload_str=query_string,
            custom_headers=headers,
        )

        url = f"{self._base_url}{path}"
        session = await self._get_session()

        for attempt in range(self._max_retries + 1):
            try:
                async with session.delete(
                    url,
                    params=clean_params or None,
                    headers=request_headers,
                ) as resp:
                    payload = await self._read_response(resp)
                    return self._validate_response_envelope(payload)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt >= self._max_retries:
                    raise
                _LOGGER.warning(
                    "Bybit DELETE %s failed (attempt %d/%d): %s",
                    path,
                    attempt + 1,
                    self._max_retries,
                    error,
                )
                await asyncio.sleep(self._retry_delay_seconds * (2**attempt))
            except BybitRestResponseError as error:
                if (
                    attempt >= self._max_retries
                    or error.ret_code not in _RETRYABLE_RET_CODES
                ):
                    raise
                backoff = (
                    max(
                        _RATE_LIMIT_MIN_BACKOFF_SECONDS,
                        self._retry_delay_seconds * (2**attempt),
                    )
                    if error.ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES
                    else self._retry_delay_seconds * (2**attempt)
                )
                _LOGGER.warning(
                    "Bybit DELETE %s returned retryable error %d (attempt %d/%d), "
                    "backing off %.1fs: %s",
                    path,
                    error.ret_code,
                    attempt + 1,
                    self._max_retries,
                    backoff,
                    error.ret_msg,
                )
                await asyncio.sleep(backoff)

        raise RuntimeError("Unreachable request loop termination")
