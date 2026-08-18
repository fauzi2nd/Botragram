"""
Botragram

Description:
    Immutable capability for managing a recovered LIVE position portfolio.

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
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models.live_runtime_portfolio_context import (
    LiveRuntimePortfolioContext,
)
from botragram.models.live_runtime_position_context import LiveRuntimePositionContext

__all__ = [
    "LiveRecoveredPositionManagementAuthorization",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveRecoveredPositionManagementAuthorization:
    """Authorize management of an exact recovered LIVE context portfolio.

    New LIVE exposure is deliberately unavailable in this phase. The context
    tuple binds management permission to the exact positions proven by recovery.
    """

    contexts: tuple[LiveRuntimePositionContext, ...]
    runtime_management_allowed: bool = False
    new_live_entry_allowed: bool = False

    def __post_init__(self) -> None:
        """Validate a non-empty unique recovered portfolio and deny new entry."""
        portfolio = LiveRuntimePortfolioContext(contexts=tuple(self.contexts))

        if self.runtime_management_allowed and not portfolio.contexts:
            raise ValueError(
                "Recovered LIVE management authorization requires runtime contexts"
            )

        if self.new_live_entry_allowed:
            raise ValueError("New LIVE entry authorization is not supported")

        object.__setattr__(self, "contexts", portfolio.contexts)

    def authorizes_context(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> bool:
        """Return whether this exact recovered context may be managed.

        Args:
            context: The runtime context about to enter a management cycle.

        Returns:
            Whether management is enabled for the exact context.
        """
        return self.runtime_management_allowed and context in self.contexts

    def authorizes_contexts(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> bool:
        """Return whether this exact ordered portfolio may be managed.

        Args:
            contexts: Canonical recovered contexts held by runtime control.

        Returns:
            Whether management is enabled for this exact portfolio snapshot.
        """
        return self.runtime_management_allowed and contexts == self.contexts
