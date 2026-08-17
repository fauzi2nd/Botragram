"""
Botragram

Description:
    Immutable human execution-authorization domain models.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from botragram.enums import AuthorizationStatus
from botragram.models.signal import Signal
from botragram.models.trading import TradingResult

__all__ = ["ExecutionAuthorization", "ExecutionAuthorizationOutcome"]


@dataclass(slots=True, kw_only=True, frozen=True)
class ExecutionAuthorization:
    """One exact signal awaiting or recording human authorization."""

    authorization_id: str
    signal: Signal
    status: AuthorizationStatus
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Validate immutable authorization identity and lifetime invariants."""
        if not self.authorization_id.strip():
            raise ValueError("Execution authorization identifier must not be empty")

        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError(
                "Execution authorization timestamps must be timezone aware"
            )

        if self.expires_at <= self.created_at:
            raise ValueError("Execution authorization expiration must be in the future")


@dataclass(slots=True, kw_only=True, frozen=True)
class ExecutionAuthorizationOutcome:
    """Immutable result of approving or rejecting an authorization."""

    authorization: ExecutionAuthorization | None
    trading_result: TradingResult | None
    reason: str = ""
