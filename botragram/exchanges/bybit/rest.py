"""
Botragram

Description:
    Explicit placeholder for the unavailable Bybit REST transport.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base.rest import (
    BaseRestClient,
    JsonObject,
    JsonResponse,
    QueryParams,
    RequestHeaders,
)

__all__ = [
    "BybitRestClient",
]


# =============================================================================
# Constants
# =============================================================================
_NOT_IMPLEMENTED_ERROR = "Bybit REST transport is not implemented"


# =============================================================================
# Bybit REST Client
# =============================================================================
class BybitRestClient(BaseRestClient):
    """Represent the reserved Bybit transport integration point."""

    __slots__ = ()

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Reject GET requests until the Bybit transport is implemented."""
        del path, params, headers, authenticated
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Reject POST requests until the Bybit transport is implemented."""
        del path, params, data, headers, authenticated
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Reject DELETE requests until the Bybit transport is implemented."""
        del path, params, headers, authenticated
        raise NotImplementedError(_NOT_IMPLEMENTED_ERROR)

    async def close(self) -> None:
        """Close the placeholder transport without side effects."""
