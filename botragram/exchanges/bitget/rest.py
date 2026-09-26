"""
Botragram

Description:
    Bitget V2 REST transport client.

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
import base64
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
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RETRY_DELAY_SECONDS,
)
from botragram.exceptions.exchange import (
    ExchangeAuthenticationError,
    ExchangeResponseError,
)
from botragram.exchanges.base.rest import (
    BaseRestClient,
    JsonObject,
    JsonResponse,
    QueryParams,
    RequestHeaders,
)

__all__ = [
    "BitgetRestClient",
    "BitgetRestResponseError",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_HEADER_API_KEY: Final[str] = "ACCESS-KEY"
_HEADER_SIGNATURE: Final[str] = "ACCESS-SIGN"
_HEADER_TIMESTAMP: Final[str] = "ACCESS-TIMESTAMP"
_HEADER_PASSPHRASE: Final[str] = "ACCESS-PASSPHRASE"

_RET_CODE_OK: Final[str] = "00000"
_RET_CODE_TIMESTAMP_EXPIRED: Final[str] = "40008"
_SERVER_TIME_PATH: Final[str] = "/api/v2/public/time"
_RETRYABLE_RET_CODES: Final[frozenset[str]] = frozenset(
    {"40014", "40015", "429", "40004"}
)


# =============================================================================
# Exceptions
# =============================================================================
class BitgetRestResponseError(ExchangeResponseError):
    """Exception raised when Bitget returns a non-zero response code."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        request_path: str = "",
        http_status: int = 200,
    ) -> None:
        super().__init__(
            f"Bitget REST API error {code}: message={message} "
            f"request_path={request_path} status={http_status}"
        )
        self.code = code
        self.message = message
        self.request_path = request_path
        self.http_status = http_status


# =============================================================================
# Bitget REST Transport Client
# =============================================================================
class BitgetRestClient(BaseRestClient):
    """Bitget V2 REST transport implementation."""

    __slots__ = (
        "_api_key",
        "_api_secret",
        "_base_url",
        "_max_retries",
        "_passphrase",
        "_retry_delay_seconds",
        "_server_time_offset_ms",
        "_session",
        "_timeout",
    )

    def __init__(
        self,
        *,
        base_url: str = "https://api.bitget.com",
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        self._passphrase = passphrase.strip()
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._server_time_offset_ms: int = 0
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        """Return base URL."""
        return self._base_url

    @property
    def has_credentials(self) -> bool:
        """Return whether complete API credentials are provided."""
        return bool(self._api_key and self._api_secret and self._passphrase)

    @property
    def server_time_offset_ms(self) -> int:
        """Return the synchronized clock offset in milliseconds."""
        return self._server_time_offset_ms

    def _current_timestamp_ms(self) -> int:
        """Return local time adjusted by the synchronized server offset."""
        return int(time() * 1000) + self._server_time_offset_ms

    async def synchronize_time(self, *, path: str = _SERVER_TIME_PATH) -> int:
        """Synchronize client time offset with Bitget server time."""
        response = await self.get(path=path, authenticated=False)
        if not isinstance(response, dict):
            raise ValueError("Bitget server time response is not a valid JSON object")

        server_time_ms: int | None = None
        raw_data = response.get("data")
        if isinstance(raw_data, dict):
            data_dict = cast(JsonObject, raw_data)
            raw_time = data_dict.get("serverTime")
            if isinstance(raw_time, (int, float, str)):
                server_time_ms = int(raw_time)
        if server_time_ms is None:
            raw_request_time = response.get("requestTime")
            if isinstance(raw_request_time, (int, float, str)):
                server_time_ms = int(raw_request_time)

        if server_time_ms is None:
            raise ValueError("Bitget server time could not be parsed from response")

        local_time_ms = int(time() * 1000)
        self._server_time_offset_ms = server_time_ms - local_time_ms
        _LOGGER.debug(
            "Bitget server time offset synchronized: %d ms",
            self._server_time_offset_ms,
        )
        return self._server_time_offset_ms

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP GET request to Bitget."""
        return await self._request(
            method="GET",
            path=path,
            params=params,
            headers=headers,
            authenticated=authenticated,
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
        """Send an HTTP POST request to Bitget."""
        return await self._request(
            method="POST",
            path=path,
            params=params,
            data=data,
            headers=headers,
            authenticated=authenticated,
        )

    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP DELETE request to Bitget."""
        return await self._request(
            method="DELETE",
            path=path,
            params=params,
            headers=headers,
            authenticated=authenticated,
        )

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or initialize the aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def _prepare_headers(
        self,
        *,
        authenticated: bool,
        method: str,
        path: str,
        query_string: str = "",
        body: str = "",
        payload_str: str = "",
        custom_headers: RequestHeaders | None = None,
    ) -> dict[str, str]:
        """Build request headers, optionally injecting Bitget V2 auth."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        if custom_headers:
            headers.update(custom_headers)

        if authenticated:
            if not self.has_credentials:
                raise ExchangeAuthenticationError(
                    "Bitget credentials are required "
                    f"(api_key, api_secret, passphrase) for {path}"
                )

            timestamp = str(self._current_timestamp_ms())
            effective_body = body or payload_str
            signature = self._generate_signature(
                timestamp=timestamp,
                method=method,
                request_path=path,
                query_string=query_string,
                body=effective_body,
            )
            headers[_HEADER_API_KEY] = self._api_key
            headers[_HEADER_SIGNATURE] = signature
            headers[_HEADER_TIMESTAMP] = timestamp
            headers[_HEADER_PASSPHRASE] = self._passphrase

        return headers

    @staticmethod
    def _validate_response_envelope(
        payload: JsonResponse,
        *,
        request_path: str = "",
        http_status: int = 200,
    ) -> JsonResponse:
        """Validate Bitget V2 response envelope and return payload."""
        if not isinstance(payload, dict):
            return payload

        raw_code = payload.get("code")
        code = str(raw_code) if raw_code is not None else ""
        if code != _RET_CODE_OK and code != "":
            raw_msg = payload.get("msg")
            msg = str(raw_msg) if raw_msg is not None else ""
            raise BitgetRestResponseError(
                code=code,
                message=msg,
                request_path=request_path,
                http_status=http_status,
            )

        return payload

    async def _request(
        self,
        *,
        method: str,
        path: str,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Execute a Bitget REST request with bounded retries."""
        endpoint_path = path if path.startswith("/") else f"/{path}"
        url = f"{self._base_url}{endpoint_path}"
        query_string = self._encode_params(params)
        body_string = json.dumps(data, separators=(",", ":")) if data else ""

        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            request_headers = self._prepare_headers(
                authenticated=authenticated,
                method=method,
                path=endpoint_path,
                query_string=query_string,
                body=body_string,
                custom_headers=headers,
            )
            try:
                request_url = (
                    f"{url}?{query_string}"
                    if (query_string and method in ("GET", "DELETE"))
                    else url
                )
                req_data = body_string if method in ("POST", "PUT") else None

                async with session.request(
                    method=method,
                    url=request_url,
                    data=req_data,
                    headers=request_headers,
                ) as response:
                    raw_text = await response.text()
                    try:
                        payload = json.loads(raw_text)
                    except json.JSONDecodeError as json_err:
                        raise BitgetRestResponseError(
                            code="PARSE_ERROR",
                            message=f"Invalid JSON response: {raw_text[:200]}",
                            request_path=endpoint_path,
                            http_status=response.status,
                        ) from json_err

                    try:
                        return self._validate_response_envelope(
                            cast(JsonResponse, payload),
                            request_path=endpoint_path,
                            http_status=response.status,
                        )
                    except BitgetRestResponseError as err:
                        if (
                            err.code == _RET_CODE_TIMESTAMP_EXPIRED
                            and attempt < self._max_retries
                        ):
                            _LOGGER.warning(
                                "Bitget timestamp expired (40008); "
                                "resynchronizing server clock..."
                            )
                            try:
                                await self.synchronize_time()
                            except Exception as sync_err:
                                _LOGGER.warning(
                                    "Failed to resync Bitget server time: %s",
                                    sync_err,
                                )
                            await asyncio.sleep(self._retry_delay_seconds)
                            continue
                        if (
                            err.code in _RETRYABLE_RET_CODES
                            and attempt < self._max_retries
                        ):
                            await asyncio.sleep(
                                self._retry_delay_seconds * (2**attempt)
                            )
                            continue
                        raise

            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ) as transport_error:
                last_error = transport_error
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay_seconds * (2**attempt))
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Request failed without error for {path}")

    def _generate_signature(
        self,
        *,
        timestamp: str,
        method: str,
        request_path: str,
        query_string: str = "",
        body: str = "",
    ) -> str:
        """Create HMAC-SHA256 signature encoded as base64."""
        message = timestamp + method.upper() + request_path
        if query_string:
            message += f"?{query_string}"
        if body:
            message += body
        mac = hmac.new(
            self._api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    @staticmethod
    def _encode_params(params: QueryParams | None) -> str:
        """Encode query parameters into URL string."""
        if not params:
            return ""
        return urlencode([(k, str(v)) for k, v in params.items()])
