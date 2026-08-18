"""Immutable ordered runtime contexts for a recovered LIVE portfolio."""

from __future__ import annotations

from dataclasses import dataclass

from botragram.models.live_runtime_position_context import LiveRuntimePositionContext

__all__ = ["LiveRuntimePortfolioContext"]


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveRuntimePortfolioContext:
    """Store every recovered runtime context without assigning priority."""

    contexts: tuple[LiveRuntimePositionContext, ...]

    def __post_init__(self) -> None:
        """Reject duplicate production position identities before installation."""
        identities = tuple(context.symbol for context in self.contexts)
        if len(identities) != len(set(identities)):
            raise ValueError("Runtime portfolio contains duplicate position symbols")
