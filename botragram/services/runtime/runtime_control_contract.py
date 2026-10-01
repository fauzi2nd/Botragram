"""
Botragram

Description:
    Service-facing contract for the application-owned trading runtime control.

Python:
    3.14+
"""

from __future__ import annotations

from typing import Protocol

from botragram.enums import Interval, StrategyType
from botragram.models import (
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
)

__all__ = ["LivePortfolioRecoveryRuntime", "PositionProtectionGate", "RuntimeControl"]


class _StreamTelemetry(Protocol):
    """Expose only the first-tick fact needed during recovery."""

    @property
    def event_count(self) -> int:
        """Return the count of validated market ticks."""
        ...


class PositionProtectionGate(Protocol):
    """Expose only the LIVE protection gate used by entry and recovery."""

    def set_position_protection_ready(self, ready: bool) -> bool:
        """Set the LIVE protection gate."""
        ...


class LivePortfolioRecoveryRuntime(PositionProtectionGate, Protocol):
    """Expose active strategy defaults for adopting external LIVE positions."""

    @property
    def interval(self) -> Interval:
        """Return the configured runtime interval."""
        ...

    @property
    def configured_strategy_type(self) -> StrategyType:
        """Return the configured strategy independent of position contexts."""
        ...


class RuntimeControl(LivePortfolioRecoveryRuntime, Protocol):
    """Expose runtime safety state without binding services to app wiring."""

    @property
    def runtime_contexts(self) -> tuple[LiveRuntimePositionContext, ...]:
        """Return the recovered portfolio contexts."""
        ...

    @property
    def live_management_authorization(
        self,
    ) -> LiveRecoveredPositionManagementAuthorization | None:
        """Return the process-local management authorization."""
        ...

    @property
    def reconciliation_required_context(self) -> LiveRuntimePositionContext | None:
        """Return the context requiring reconciliation, if any."""
        ...

    @property
    def is_paused(self) -> bool:
        """Return whether future trading cycles are paused."""
        ...

    @property
    def is_position_protection_ready(self) -> bool:
        """Return whether LIVE position protection is verified."""
        ...

    @property
    def operator_exit_in_progress(self) -> bool:
        """Return whether an operator exit owns the mutation boundary."""
        ...

    @property
    def cycle_in_progress(self) -> bool:
        """Return whether a trading cycle is in progress."""
        ...

    def pause(self) -> bool:
        """Pause future trading cycles."""
        ...

    def resume(self) -> bool:
        """Resume an authorized runtime."""
        ...

    def resume_global_cycle(self) -> bool:
        """Resume an authorized global discovery cycle."""
        ...

    def begin_operator_exit(self) -> None:
        """Reserve the paused runtime for an operator exit."""
        ...

    def end_operator_exit(self) -> None:
        """Release the operator-exit reservation."""
        ...

    def set_runtime_contexts(
        self, *, contexts: tuple[LiveRuntimePositionContext, ...]
    ) -> None:
        """Replace recovered runtime contexts."""
        ...

    def clear_runtime_contexts(self) -> None:
        """Clear recovered runtime contexts."""
        ...

    def set_live_management_authorization(
        self, *, authorization: LiveRecoveredPositionManagementAuthorization
    ) -> None:
        """Install exact management authorization."""
        ...

    def clear_live_management_authorization(self) -> None:
        """Clear process-local management authorization."""
        ...

    def restore_configuration(
        self,
        *,
        symbol: str,
        interval: Interval,
        strategy_type: StrategyType,
        preserve_strategy: bool = False,
    ) -> None:
        """Restore persisted position configuration while paused."""
        ...

    def get_stream_telemetry(self) -> _StreamTelemetry:
        """Return the validated market-tick count for startup readiness."""
        ...
