"""
Botragram

Description:
    Sequential autonomous PAPER opportunity execution.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Signal, TradingResult

__all__ = [
    "AutonomousPaperExecutionService",
]


# =============================================================================
# Service Contracts
# =============================================================================
class OpportunityDiscoveryProvider(Protocol):
    """Provide bounded ranked opportunity discovery."""

    async def discover(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[Signal]:
        """Return ranked actionable candidates."""
        ...


class PaperSignalExecutor(Protocol):
    """Execute one signal through the PAPER simulation boundary."""

    async def execute(
        self,
        *,
        signal: Signal,
        initial_balance: Decimal | None = None,
        interval: Interval | None = None,
    ) -> TradingResult:
        """Execute one PAPER signal and return its result."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousPaperExecutionService:
    """Discover and execute ranked candidates through PAPER only."""

    discovery_service: OpportunityDiscoveryProvider
    paper_trading_service: PaperSignalExecutor

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> Sequence[TradingResult]:
        """Discover candidates and execute them sequentially in PAPER.

        No background tasks are created. An error or cancellation from
        discovery or one candidate execution stops the complete cycle and
        propagates to the owning runtime.

        Args:
            quote_asset: Quote asset used to select the discovery universe.
            interval: Candle interval evaluated by the current strategy.
            candle_limit: Historical candles analyzed for each candidate.
            max_symbols: Maximum symbols analyzed during discovery.
            top_n: Maximum ranked actionable candidates to execute.
            initial_balance: Optional PAPER account balance override.

        Returns:
            Results in ranked candidate order. Each candidate is attempted at
            most once during the cycle.
        """
        candidates = await self.discovery_service.discover(
            quote_asset=quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=max_symbols,
            top_n=top_n,
        )
        results: list[TradingResult] = []

        for candidate in candidates:
            results.append(
                await self.paper_trading_service.execute(
                    signal=candidate,
                    initial_balance=initial_balance,
                    interval=interval,
                )
            )

        return tuple(results)
