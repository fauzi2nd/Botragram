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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from re import IGNORECASE, Pattern, compile
from threading import Lock
from time import monotonic, time
from typing import Final, TypeIs, cast
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
    "BinanceRateLimitGovernor",
    "BinanceRateLimitSnapshot",
    "BinanceRateLimitWindow",
    "BinanceRestClient",
    "BinanceRestResponseError",
]


# =============================================================================
# Type Aliases
# =============================================================================
type MutableQueryParams = dict[str, str | int | float | bool]
type RateLimitKey = tuple[str, int]


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
_SERVER_TIME_PARAMETER: Final[str] = "serverTime"
_INVALID_SERVER_TIME_ERROR: Final[str] = "Binance server time response is invalid"
_REQUEST_WEIGHT_RATE_LIMIT_TYPE: Final[str] = "REQUEST_WEIGHT"
_ORDER_RATE_LIMIT_TYPE: Final[str] = "ORDERS"
_DEFAULT_REQUEST_WEIGHT_LIMIT: Final[int] = 2_400
_DEFAULT_DISCOVERY_THROTTLE_PERCENT: Final[int] = 75
_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS: Final[float] = 60.0
_SECONDS_PER_MINUTE: Final[int] = 60
_INTERVAL_SECONDS: Final[Mapping[str, int]] = {
    "SECOND": 1,
    "MINUTE": _SECONDS_PER_MINUTE,
    "HOUR": 60 * _SECONDS_PER_MINUTE,
    "DAY": 24 * 60 * _SECONDS_PER_MINUTE,
}
_USAGE_HEADER_PATTERN: Final[Pattern[str]] = compile(
    r"^X-MBX-(USED-WEIGHT|ORDER-COUNT)-(\d+)([SMHD])$",
    IGNORECASE,
)
_HEADER_INTERVAL_SECONDS: Final[Mapping[str, int]] = {
    "S": 1,
    "M": _SECONDS_PER_MINUTE,
    "H": 60 * _SECONDS_PER_MINUTE,
    "D": 24 * 60 * _SECONDS_PER_MINUTE,
}


def _current_timestamp_ms() -> int:
    """Return the current local Unix timestamp in milliseconds."""
    return int(time() * 1_000)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    """Narrow one untrusted JSON value to a runtime-validated object list."""
    return isinstance(value, list)


def _is_object_mapping(value: object) -> TypeIs[Mapping[object, object]]:
    """Narrow one untrusted JSON value to a runtime-validated mapping."""
    return isinstance(value, Mapping)


# =============================================================================
# Binance Rate Limit Governor
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class BinanceRateLimitWindow:
    """Describe one current Binance rate-limit usage window."""

    rate_limit_type: str
    interval_seconds: int
    used: int
    limit: int
    usage_percent: int


@dataclass(slots=True, kw_only=True, frozen=True)
class BinanceRateLimitSnapshot:
    """Expose immutable request-budget telemetry without transport authority."""

    windows: tuple[BinanceRateLimitWindow, ...]
    discovery_throttled: bool
    throttle_reason: str | None
    retry_after_seconds: float
    throttle_percent: int


@dataclass(slots=True, kw_only=True, frozen=True)
class _RateLimitObservation:
    """Retain one process-local vendor usage observation."""

    used: int
    observed_at: float


class BinanceRateLimitGovernor:
    """Track Binance response budgets and gate only optional discovery work."""

    __slots__ = (
        "_blocked_until",
        "_clock",
        "_last_logged_state",
        "_limits",
        "_lock",
        "_observations",
        "_throttle_percent",
    )

    def __init__(
        self,
        *,
        throttle_percent: int = _DEFAULT_DISCOVERY_THROTTLE_PERCENT,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Initialize one process-local rate-limit governor.

        Args:
            throttle_percent: Usage percentage that pauses optional discovery.
            clock: Monotonic clock used for deterministic window expiry.

        Raises:
            ValueError: If the throttle percentage is outside 1 through 100.
        """
        if (
            isinstance(throttle_percent, bool)
            or throttle_percent <= 0
            or throttle_percent > 100
        ):
            raise ValueError("Binance throttle percentage must be within 1..100")

        self._throttle_percent = throttle_percent
        self._clock = clock
        self._lock = Lock()
        self._last_logged_state: tuple[bool, str | None] = (False, None)
        self._blocked_until = 0.0
        self._limits: dict[RateLimitKey, int] = {
            (
                _REQUEST_WEIGHT_RATE_LIMIT_TYPE,
                _SECONDS_PER_MINUTE,
            ): _DEFAULT_REQUEST_WEIGHT_LIMIT,
        }
        self._observations: dict[RateLimitKey, _RateLimitObservation] = {}

    def observe_response(
        self,
        *,
        headers: Mapping[str, str],
        status: int,
        retry_after_seconds: float | None,
    ) -> None:
        """Record safe rate-limit metadata from one Binance response.

        Args:
            headers: Response headers without request credential material.
            status: HTTP response status.
            retry_after_seconds: Parsed non-negative Binance cooldown.
        """
        parsed_observations: list[tuple[RateLimitKey, int]] = []
        for header_name, raw_used in headers.items():
            key = self._parse_usage_header(header_name=header_name)
            used = self._parse_non_negative_integer(raw_used)
            if key is None or used is None:
                continue
            parsed_observations.append((key, used))

        observed_at = self._clock()
        with self._lock:
            for key, used in parsed_observations:
                previous = self._observations.get(key)
                if previous is not None and observed_at - previous.observed_at < key[1]:
                    used = max(used, previous.used)
                self._observations[key] = _RateLimitObservation(
                    used=used,
                    observed_at=observed_at,
                )

            if status in {_HTTP_AUTO_BAN_STATUS, _HTTP_RATE_LIMIT_STATUS}:
                cooldown = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
                )
                self._blocked_until = max(
                    self._blocked_until,
                    observed_at + cooldown,
                )

            snapshot, should_log = self._snapshot_and_log_decision_locked(
                now=observed_at,
            )

        if should_log:
            self._log_budget_transition(snapshot=snapshot)

    def observe_payload(self, *, payload: JsonResponse) -> None:
        """Learn exact Binance limits from an exchange-information payload.

        Args:
            payload: Validated top-level Binance JSON response.
        """
        if not isinstance(payload, Mapping):
            return

        raw_limits = payload.get("rateLimits")
        if not _is_object_list(raw_limits):
            return

        parsed_limits: list[tuple[RateLimitKey, int]] = []
        for raw_limit in raw_limits:
            if not _is_object_mapping(raw_limit):
                continue
            parsed = self._parse_limit(raw_limit=raw_limit)
            if parsed is None:
                continue
            parsed_limits.append(parsed)

        if not parsed_limits:
            return

        now = self._clock()
        with self._lock:
            for key, limit in parsed_limits:
                self._limits[key] = limit
            snapshot, should_log = self._snapshot_and_log_decision_locked(now=now)

        if should_log:
            self._log_budget_transition(snapshot=snapshot)

    def should_throttle_discovery(self) -> bool:
        """Return whether optional discovery must yield to exchange headroom."""
        return self.get_snapshot().discovery_throttled

    def get_snapshot(self) -> BinanceRateLimitSnapshot:
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
    ) -> tuple[BinanceRateLimitSnapshot, bool]:
        """Build one snapshot and atomically reserve a transition log."""
        snapshot = self._get_snapshot_locked(now=now)
        current_state = (
            snapshot.discovery_throttled,
            snapshot.throttle_reason if snapshot.discovery_throttled else None,
        )
        should_log = current_state != self._last_logged_state and (
            snapshot.discovery_throttled or self._last_logged_state[0]
        )
        self._last_logged_state = current_state
        return snapshot, should_log

    def _get_snapshot_locked(self, *, now: float) -> BinanceRateLimitSnapshot:
        """Return current telemetry while the governor lock is held."""
        windows = self._get_active_windows(now=now)
        retry_after_seconds = max(0.0, self._blocked_until - now)

        if retry_after_seconds > 0:
            return BinanceRateLimitSnapshot(
                windows=windows,
                discovery_throttled=True,
                throttle_reason="retry_after",
                retry_after_seconds=retry_after_seconds,
                throttle_percent=self._throttle_percent,
            )

        throttled_window = next(
            (
                window
                for window in windows
                if window.used * 100 >= window.limit * self._throttle_percent
            ),
            None,
        )
        return BinanceRateLimitSnapshot(
            windows=windows,
            discovery_throttled=throttled_window is not None,
            throttle_reason=(
                None
                if throttled_window is None
                else (
                    f"{throttled_window.rate_limit_type}:"
                    f"{throttled_window.interval_seconds}s"
                )
            ),
            retry_after_seconds=0.0,
            throttle_percent=self._throttle_percent,
        )

    @staticmethod
    def _log_budget_transition(*, snapshot: BinanceRateLimitSnapshot) -> None:
        """Log only throttle-state transitions with safe budget context."""
        limiting_window = BinanceRateLimitGovernor._get_limiting_window(
            snapshot=snapshot,
        )
        used: int | str = "N/A"
        limit: int | str = "N/A"
        usage_percent: int | str = "N/A"
        headroom: int | str = "N/A"
        if limiting_window is not None:
            used = limiting_window.used
            limit = limiting_window.limit
            usage_percent = limiting_window.usage_percent
            headroom = max(0, limiting_window.limit - limiting_window.used)

        if snapshot.discovery_throttled:
            _LOGGER.warning(
                "Binance optional discovery and entry throttled: reason=%s "
                "used=%s limit=%s usage_pct=%s threshold_pct=%s headroom=%s "
                "retry_after_seconds=%.3f",
                snapshot.throttle_reason,
                used,
                limit,
                usage_percent,
                snapshot.throttle_percent,
                headroom,
                snapshot.retry_after_seconds,
            )
            return

        _LOGGER.info(
            "Binance optional discovery and entry resumed: used=%s limit=%s "
            "usage_pct=%s threshold_pct=%s headroom=%s",
            used,
            limit,
            usage_percent,
            snapshot.throttle_percent,
            headroom,
        )

    @staticmethod
    def _get_limiting_window(
        *,
        snapshot: BinanceRateLimitSnapshot,
    ) -> BinanceRateLimitWindow | None:
        """Return the most utilized active window for transition logging."""
        return max(
            snapshot.windows,
            key=lambda window: (window.used * 1_000_000) // window.limit,
            default=None,
        )

    def _get_active_windows(
        self,
        *,
        now: float,
    ) -> tuple[BinanceRateLimitWindow, ...]:
        """Build deterministic snapshots for observations not yet expired."""
        windows: list[BinanceRateLimitWindow] = []
        for key, observation in self._observations.items():
            rate_limit_type, interval_seconds = key
            limit = self._limits.get(key)
            if limit is None or now - observation.observed_at >= interval_seconds:
                continue
            windows.append(
                BinanceRateLimitWindow(
                    rate_limit_type=rate_limit_type,
                    interval_seconds=interval_seconds,
                    used=observation.used,
                    limit=limit,
                    usage_percent=(observation.used * 100) // limit,
                )
            )
        return tuple(
            sorted(
                windows,
                key=lambda window: (
                    window.rate_limit_type,
                    window.interval_seconds,
                ),
            )
        )

    @staticmethod
    def _parse_usage_header(*, header_name: str) -> RateLimitKey | None:
        """Map one Binance usage-header name to an internal window key."""
        match = _USAGE_HEADER_PATTERN.fullmatch(header_name)
        if match is None:
            return None

        interval_number = int(match.group(2))
        interval_unit_seconds = _HEADER_INTERVAL_SECONDS.get(match.group(3).upper())
        if interval_number <= 0 or interval_unit_seconds is None:
            return None

        rate_limit_type = (
            _REQUEST_WEIGHT_RATE_LIMIT_TYPE
            if match.group(1).upper() == "USED-WEIGHT"
            else _ORDER_RATE_LIMIT_TYPE
        )
        return rate_limit_type, interval_number * interval_unit_seconds

    @staticmethod
    def _parse_limit(
        *,
        raw_limit: Mapping[object, object],
    ) -> tuple[RateLimitKey, int] | None:
        """Validate one Binance exchange-information rate-limit record."""
        rate_limit_type = raw_limit.get("rateLimitType")
        interval = raw_limit.get("interval")
        interval_number = raw_limit.get("intervalNum")
        limit = raw_limit.get("limit")
        if (
            not isinstance(rate_limit_type, str)
            or rate_limit_type
            not in {_REQUEST_WEIGHT_RATE_LIMIT_TYPE, _ORDER_RATE_LIMIT_TYPE}
            or not isinstance(interval, str)
            or isinstance(interval_number, bool)
            or not isinstance(interval_number, int)
            or interval_number <= 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
        ):
            return None

        interval_unit_seconds = _INTERVAL_SECONDS.get(interval.upper())
        if interval_unit_seconds is None:
            return None
        return (
            rate_limit_type,
            interval_number * interval_unit_seconds,
        ), limit

    @staticmethod
    def _parse_non_negative_integer(raw_value: str) -> int | None:
        """Return a non-negative integer header value when valid."""
        try:
            value = int(raw_value)
        except ValueError:
            return None
        return value if value >= 0 else None


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
        "_clock_ms",
        "_clock_offset_ms",
        "_base_url",
        "_max_retries",
        "_recv_window_ms",
        "_rate_limit_governor",
        "_retry_delay_seconds",
        "_session",
        "_time_sync_lock",
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
        clock_ms: Callable[[], int] = _current_timestamp_ms,
        rate_limit_governor: BinanceRateLimitGovernor | None = None,
    ) -> None:
        """Initialize the Binance REST client.

        Args:
            base_url: Binance REST API base URL.
            api_key: Optional Binance API key.
            api_secret: Optional Binance API secret.
            recv_window_ms: Signed-request acceptance window.
            request_timeout_seconds: Total timeout for one HTTP request.
            max_retries: Maximum attempts for retryable read requests.
            retry_delay_seconds: Base delay for retryable read requests.
            clock_ms: Local millisecond clock used to synchronize signed requests.
            rate_limit_governor: Optional process-local Binance budget tracker.
        """
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
        self._clock_ms = clock_ms
        self._clock_offset_ms = 0
        self._recv_window_ms = recv_window_ms
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._rate_limit_governor = (
            rate_limit_governor
            if rate_limit_governor is not None
            else BinanceRateLimitGovernor()
        )
        self._timeout = aiohttp.ClientTimeout(
            total=request_timeout_seconds,
        )
        self._session: aiohttp.ClientSession | None = None
        self._time_sync_lock = asyncio.Lock()

    @property
    def rate_limit_governor(self) -> BinanceRateLimitGovernor:
        """Return the process-local Binance request-budget governor."""
        return self._rate_limit_governor

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

    async def synchronize_time(self, *, path: str) -> None:
        """Synchronize signed-request timestamps with one Binance server clock.

        Args:
            path: Public Binance server-time endpoint for the selected product.

        Raises:
            RuntimeError: If Binance does not return a valid server timestamp.
            ValueError: If the endpoint path is empty.
        """
        normalized_path = path.strip()
        if not normalized_path:
            raise ValueError("Binance server time path must not be empty")

        async with self._time_sync_lock:
            sent_at_ms = self._local_timestamp_ms()
            payload = await self.get(normalized_path)
            received_at_ms = self._local_timestamp_ms()
            server_time_ms = self._get_server_time_ms(payload=payload)
            midpoint_ms = (sent_at_ms + received_at_ms) // 2
            self._clock_offset_ms = server_time_ms - midpoint_ms

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
                    retry_after_seconds = self._get_retry_after_seconds(
                        response=response,
                    )

                    if response.status >= 400:
                        self._rate_limit_governor.observe_response(
                            headers=response.headers,
                            status=response.status,
                            retry_after_seconds=retry_after_seconds,
                        )
                        raise BinanceRestResponseError(
                            status=response.status,
                            payload=payload,
                            retry_after_seconds=retry_after_seconds,
                            message=self._format_http_error(
                                method=method,
                                url=url,
                                status=response.status,
                                payload=payload,
                            ),
                        )

                    self._rate_limit_governor.observe_payload(payload=payload)
                    self._rate_limit_governor.observe_response(
                        headers=response.headers,
                        status=response.status,
                        retry_after_seconds=retry_after_seconds,
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

    def _timestamp_ms(self) -> int:
        """Return the synchronized Unix timestamp used for signatures."""
        return self._local_timestamp_ms() + self._clock_offset_ms

    def _local_timestamp_ms(self) -> int:
        """Return the local Unix timestamp in milliseconds."""
        return self._clock_ms()

    @staticmethod
    def _get_server_time_ms(*, payload: JsonResponse) -> int:
        """Extract one required positive Binance server timestamp."""
        if not isinstance(payload, Mapping):
            raise RuntimeError(_INVALID_SERVER_TIME_ERROR)

        server_time_ms = payload.get(_SERVER_TIME_PARAMETER)
        if (
            isinstance(server_time_ms, bool)
            or not isinstance(server_time_ms, int)
            or server_time_ms <= 0
        ):
            raise RuntimeError(_INVALID_SERVER_TIME_ERROR)

        return server_time_ms

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
