"""
Botragram

Description:
    Classify transient dependency failures at the application boundary.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Iterator
from errno import (
    ECONNABORTED,
    ECONNREFUSED,
    ECONNRESET,
    EHOSTUNREACH,
    ENETDOWN,
    ENETRESET,
    ENETUNREACH,
    ETIMEDOUT,
)
from socket import gaierror

import aiohttp

from botragram.exchanges.binance.rest import BinanceRestResponseError

__all__ = ["is_transient_connectivity_error"]


_TRANSIENT_HTTP_STATUSES = frozenset({408, 418, 429})
_TRANSIENT_ERRNOS = frozenset(
    {
        ECONNABORTED,
        ECONNREFUSED,
        ECONNRESET,
        EHOSTUNREACH,
        ENETDOWN,
        ENETRESET,
        ENETUNREACH,
        ETIMEDOUT,
    }
)
_TRANSIENT_WINDOWS_ERRORS = frozenset({10051, 10053, 10054, 10060, 11001, 11002})


def is_transient_connectivity_error(error: BaseException) -> bool:
    """Return whether an exception chain represents temporary connectivity loss."""
    return any(_is_transient_exception(item) for item in _walk_exception_chain(error))


def _is_transient_exception(error: BaseException) -> bool:
    """Classify one exception without relying on unstable message text."""
    if isinstance(error, BinanceRestResponseError):
        return error.status in _TRANSIENT_HTTP_STATUSES or error.status >= 500
    if isinstance(error, aiohttp.ClientResponseError):
        return error.status in _TRANSIENT_HTTP_STATUSES or error.status >= 500
    if isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            gaierror,
            aiohttp.ClientConnectionError,
            aiohttp.ClientPayloadError,
        ),
    ):
        return True
    if isinstance(error, OSError):
        return (
            error.errno in _TRANSIENT_ERRNOS
            or getattr(error, "winerror", None) in _TRANSIENT_WINDOWS_ERRORS
        )
    return False


def _walk_exception_chain(error: BaseException) -> Iterator[BaseException]:
    """Yield nested and chained exceptions once in deterministic depth-first order."""
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        yield current

        if current.__context__ is not None:
            pending.append(current.__context__)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
