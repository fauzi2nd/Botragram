"""
Botragram

Description:
    Base REST transport protocol and abstract base class.

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
from abc import ABC, abstractmethod
from collections.abc import Mapping

__all__ = [
    "BaseRestClient",
    "JsonObject",
    "JsonResponse",
    "QueryParams",
    "RequestHeaders",
]


# =============================================================================
# Type Aliases
# =============================================================================
type QueryValue = str | int | float | bool
type QueryParams = Mapping[str, QueryValue]
type RequestHeaders = Mapping[str, str]
type JsonObject = dict[str, object]
type JsonArray = list[object]
type JsonResponse = JsonObject | JsonArray


# =============================================================================
# Abstract Base REST Client
# =============================================================================
class BaseRestClient(ABC):
    """Abstract base class for exchange REST transports."""

    @abstractmethod
    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP GET request and return its parsed JSON payload."""

    @abstractmethod
    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        data: JsonObject | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP POST request and return its parsed JSON payload."""

    @abstractmethod
    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: RequestHeaders | None = None,
        authenticated: bool = False,
    ) -> JsonResponse:
        """Send an HTTP DELETE request and return its parsed JSON payload."""

    @abstractmethod
    async def close(self) -> None:
        """Close the underlying HTTP session."""
