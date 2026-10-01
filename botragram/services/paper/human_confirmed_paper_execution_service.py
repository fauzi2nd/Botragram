"""
Botragram

Description:
    Bounded discovery orchestration for human-confirmed PAPER opportunities.

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
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import ExecutionAuthorization, Signal

__all__ = ["HumanConfirmedPaperExecutionService"]


# =============================================================================
# Service Contracts
# =============================================================================
class OpportunityDiscoveryProvider(Protocol):
    """Provide bounded, deterministically ranked opportunities."""

    async def discover(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[Signal]:
        """Return actionable candidates in deterministic rank order."""
        ...


class ExecutionAuthorizationPreparer(Protocol):
    """Prepare bounded human approvals without executing their signals."""

    async def prepare_if_no_equivalent_pending(
        self,
        *,
        signal: Signal,
    ) -> ExecutionAuthorization | None:
        """Create and publish one non-duplicate pending authorization."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class HumanConfirmedPaperExecutionService:
    """Turn ranked discovery results into pending PAPER authorizations only."""

    discovery_service: OpportunityDiscoveryProvider
    authorization_service: ExecutionAuthorizationPreparer

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[ExecutionAuthorization]:
        """Discover and prepare bounded opportunities without PAPER execution.

        Args:
            quote_asset: Quote asset selecting the active market universe.
            interval: Candle interval evaluated by the configured strategy.
            candle_limit: Historical candles evaluated per market.
            max_symbols: Maximum normalized symbols analyzed by discovery.
            top_n: Maximum ranked candidates considered for confirmation.

        Returns:
            Newly prepared authorizations in the established rank order. Existing
            equivalent pending authorizations are omitted to prevent repeats.

        Raises:
            Exception: Propagates discovery or authorization persistence failure.
            asyncio.CancelledError: Propagates immediately to the owning runtime.
        """
        candidates = await self.discovery_service.discover(
            quote_asset=quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=max_symbols,
            top_n=top_n,
        )
        authorizations: list[ExecutionAuthorization] = []

        for candidate in candidates:
            authorization = (
                await self.authorization_service.prepare_if_no_equivalent_pending(
                    signal=candidate,
                )
            )
            if authorization is not None:
                authorizations.append(authorization)

        return tuple(authorizations)
