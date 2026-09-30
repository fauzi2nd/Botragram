"""
Botragram

Description:
    Immutable readiness facts for recovered LIVE multi-context activation.

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
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import LiveMarketStreamLifecycleStatus, LivePortfolioRecoveryStatus
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
)

__all__ = [
    "MultiContextActivationPreconditionProvider",
    "MultiContextRunnerActivationPreconditions",
]


class MultiContextActivationPreconditionProvider(Protocol):
    """Build current LIVE multi-context activation state without runner I/O."""

    def get_multi_context_activation_preconditions(
        self,
        *,
        runtime_is_stopping: bool,
    ) -> MultiContextRunnerActivationPreconditions | None:
        """Return current exact multi-context activation state."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class MultiContextRunnerActivationPreconditions:
    """Describe whether a recovered context portfolio can run safely.

    The value object separates verified runtime substrate from authorization.
    It deliberately does not resume a runner or select a primary context.
    """

    portfolio_status: LivePortfolioRecoveryStatus
    contexts: tuple[LiveRuntimePositionContext, ...]
    stream_states: tuple[LiveMarketStreamState, ...]
    monitor_states: tuple[LiveProtectionMonitorState, ...]
    live_management_authorization: LiveRecoveredPositionManagementAuthorization
    runtime_is_paused: bool
    runtime_is_stopping: bool

    @property
    def runtime_representation_valid(self) -> bool:
        """Return whether contexts match their typed recovery outcome."""
        context_count = len(self.contexts)
        return (
            self.portfolio_status is LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
            and context_count == 1
        ) or (
            self.portfolio_status is LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
            and context_count > 1
        )

    @property
    def stream_substrate_ready(self) -> bool:
        """Return whether every context has exactly one ready owned stream."""
        expected_identities = frozenset(
            LiveMarketStreamIdentity.from_runtime_context(context=context)
            for context in self.contexts
        )
        actual_identities = tuple(
            stream_state.identity for stream_state in self.stream_states
        )
        return (
            bool(expected_identities)
            and len(actual_identities) == len(set(actual_identities))
            and frozenset(actual_identities) == expected_identities
            and all(
                stream_state.lifecycle_status is LiveMarketStreamLifecycleStatus.RUNNING
                and stream_state.first_tick_received
                for stream_state in self.stream_states
            )
        )

    @property
    def protection_monitoring_ready(self) -> bool:
        """Return whether every context has one active healthy exact monitor."""
        expected_contexts = frozenset(self.contexts)
        actual_contexts = tuple(
            monitor_state.context for monitor_state in self.monitor_states
        )
        return (
            bool(expected_contexts)
            and len(actual_contexts) == len(set(actual_contexts))
            and frozenset(actual_contexts) == expected_contexts
            and all(
                monitor_state.is_active and monitor_state.failure_type is None
                for monitor_state in self.monitor_states
            )
        )

    @property
    def is_eligible(self) -> bool:
        """Return whether all future runner-activation requirements are met."""
        return (
            self.runtime_representation_valid
            and self.stream_substrate_ready
            and self.protection_monitoring_ready
            and self.live_management_authorization.authorizes_contexts(
                contexts=self.contexts,
            )
            and not self.runtime_is_paused
            and not self.runtime_is_stopping
        )

    @property
    def can_activate(self) -> bool:
        """Return whether readiness and authorization permit a paused activation."""
        return (
            self.runtime_representation_valid
            and self.stream_substrate_ready
            and self.protection_monitoring_ready
            and self.live_management_authorization.authorizes_contexts(
                contexts=self.contexts,
            )
            and not self.runtime_is_stopping
        )
