"""
Botragram

Description:
    Base REST API client with async aiohttp session management.

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
from typing import Any

# =============================================================================
# Third Party
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.exchange import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Base REST Client Class
# =============================================================================
class BaseRestClient:
    """Base REST API client for crypto exchanges using aiohttp."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """Initialize base REST API client.

        Args:
            base_url: Root API endpoint URL.
            api_key: Exchange API key.
            api_secret: Exchange API secret.
            timeout_seconds: HTTP request timeout in seconds.
            max_retries: Maximum retry attempts for failed requests.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._max_retries = max_retries
        self._session: aiohttp.ClientSession | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create an active aiohttp ClientSession.

        Returns:
            Active ClientSession instance.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        """Close active HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("REST client HTTP session closed")

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Execute HTTP request with automatic session management.

        Args:
            method: HTTP method string (GET, POST, etc.).
            endpoint: API path endpoint.
            params: URL query parameters.
            data: Request payload body.
            headers: Custom request headers.

        Returns:
            JSON response payload.
        """
        session = await self.get_session()
        url = f"{self._base_url}{endpoint}"

        for attempt in range(1, self._max_retries + 1):
            try:
                async with session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    return await response.json()
            except Exception as err:
                logger.warning(
                    f"HTTP {method} request attempt {attempt}/{self._max_retries} "
                    f"failed for {url}: {err}"
                )
                if attempt == self._max_retries:
                    raise err
        return {}
