"""Recover an active trading position after an application restart."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.app.trading_runner import MultiContextRunnerActivationPreconditions
from botragram.enums import (
    Interval,
    LiveMarketStreamLifecycleStatus,
    LivePortfolioRecoveryStatus,
    MarketType,
    PositionSide,
    SignalType,
    StrategyType,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveProtectionMonitorState,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
    Position,
)
from botragram.repositories import (
    CandleRepository,
    PositionRepository,
    SignalRepository,
    SubmissionAttemptRepository,
)
from botragram.services.live_portfolio_recovery_service import (
    LivePortfolioRecoveryService,
)
from botragram.services.live_post_entry_recovery_service import (
    LiveAcknowledgedEntryRecovery,
    LivePostEntryRecoveryResult,
)
from botragram.services.live_submission_recovery_service import (
    LiveIncompleteSubmissionRecovery,
    LiveSubmissionRecoveryResult,
)

__all__ = ["RuntimeRecoveryService"]


_FIRST_TICK_TIMEOUT_SECONDS: Final[float] = 15.0
_FIRST_TICK_POLL_SECONDS: Final[float] = 0.05
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class MarketStreamController(Protocol):
    """Control the process-wide market stream used by runtime recovery."""

    async def start_market_stream(self) -> bool:
        """Start the selected market stream."""
        ...

    async def stop_market_stream(self) -> bool:
        """Stop the selected market stream."""
        ...


class LiveMarketStreamOwner(Protocol):
    """Own multi-context market streams without Telegram compatibility routing."""

    @property
    def stream_states(self) -> tuple[LiveMarketStreamState, ...]:
        """Return immutable state for every owned market stream."""
        ...

    async def start(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> LiveMarketStreamIdentity:
        """Start one stream from its runtime context."""
        ...

    async def wait_for_first_tick(
        self,
        *,
        identity: LiveMarketStreamIdentity,
        timeout_seconds: float,
    ) -> bool:
        """Wait for one owned stream's first valid tick."""
        ...

    async def stop(self, *, identity: LiveMarketStreamIdentity) -> bool:
        """Stop one owned stream."""
        ...


class LiveNaturalExitRecovery(Protocol):
    """Reconcile natural exits before normal LIVE portfolio recovery."""

    async def reconcile(self) -> None:
        """Remove proven orphan protection or fail closed."""
        ...


class LiveProtectionMonitorOwner(Protocol):
    """Own independent per-position protection monitors during recovery."""

    @property
    def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
        """Return immutable state for every owned protection monitor."""
        ...

    def register(self, *, context: LiveRuntimePositionContext) -> bool:
        """Register one monitor for a recovered runtime context."""
        ...

    def stop(self, *, symbol: str) -> bool:
        """Stop one runtime monitor without changing durable protection."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class RuntimeRecoveryService:
    """Restore recovered runtime state without bypassing LIVE safety gates."""

    trade_mode: TradeMode
    market_type: MarketType
    runtime_control: TradingRuntimeControl
    stream_controller: MarketStreamController
    market_stream_service: LiveMarketStreamOwner
    protection_monitoring_service: LiveProtectionMonitorOwner
    position_repository: PositionRepository
    signal_repository: SignalRepository
    candle_repository: CandleRepository
    live_portfolio_recovery_service: LivePortfolioRecoveryService
    first_tick_timeout_seconds: float = _FIRST_TICK_TIMEOUT_SECONDS
    submission_attempt_repository: SubmissionAttemptRepository | None = None
    live_submission_recovery_service: LiveIncompleteSubmissionRecovery | None = None
    live_post_entry_recovery_service: LiveAcknowledgedEntryRecovery | None = None
    live_natural_exit_recovery_service: LiveNaturalExitRecovery | None = None
    autonomous_live_entry_authorization: AutonomousLiveEntryAuthorization | None = None

    def __post_init__(self) -> None:
        """Validate recovery timing."""
        if self.first_tick_timeout_seconds <= 0:
            raise ValueError("First stream tick timeout must be greater than zero")

    async def recover(self) -> bool:
        """Rebuild runtime state and resume only when every safety gate is ready."""
        if self.trade_mode is TradeMode.LIVE:
            if not await self._clear_live_recovery_runtime_state():
                _LOGGER.critical(
                    "LIVE recovery cannot release prior process-local runtime state"
                )
                return False
            if not await self._recover_incomplete_live_entry():
                return False

            if self.market_type is not MarketType.FUTURES:
                _LOGGER.critical(
                    "Automatic live position recovery currently requires FUTURES"
                )
                return False

            if not await self._recover_natural_live_exit():
                return False

            portfolio_result = await self.live_portfolio_recovery_service.recover()
            if portfolio_result.status is LivePortfolioRecoveryStatus.NO_POSITIONS:
                self.runtime_control.clear_runtime_contexts()
                if self.autonomous_live_entry_authorization is not None:
                    self.runtime_control.set_position_protection_ready(True)
                    self.runtime_control.resume_global_cycle()
                    _LOGGER.info(
                        "TESTNET autonomous LIVE runtime activated after clean "
                        "portfolio recovery"
                    )
                    return True
                return False
            if portfolio_result.status is LivePortfolioRecoveryStatus.UNSAFE:
                self.runtime_control.clear_runtime_contexts()
                _LOGGER.critical(
                    "LIVE portfolio recovery is unsafe: reason=%s symbol=%s",
                    portfolio_result.unsafe_reason,
                    portfolio_result.unsafe_symbol,
                )
                return False
            if (
                portfolio_result.status
                is LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
            ):
                contexts = tuple(
                    self._to_runtime_context(position=position)
                    for position in portfolio_result.recovered_positions
                )
                self.runtime_control.set_runtime_contexts(contexts=contexts)
                started_identities = await self._start_multi_position_streams(
                    contexts=contexts
                )
                if started_identities is None:
                    await self._clear_live_recovery_runtime_state()
                    return False
                try:
                    if not self._register_protection_monitors(contexts=contexts):
                        await self._clear_live_recovery_runtime_state()
                        return False
                except asyncio.CancelledError:
                    await self._clear_live_recovery_runtime_state()
                    raise
                try:
                    authorization = LiveRecoveredPositionManagementAuthorization(
                        contexts=contexts,
                        runtime_management_allowed=True,
                    )
                    self.runtime_control.set_live_management_authorization(
                        authorization=authorization,
                    )
                    preconditions = self.get_multi_context_activation_preconditions(
                        runtime_is_stopping=False,
                    )
                    if preconditions is None or not preconditions.can_activate:
                        await self._clear_live_recovery_runtime_state()
                        return False
                    self.runtime_control.set_position_protection_ready(True)
                    self.runtime_control.resume()
                except asyncio.CancelledError:
                    await self._clear_live_recovery_runtime_state()
                    raise
                except Exception:
                    _LOGGER.exception(
                        "LIVE multi-position management activation failed"
                    )
                    await self._clear_live_recovery_runtime_state()
                    return False
                _LOGGER.critical(
                    "LIVE recovered multi-position management activated: count=%d",
                    len(portfolio_result.recovered_positions),
                )
                return True

            if (
                portfolio_result.status
                is not LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
            ):
                raise RuntimeError(
                    "Unsupported LIVE portfolio recovery status: "
                    f"{portfolio_result.status!r}"
                )

            position = portfolio_result.recovered_positions[0]
            self.runtime_control.set_runtime_contexts(
                contexts=(self._to_runtime_context(position=position),),
            )
        else:
            positions = tuple(await self.position_repository.get_open_positions())
            if not positions:
                return False
            if len(positions) != 1:
                _LOGGER.critical(
                    "Automatic recovery requires exactly one active position: count=%d",
                    len(positions),
                )
                return False

            restored_position = await self._restore_metadata(position=positions[0])
            if restored_position is None:
                _LOGGER.critical(
                    "Automatic recovery blocked because position metadata could not "
                    "be reconstructed unambiguously: symbol=%s",
                    positions[0].symbol,
                )
                return False
            await self.position_repository.save(position=restored_position)
            position = restored_position

        self.runtime_control.restore_configuration(
            symbol=position.symbol,
            interval=self._require_interval(position),
            strategy_type=self._require_strategy(position),
        )
        await self.stream_controller.start_market_stream()

        try:
            await self._wait_for_first_tick()
        except TimeoutError:
            await self.stream_controller.stop_market_stream()
            _LOGGER.error(
                "Automatic recovery timed out waiting for first stream tick: "
                "symbol=%s timeout_seconds=%.1f",
                position.symbol,
                self.first_tick_timeout_seconds,
            )
            return False

        if self.trade_mode is TradeMode.LIVE:
            try:
                if not self._register_protection_monitors(
                    contexts=(self._to_runtime_context(position=position),),
                ):
                    await self.stream_controller.stop_market_stream()
                    return False
            except asyncio.CancelledError:
                await self.stream_controller.stop_market_stream()
                raise

        self.runtime_control.resume()
        _LOGGER.info(
            "Active position recovered automatically: mode=%s symbol=%s side=%s "
            "interval=%s strategy=%s",
            self.trade_mode.value,
            position.symbol,
            position.side.value,
            self._require_interval(position).value,
            self._require_strategy(position).value,
        )
        return True

    def get_multi_context_activation_preconditions(
        self,
        *,
        runtime_is_stopping: bool,
    ) -> MultiContextRunnerActivationPreconditions | None:
        """Return exact current LIVE multi-context runner activation state."""
        authorization = self.runtime_control.live_management_authorization
        contexts = self.runtime_control.runtime_contexts

        if authorization is None or len(contexts) <= 1:
            return None

        return MultiContextRunnerActivationPreconditions(
            portfolio_status=LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE,
            contexts=contexts,
            stream_states=self.market_stream_service.stream_states,
            monitor_states=self.protection_monitoring_service.monitor_states,
            live_management_authorization=authorization,
            runtime_is_paused=self.runtime_control.is_paused,
            runtime_is_stopping=runtime_is_stopping,
        )

    async def _clear_live_recovery_runtime_state(self) -> bool:
        """Release all process-local LIVE runtime state before recovery or exit.

        Returns:
            Whether monitor and stream ownership is empty after deterministic
            cleanup. Durable exchange protection is intentionally untouched.
        """
        monitor_symbols = tuple(
            monitor_state.context.symbol
            for monitor_state in self.protection_monitoring_service.monitor_states
        )
        stream_identities = tuple(
            stream_state.identity
            for stream_state in self.market_stream_service.stream_states
        )
        self.runtime_control.pause()
        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.clear_runtime_contexts()
        self._stop_recovery_monitors(symbols=list(monitor_symbols))
        await self._stop_recovery_streams(identities=stream_identities)

        is_cleared = (
            not self.protection_monitoring_service.monitor_states
            and not self.market_stream_service.stream_states
        )
        if not is_cleared:
            _LOGGER.critical(
                "LIVE recovery cleanup left process-local ownership: monitors=%d "
                "streams=%d",
                len(self.protection_monitoring_service.monitor_states),
                len(self.market_stream_service.stream_states),
            )
        return is_cleared

    async def _recover_natural_live_exit(self) -> bool:
        """Reconcile natural exits before normal LIVE portfolio recovery."""
        service = self.live_natural_exit_recovery_service
        if service is None:
            return True

        try:
            await service.reconcile()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "LIVE natural-exit recovery failed; runtime remains paused"
            )
            return False

        return True

    async def _recover_incomplete_live_entry(self) -> bool:
        """Recover a durable LIVE entry before normal position recovery runs."""
        submission_recovery = self.live_submission_recovery_service
        post_entry_recovery = self.live_post_entry_recovery_service
        attempt_repository = self.submission_attempt_repository

        if (
            submission_recovery is None
            or post_entry_recovery is None
            or attempt_repository is None
        ):
            return True

        try:
            result = await submission_recovery.recover_incomplete()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("LIVE submission recovery failed; runtime remains paused")
            return False

        if result in {
            LiveSubmissionRecoveryResult.NOTHING_TO_RECOVER,
            LiveSubmissionRecoveryResult.TERMINALLY_REJECTED,
        }:
            return True

        if result in {
            LiveSubmissionRecoveryResult.STILL_INCOMPLETE,
            LiveSubmissionRecoveryResult.MULTIPLE_INCOMPLETE,
        }:
            _LOGGER.critical(
                "LIVE startup blocked by incomplete submission recovery: result=%s",
                result.value,
            )
            return False

        attempts = tuple(await attempt_repository.get_incomplete())
        if (
            len(attempts) != 1
            or attempts[0].status is not SubmissionAttemptStatus.ACKNOWLEDGED
        ):
            _LOGGER.critical(
                "LIVE startup blocked because acknowledged recovery handoff is "
                "not singular"
            )
            return False

        try:
            post_entry_result = await post_entry_recovery.recover_acknowledged(
                attempt=attempts[0],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "LIVE acknowledged-entry recovery failed; runtime remains paused"
            )
            return False

        if post_entry_result in {
            LivePostEntryRecoveryResult.COMPLETED,
            LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE,
        }:
            return True

        _LOGGER.critical(
            "LIVE startup blocked because acknowledged entry position is not visible"
        )
        return False

    async def _start_multi_position_streams(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> tuple[LiveMarketStreamIdentity, ...] | None:
        """Start and verify every recovered stream while keeping runtime paused."""
        stream_service = self.market_stream_service

        if stream_service.stream_states:
            _LOGGER.critical(
                "LIVE multi-position stream recovery requires no pre-existing "
                "owned streams"
            )
            return None

        started_identities: list[LiveMarketStreamIdentity] = []

        try:
            for context in contexts:
                identity = await stream_service.start(context=context)
                started_identities.append(identity)

            for identity in started_identities:
                is_ready = await stream_service.wait_for_first_tick(
                    identity=identity,
                    timeout_seconds=self.first_tick_timeout_seconds,
                )
                stream_state = self._get_owned_stream_state(identity=identity)

                if (
                    not is_ready
                    or stream_state is None
                    or stream_state.lifecycle_status
                    is not LiveMarketStreamLifecycleStatus.RUNNING
                    or not stream_state.first_tick_received
                ):
                    _LOGGER.error(
                        "LIVE multi-position stream readiness failed: symbol=%s "
                        "interval=%s",
                        identity.symbol,
                        identity.interval.value,
                    )
                    await self._stop_recovery_streams(
                        identities=tuple(started_identities)
                    )
                    return None
        except asyncio.CancelledError:
            await self._stop_recovery_streams(identities=tuple(started_identities))
            raise
        except Exception:
            _LOGGER.exception("LIVE multi-position stream startup failed")
            await self._stop_recovery_streams(identities=tuple(started_identities))
            return None

        return tuple(started_identities)

    def _register_protection_monitors(
        self,
        *,
        contexts: tuple[LiveRuntimePositionContext, ...],
    ) -> bool:
        """Register every context or release only this recovery attempt's monitors."""
        monitor_service = self.protection_monitoring_service

        if monitor_service.monitor_states:
            _LOGGER.critical(
                "LIVE recovery requires no pre-existing protection monitors"
            )
            return False

        registered_symbols: list[str] = []

        try:
            for context in contexts:
                if not monitor_service.register(context=context):
                    _LOGGER.error(
                        "LIVE protection monitor registration was rejected: symbol=%s",
                        context.symbol,
                    )
                    self._stop_recovery_monitors(symbols=registered_symbols)
                    return False
                registered_symbols.append(context.symbol)
        except asyncio.CancelledError:
            self._stop_recovery_monitors(symbols=registered_symbols)
            raise
        except Exception:
            _LOGGER.exception("LIVE protection monitor registration failed")
            self._stop_recovery_monitors(symbols=registered_symbols)
            return False

        return True

    def _stop_recovery_monitors(self, *, symbols: list[str]) -> None:
        """Release only monitors registered by this recovery attempt."""
        for symbol in reversed(symbols):
            try:
                self.protection_monitoring_service.stop(symbol=symbol)
            except Exception:
                _LOGGER.exception(
                    "LIVE protection monitor cleanup failed: symbol=%s",
                    symbol,
                )

    async def _stop_recovery_streams(
        self,
        *,
        identities: tuple[LiveMarketStreamIdentity, ...],
    ) -> None:
        """Stop only streams started by this recovery attempt in reverse order."""
        for identity in reversed(identities):
            try:
                await self.market_stream_service.stop(identity=identity)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "LIVE multi-position recovery stream cleanup failed: "
                    "symbol=%s interval=%s",
                    identity.symbol,
                    identity.interval.value,
                )

    def _get_owned_stream_state(
        self,
        *,
        identity: LiveMarketStreamIdentity,
    ) -> LiveMarketStreamState | None:
        """Return one identity-specific owner snapshot without selecting a stream."""
        return next(
            (
                stream_state
                for stream_state in self.market_stream_service.stream_states
                if stream_state.identity == identity
            ),
            None,
        )

    async def _restore_metadata(self, *, position: Position) -> Position | None:
        """Reconstruct missing paper metadata from its exact entry history."""
        if position.interval is not None and position.strategy_type is not None:
            return position

        expected_signal_type = (
            SignalType.BUY if position.side is PositionSide.LONG else SignalType.SELL
        )
        signals = tuple(
            signal
            for signal in await self.signal_repository.get_between(
                start_time=position.opened_at,
                end_time=position.opened_at,
                symbol=position.symbol,
                signal_type=expected_signal_type,
            )
            if signal.generated_at == position.opened_at
        )

        if len(signals) != 1:
            return None

        try:
            strategy_type = StrategyType(signals[0].strategy_name)
        except ValueError:
            return None

        matching_intervals: list[Interval] = []

        for interval in Interval:
            candles = await self.candle_repository.get_between(
                symbol=position.symbol,
                interval=interval,
                start_time=position.opened_at - timedelta(seconds=interval.seconds),
                end_time=position.opened_at,
            )

            if any(candle.close_time == position.opened_at for candle in candles):
                matching_intervals.append(interval)

        if len(matching_intervals) != 1:
            return None

        restored = replace(
            position,
            interval=matching_intervals[0],
            strategy_type=strategy_type,
        )
        _LOGGER.warning(
            "Legacy position recovery metadata reconstructed from entry history: "
            "symbol=%s interval=%s strategy=%s",
            restored.symbol,
            matching_intervals[0].value,
            strategy_type.value,
        )
        return restored

    async def _wait_for_first_tick(self) -> None:
        """Wait until the restored stream has delivered one validated ticker."""
        async with asyncio.timeout(self.first_tick_timeout_seconds):
            while self.runtime_control.get_stream_telemetry().event_count == 0:
                await asyncio.sleep(_FIRST_TICK_POLL_SECONDS)

    @staticmethod
    def _to_runtime_context(*, position: Position) -> LiveRuntimePositionContext:
        """Build one runtime context from an already recovered position."""
        return LiveRuntimePositionContext(
            symbol=position.symbol,
            interval=RuntimeRecoveryService._require_interval(position),
            strategy_type=RuntimeRecoveryService._require_strategy(position),
        )

    @staticmethod
    def _require_interval(position: Position) -> Interval:
        """Return recovery interval after metadata restoration."""
        if position.interval is None:
            raise RuntimeError("Recovered position interval is missing")

        return position.interval

    @staticmethod
    def _require_strategy(position: Position) -> StrategyType:
        """Return recovery strategy after metadata restoration."""
        if position.strategy_type is None:
            raise RuntimeError("Recovered position strategy is missing")

        return position.strategy_type
