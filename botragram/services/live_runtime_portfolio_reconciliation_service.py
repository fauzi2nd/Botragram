"""
Botragram

Description:
    Reconcile authoritative LIVE portfolio state into local management ownership.

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
from dataclasses import dataclass
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import LiveMarketStreamLifecycleStatus, LivePortfolioRecoveryStatus
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LivePortfolioRecoveryResult,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePortfolioContext,
    LiveRuntimePositionContext,
    Position,
)

__all__ = ["LiveRuntimePortfolioReconciliationService"]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Dependency Contracts
# =============================================================================
class LivePortfolioRecovery(Protocol):
    """Recover the authoritative protected LIVE portfolio."""

    async def recover(self) -> LivePortfolioRecoveryResult:
        """Return one immutable authoritative portfolio recovery result."""
        ...


class LiveNaturalExitReconciliation(Protocol):
    """Perform the existing read-first natural-exit reconciliation."""

    async def reconcile(self) -> None:
        """Remove only proven naturally-exited runtime position state."""
        ...


class LiveMarketStreamPortfolioOwner(Protocol):
    """Own exact per-context market streams."""

    @property
    def stream_states(self) -> tuple[LiveMarketStreamState, ...]:
        """Return all owned stream states."""
        ...

    async def start(
        self, *, context: LiveRuntimePositionContext
    ) -> LiveMarketStreamIdentity:
        """Start one context's stream idempotently."""
        ...

    async def wait_for_first_tick(
        self, *, identity: LiveMarketStreamIdentity, timeout_seconds: float
    ) -> bool:
        """Wait for one context's first stream tick."""
        ...

    async def stop(self, *, identity: LiveMarketStreamIdentity) -> bool:
        """Stop one owned stream."""
        ...

    async def stop_all(self) -> None:
        """Release all process-local stream ownership."""
        ...


class LiveProtectionMonitorPortfolioOwner(Protocol):
    """Own exact per-context protection monitors."""

    @property
    def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
        """Return all owned monitor states."""
        ...

    def register(self, *, context: LiveRuntimePositionContext) -> bool:
        """Register one context's monitor idempotently."""
        ...

    def stop(self, *, symbol: str) -> bool:
        """Stop one owned monitor."""
        ...

    def stop_all(self) -> None:
        """Release all process-local monitor ownership."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveRuntimePortfolioReconciliationService:
    """Adopt the exact protected LIVE portfolio into local management state."""

    runtime_control: TradingRuntimeControl
    live_portfolio_recovery_service: LivePortfolioRecovery
    market_stream_service: LiveMarketStreamPortfolioOwner
    protection_monitoring_service: LiveProtectionMonitorPortfolioOwner
    first_tick_timeout_seconds: float
    live_natural_exit_recovery_service: LiveNaturalExitReconciliation | None = None

    def __post_init__(self) -> None:
        """Validate the bounded first-tick readiness wait."""
        if self.first_tick_timeout_seconds <= 0:
            raise ValueError("First stream tick timeout must be greater than zero")

    async def reconcile(self) -> bool:
        """Return whether canonical LIVE portfolio reconciliation completed safely."""
        return (await self.reconcile_context()) is not None

    async def reconcile_context(self) -> LiveRuntimePortfolioContext | None:
        """Synchronize and return the exact authoritative managed portfolio.

        Raises:
            asyncio.CancelledError: If reconciliation is cancelled.

        Returns:
            Exact managed runtime portfolio when safe, otherwise ``None``.
        """
        self.runtime_control.set_position_protection_ready(False)
        try:
            natural_exit_recovery = self.live_natural_exit_recovery_service
            if natural_exit_recovery is not None:
                await natural_exit_recovery.reconcile()

            portfolio = await self.live_portfolio_recovery_service.recover()
            if portfolio.status is LivePortfolioRecoveryStatus.UNSAFE:
                await self._fail_closed()
                return None

            contexts = tuple(
                sorted(
                    (
                        self._to_runtime_context(position=position)
                        for position in portfolio.recovered_positions
                    ),
                    key=lambda context: (
                        context.symbol,
                        context.interval.value,
                        context.strategy_type.value,
                    ),
                )
            )
            portfolio_context = LiveRuntimePortfolioContext(contexts=contexts)
            if not contexts:
                await self._remove_stale_ownership(contexts=())
                self.runtime_control.clear_runtime_contexts()
                self.runtime_control.clear_live_management_authorization()
                self.runtime_control.set_position_protection_ready(True)
                return portfolio_context

            self.runtime_control.set_runtime_contexts(contexts=contexts)
            await self._remove_stale_ownership(contexts=contexts)
            await self._ensure_streams_ready(contexts=contexts)
            self._ensure_monitors_ready(contexts=contexts)
            if not self._ownership_is_exact(contexts=contexts):
                raise RuntimeError("LIVE portfolio management ownership is incomplete")

            self.runtime_control.set_live_management_authorization(
                authorization=LiveRecoveredPositionManagementAuthorization(
                    contexts=contexts,
                    runtime_management_allowed=True,
                )
            )
            self.runtime_control.set_position_protection_ready(True)
            return portfolio_context
        except asyncio.CancelledError:
            await self._fail_closed()
            raise
        except Exception:
            _LOGGER.exception("LIVE runtime portfolio reconciliation failed")
            await self._fail_closed()
            return None

    async def _remove_stale_ownership(
        self, *, contexts: tuple[LiveRuntimePositionContext, ...]
    ) -> None:
        """Release only stream and monitor ownership outside the target portfolio."""
        target_identities = {
            LiveMarketStreamIdentity.from_runtime_context(context=context)
            for context in contexts
        }
        target_contexts = frozenset(contexts)
        stale_monitor_symbols = tuple(
            state.context.symbol
            for state in self.protection_monitoring_service.monitor_states
            if state.context not in target_contexts
        )
        stale_streams = tuple(
            state.identity
            for state in self.market_stream_service.stream_states
            if state.identity not in target_identities
        )
        for symbol in stale_monitor_symbols:
            self.protection_monitoring_service.stop(symbol=symbol)
        for identity in stale_streams:
            await self.market_stream_service.stop(identity=identity)

    async def _ensure_streams_ready(
        self, *, contexts: tuple[LiveRuntimePositionContext, ...]
    ) -> None:
        """Start only missing streams and prove first-tick readiness for every one."""
        states = {
            state.identity: state for state in self.market_stream_service.stream_states
        }
        identities: list[LiveMarketStreamIdentity] = []
        for context in contexts:
            identity = LiveMarketStreamIdentity.from_runtime_context(context=context)
            if identity not in states:
                identity = await self.market_stream_service.start(context=context)
            identities.append(identity)

        for identity in identities:
            is_ready = await self.market_stream_service.wait_for_first_tick(
                identity=identity,
                timeout_seconds=self.first_tick_timeout_seconds,
            )
            state = next(
                (
                    candidate
                    for candidate in self.market_stream_service.stream_states
                    if candidate.identity == identity
                ),
                None,
            )
            if (
                not is_ready
                or state is None
                or state.lifecycle_status is not LiveMarketStreamLifecycleStatus.RUNNING
                or not state.first_tick_received
            ):
                raise RuntimeError(
                    "LIVE stream is not ready for portfolio management: "
                    f"{identity.symbol}:{identity.interval.value}"
                )

    def _ensure_monitors_ready(
        self, *, contexts: tuple[LiveRuntimePositionContext, ...]
    ) -> None:
        """Register only missing monitors and reject unhealthy existing monitors."""
        states = {
            state.context: state
            for state in self.protection_monitoring_service.monitor_states
        }
        for context in contexts:
            state = states.get(context)
            if state is None:
                if not self.protection_monitoring_service.register(context=context):
                    raise RuntimeError(
                        "LIVE protection monitor registration was rejected: "
                        f"{context.symbol}"
                    )
                continue
            if not state.is_active or state.failure_type is not None:
                raise RuntimeError(
                    f"LIVE protection monitor is unhealthy: {context.symbol}"
                )

    def _ownership_is_exact(
        self, *, contexts: tuple[LiveRuntimePositionContext, ...]
    ) -> bool:
        """Require exact canonical contexts across all management ownership."""
        expected_identities = tuple(
            LiveMarketStreamIdentity.from_runtime_context(context=context)
            for context in contexts
        )
        stream_states = self.market_stream_service.stream_states
        monitor_states = self.protection_monitoring_service.monitor_states
        return (
            self.runtime_control.runtime_contexts == contexts
            and tuple(state.identity for state in stream_states) == expected_identities
            and all(
                state.lifecycle_status is LiveMarketStreamLifecycleStatus.RUNNING
                and state.first_tick_received
                for state in stream_states
            )
            and tuple(state.context for state in monitor_states) == contexts
            and all(
                state.is_active and state.failure_type is None
                for state in monitor_states
            )
        )

    async def _fail_closed(self) -> None:
        """Release local ownership and close the new-exposure gate after failure."""
        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.clear_live_management_authorization()
        self.runtime_control.pause()
        self.protection_monitoring_service.stop_all()
        try:
            await self.market_stream_service.stop_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("LIVE runtime stream cleanup failed after reconciliation")

    @staticmethod
    def _to_runtime_context(*, position: Position) -> LiveRuntimePositionContext:
        """Build one exact context from restored and protected position metadata."""
        interval = position.interval
        strategy_type = position.strategy_type
        if interval is None or strategy_type is None:
            raise RuntimeError("Recovered position is missing runtime metadata")
        return LiveRuntimePositionContext(
            symbol=position.symbol,
            interval=interval,
            strategy_type=strategy_type,
        )
