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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from time import monotonic, time
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
    "BybitRateLimitGovernor",
    "BybitRateLimitSnapshot",
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

_HEADER_LIMIT: Final[str] = "x-bapi-limit"
_HEADER_LIMIT_STATUS: Final[str] = "x-bapi-limit-status"
_HEADER_LIMIT_RESET: Final[str] = "x-bapi-limit-reset-timestamp"

_RET_CODE_OK: Final[int] = 0
_SERVER_TIME_PATH: Final[str] = "/v5/market/time"
_RETRYABLE_RATE_LIMIT_RET_CODES: Final[frozenset[int]] = frozenset({10006, 10018})
_RETRYABLE_SERVER_RET_CODES: Final[frozenset[int]] = frozenset({10000, 10016})
_RETRYABLE_RET_CODES: Final[frozenset[int]] = (
    _RETRYABLE_RATE_LIMIT_RET_CODES | _RETRYABLE_SERVER_RET_CODES
)
_RATE_LIMIT_MIN_BACKOFF_SECONDS: Final[float] = 1.5
_DEFAULT_DISCOVERY_THROTTLE_PERCENT: Final[int] = 80
_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS: Final[float] = 2.0


# =============================================================================
# Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class BybitRateLimitSnapshot:
    """Telemetry snapshot representing current Bybit REST rate limit status."""

    discovery_throttled: bool
    throttle_reason: str | None = None
    retry_after_seconds: float = 0.0
    remaining: int | None = None
    limit: int | None = None
    throttle_percent: int = _DEFAULT_DISCOVERY_THROTTLE_PERCENT


# =============================================================================
# Governor
# =============================================================================
class BybitRateLimitGovernor:
    """Track Bybit response budgets and gate only optional discovery work."""

    __slots__ = (
        "_blocked_until",
        "_clock",
        "_last_logged_state",
        "_limit",
        "_lock",
        "_remaining",
        "_reset_timestamp_ms",
        "_throttle_percent",
    )

    def __init__(
        self,
        *,
        throttle_percent: int = _DEFAULT_DISCOVERY_THROTTLE_PERCENT,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Initialize the Bybit rate-limit governor."""
        if (
            isinstance(throttle_percent, bool)
            or throttle_percent <= 0
            or throttle_percent > 100
        ):
            raise ValueError("Bybit throttle percentage must be within 1..100")

        self._throttle_percent = throttle_percent
        self._clock = clock
        self._lock = Lock()
        self._last_logged_state: tuple[bool, str | None] = (False, None)
        self._blocked_until = 0.0
        self._limit: int | None = None
        self._remaining: int | None = None
        self._reset_timestamp_ms: int | None = None

    def observe_response(
        self,
        *,
        headers: Mapping[str, str],
        status: int,
        ret_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Record rate-limit metadata from one Bybit HTTP response."""
        parsed_limit: int | None = None
        parsed_remaining: int | None = None
        parsed_reset_ms: int | None = None

        for k, v in headers.items():
            k_lower = k.lower()
            if k_lower == _HEADER_LIMIT_STATUS:
                try:
                    parsed_remaining = max(0, int(v))
                except ValueError, TypeError:
                    pass
            elif k_lower == _HEADER_LIMIT:
                try:
                    parsed_limit = max(0, int(v))
                except ValueError, TypeError:
                    pass
            elif k_lower == _HEADER_LIMIT_RESET:
                try:
                    parsed_reset_ms = int(v)
                except ValueError, TypeError:
                    pass

        now = self._clock()
        with self._lock:
            if parsed_limit is not None:
                self._limit = parsed_limit
            if parsed_remaining is not None:
                self._remaining = parsed_remaining
            if parsed_reset_ms is not None:
                self._reset_timestamp_ms = parsed_reset_ms

            if status == 429 or (
                ret_code is not None and ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES
            ):
                cooldown = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
                )
                self._blocked_until = max(self._blocked_until, now + cooldown)

            snapshot, should_log = self._snapshot_and_log_decision_locked(now=now)

        if should_log:
            self._log_budget_transition(snapshot=snapshot)

    def should_throttle_discovery(self) -> bool:
        """Return whether optional discovery must yield to exchange headroom."""
        return self.get_snapshot().discovery_throttled

    def get_snapshot(self) -> BybitRateLimitSnapshot:
        """Return current immutable request-budget telemetry."""
        now = self._clock()
        with self._lock:
            snapshot, should_log = self._snapshot_and_log_decision_locked(now=now)

        if should_log:
            self._log_budget_transition(snapshot=snapshot)
        return snapshot

    def _snapshot_and_log_decision_locked(
        self,
        *,
        now: float,
    ) -> tuple[BybitRateLimitSnapshot, bool]:
        """Build one snapshot and atomically reserve a transition log."""
        retry_after_seconds = max(0.0, self._blocked_until - now)
        if retry_after_seconds > 0:
            snapshot = BybitRateLimitSnapshot(
                discovery_throttled=True,
                throttle_reason="retry_after",
                retry_after_seconds=retry_after_seconds,
                remaining=self._remaining,
                limit=self._limit,
                throttle_percent=self._throttle_percent,
            )
        elif (
            self._limit is not None
            and self._limit > 0
            and self._remaining is not None
            and (
                (self._limit - self._remaining) * 100
                >= self._limit * self._throttle_percent
                or self._remaining <= 1
            )
        ):
            snapshot = BybitRateLimitSnapshot(
                discovery_throttled=True,
                throttle_reason=f"headroom_{self._remaining}_of_{self._limit}",
                retry_after_seconds=0.0,
                remaining=self._remaining,
                limit=self._limit,
                throttle_percent=self._throttle_percent,
            )
        else:
            snapshot = BybitRateLimitSnapshot(
                discovery_throttled=False,
                throttle_reason=None,
                retry_after_seconds=0.0,
                remaining=self._remaining,
                limit=self._limit,
                throttle_percent=self._throttle_percent,
            )

        current_state = (
            snapshot.discovery_throttled,
            snapshot.throttle_reason if snapshot.discovery_throttled else None,
        )
        should_log = current_state != self._last_logged_state and (
            snapshot.discovery_throttled or self._last_logged_state[0]
        )
        self._last_logged_state = current_state
        return snapshot, should_log

    def _log_budget_transition(self, *, snapshot: BybitRateLimitSnapshot) -> None:
        """Log entering or leaving a throttled state."""
        if snapshot.discovery_throttled:
            _LOGGER.warning(
                "Bybit optional discovery paused for headroom: reason=%s "
                "cooldown=%.1fs remaining=%s/%s",
                snapshot.throttle_reason,
                snapshot.retry_after_seconds,
                snapshot.remaining,
                snapshot.limit,
            )
        else:
            _LOGGER.info(
                "Bybit optional discovery resumed: remaining=%s/%s",
                snapshot.remaining,
                snapshot.limit,
            )


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
        "_rate_limit_governor",
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
        rate_limit_governor: BybitRateLimitGovernor | None = None,
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
        self._rate_limit_governor = (
            rate_limit_governor
            if rate_limit_governor is not None
            else BybitRateLimitGovernor()
        )

    @property
    def rate_limit_governor(self) -> BybitRateLimitGovernor:
        """Return the rate-limit governor gating optional exchange work."""
        return self._rate_limit_governor

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
        url = f"{self._base_url}{path}"
        session = await self._get_session()

        for attempt in range(self._max_retries + 1):
            request_headers = self._prepare_headers(
                authenticated=authenticated,
                payload_str=query_string,
                custom_headers=headers,
            )
            try:
                async with session.get(
                    url,
                    params=clean_params or None,
                    headers=request_headers,
                ) as resp:
                    self._rate_limit_governor.observe_response(
                        headers=resp.headers,
                        status=resp.status,
                    )
                    payload = await self._read_response(resp)
                    return self._validate_response_envelope(payload)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt >= self._max_retries:
                    raise
                if attempt == 0:
                    _LOGGER.debug(
                        "Bybit GET %s transient failure (attempt 1/%d), retrying: %s",
                        path,
                        self._max_retries,
                        error,
                    )
                else:
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
                if error.ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES:
                    self._rate_limit_governor.observe_response(
                        headers={},
                        status=429,
                        ret_code=error.ret_code,
                        retry_after_seconds=backoff,
                    )
                if attempt == 0:
                    _LOGGER.debug(
                        "Bybit GET %s returned retryable error %d (attempt 1/%d), "
                        "backing off %.1fs: %s",
                        path,
                        error.ret_code,
                        self._max_retries,
                        backoff,
                        error.ret_msg,
                    )
                else:
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
        url = f"{self._base_url}{path}"
        session = await self._get_session()

        for attempt in range(self._max_retries + 1):
            request_headers = self._prepare_headers(
                authenticated=authenticated,
                payload_str=body_str,
                custom_headers=headers,
            )
            try:
                async with session.post(
                    url,
                    params=clean_params,
                    data=body_str if data is not None else None,
                    headers=request_headers,
                ) as resp:
                    self._rate_limit_governor.observe_response(
                        headers=resp.headers,
                        status=resp.status,
                    )
                    payload = await self._read_response(resp)
                    return self._validate_response_envelope(payload)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt >= self._max_retries:
                    raise
                if attempt == 0:
                    _LOGGER.debug(
                        "Bybit POST %s transient failure (attempt 1/%d), retrying: %s",
                        path,
                        self._max_retries,
                        error,
                    )
                else:
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
                if error.ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES:
                    self._rate_limit_governor.observe_response(
                        headers={},
                        status=429,
                        ret_code=error.ret_code,
                        retry_after_seconds=backoff,
                    )
                if attempt == 0:
                    _LOGGER.debug(
                        "Bybit POST %s returned retryable error %d (attempt 1/%d), "
                        "backing off %.1fs: %s",
                        path,
                        error.ret_code,
                        self._max_retries,
                        backoff,
                        error.ret_msg,
                    )
                else:
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
        url = f"{self._base_url}{path}"
        session = await self._get_session()

        for attempt in range(self._max_retries + 1):
            request_headers = self._prepare_headers(
                authenticated=authenticated,
                payload_str=query_string,
                custom_headers=headers,
            )
            try:
                async with session.delete(
                    url,
                    params=clean_params or None,
                    headers=request_headers,
                ) as resp:
                    self._rate_limit_governor.observe_response(
                        headers=resp.headers,
                        status=resp.status,
                    )
                    payload = await self._read_response(resp)
                    return self._validate_response_envelope(payload)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt >= self._max_retries:
                    raise
                if attempt == 0:
                    _LOGGER.debug(
                        "Bybit DELETE %s transient failure (attempt 1/%d), "
                        "retrying: %s",
                        path,
                        self._max_retries,
                        error,
                    )
                else:
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
                if error.ret_code in _RETRYABLE_RATE_LIMIT_RET_CODES:
                    self._rate_limit_governor.observe_response(
                        headers={},
                        status=429,
                        ret_code=error.ret_code,
                        retry_after_seconds=backoff,
                    )
                if attempt == 0:
                    _LOGGER.debug(
                        "Bybit DELETE %s returned retryable error %d (attempt 1/%d), "
                        "backing off %.1fs: %s",
                        path,
                        error.ret_code,
                        self._max_retries,
                        backoff,
                        error.ret_msg,
                    )
                else:
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
