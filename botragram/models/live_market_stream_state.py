"""
Botragram

Description:
    Immutable observational snapshot for one live market stream.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import LiveMarketStreamLifecycleStatus
from botragram.models.live_market_stream_identity import LiveMarketStreamIdentity

__all__ = ["LiveMarketStreamState"]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveMarketStreamState:
    """Expose one stream's state without leaking its mutable owner resources."""

    identity: LiveMarketStreamIdentity
    lifecycle_status: LiveMarketStreamLifecycleStatus
    first_tick_received: bool
    event_count: int
    last_price: Decimal | None
    last_event_monotonic: float | None
    failure_type: str | None = None
