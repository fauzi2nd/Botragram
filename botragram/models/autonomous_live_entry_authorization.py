"""
Botragram

Description:
    Immutable TESTNET-only authorization for future autonomous LIVE entry.

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
from botragram.enums import ExchangeEnvironment

__all__ = ["AutonomousLiveEntryAuthorization"]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousLiveEntryAuthorization:
    """Represent explicit future autonomous new-LIVE-entry permission.

    This capability is intentionally independent from recovered-position
    management authorization. It is configuration-derived and never persisted.
    """

    environment: ExchangeEnvironment
    explicit_opt_in: bool

    def __post_init__(self) -> None:
        """Reject unsafe or implicit autonomous LIVE entry authorization."""
        if self.environment is not ExchangeEnvironment.TESTNET:
            raise ValueError("Autonomous LIVE entry authorization requires TESTNET")

        if not self.explicit_opt_in:
            raise ValueError("Autonomous LIVE entry authorization requires opt-in")

    @property
    def new_live_entry_allowed(self) -> bool:
        """Return the capability semantic for future execution boundaries."""
        return True
