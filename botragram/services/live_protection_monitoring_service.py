"""
Botragram

Description:
    Independent runtime ownership for per-position protection monitoring.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import (
    LiveProtectionMonitorState,
    LiveRuntimePositionContext,
    Ticker,
)

__all__ = [
    "LiveProtectionMonitoringService",
    "PositionProtectionTickHandler",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Protocols
# =============================================================================
class PositionProtectionTickHandler(Protocol):
    """Advance protection for one position without owning market streams."""

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Process one ticker routed to this position's monitor."""
        ...


# =============================================================================
# Internal Models
# =============================================================================
@dataclass(slots=True)
class _OwnedProtectionMonitor:
    """Keep one manager instance and its sticky failure state private."""

    context: LiveRuntimePositionContext
    manager: PositionProtectionTickHandler
    failure_type: str | None = None


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class LiveProtectionMonitoringService:
    """Own 0/1/N independent per-symbol protection-monitoring contexts."""

    manager_factory: Callable[
        [LiveRuntimePositionContext], PositionProtectionTickHandler
    ]
    _monitors: dict[str, _OwnedProtectionMonitor] = field(
        default_factory=dict[str, _OwnedProtectionMonitor],
        init=False,
        repr=False,
    )

    @property
    def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
        """Return immutable monitoring state in deterministic symbol order."""
        return tuple(
            LiveProtectionMonitorState(
                context=owned_monitor.context,
                is_active=True,
                failure_type=owned_monitor.failure_type,
            )
            for _, owned_monitor in self._ordered_monitors()
        )

    def register(self, *, context: LiveRuntimePositionContext) -> bool:
        """Register one manager context unless its normalized symbol is owned.

        Args:
            context: Immutable runtime context for one recovered live position.

        Returns:
            Whether a new manager instance was registered. Duplicate symbols are
            intentionally idempotent and retain the original context/manager.
        """
        symbol = context.symbol

        if symbol in self._monitors:
            return False

        self._monitors[symbol] = _OwnedProtectionMonitor(
            context=context,
            manager=self.manager_factory(context),
        )
        return True

    def stop(self, *, symbol: str) -> bool:
        """Stop one runtime monitor without mutating durable exchange protection.

        Args:
            symbol: The position symbol whose monitor should be removed.

        Returns:
            Whether an owned monitor was removed.
        """
        return self._monitors.pop(self._normalize_symbol(symbol), None) is not None

    def stop_all(self) -> None:
        """Remove every runtime monitor in deterministic symbol order."""
        for symbol, _ in self._ordered_monitors():
            del self._monitors[symbol]

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Route a ticker only to its matching position protection monitor.

        Args:
            ticker: The normalized ticker received from one market stream.

        Raises:
            asyncio.CancelledError: If lifecycle cancellation is requested.
        """
        symbol = self._normalize_symbol(ticker.symbol)
        owned_monitor = self._monitors.get(symbol)

        if owned_monitor is None:
            return

        if owned_monitor.failure_type is not None:
            return

        try:
            await owned_monitor.manager.on_market_tick(ticker=ticker)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            owned_monitor.failure_type = type(error).__name__
            _LOGGER.exception(
                "Live protection monitor failed: symbol=%s manager=%s",
                symbol,
                type(owned_monitor.manager).__name__,
            )
        # A manager failure is intentionally sticky until runtime recovery
        # releases this owner and registers a fresh manager. Failed ownership is
        # quarantined above, so no later tick can re-enter an untrusted manager.

    def _ordered_monitors(
        self,
    ) -> tuple[tuple[str, _OwnedProtectionMonitor], ...]:
        """Return private monitor ownership in deterministic symbol order."""
        return tuple(sorted(self._monitors.items()))

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize and validate one protection-monitor identity."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Protection monitor symbol must not be empty")

        return normalized_symbol
