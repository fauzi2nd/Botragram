"""Recover an active trading position after an application restart."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    Interval,
    LivePortfolioRecoveryStatus,
    MarketType,
    PositionSide,
    SignalType,
    StrategyType,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.models import LiveRuntimePositionContext, Position
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


@dataclass(slots=True, kw_only=True, frozen=True)
class RuntimeRecoveryService:
    """Restore one active position without bypassing live safety gates."""

    trade_mode: TradeMode
    market_type: MarketType
    runtime_control: TradingRuntimeControl
    stream_controller: MarketStreamController
    position_repository: PositionRepository
    signal_repository: SignalRepository
    candle_repository: CandleRepository
    live_portfolio_recovery_service: LivePortfolioRecoveryService
    first_tick_timeout_seconds: float = _FIRST_TICK_TIMEOUT_SECONDS
    submission_attempt_repository: SubmissionAttemptRepository | None = None
    live_submission_recovery_service: LiveIncompleteSubmissionRecovery | None = None
    live_post_entry_recovery_service: LiveAcknowledgedEntryRecovery | None = None

    def __post_init__(self) -> None:
        """Validate recovery timing."""
        if self.first_tick_timeout_seconds <= 0:
            raise ValueError("First stream tick timeout must be greater than zero")

    async def recover(self) -> bool:
        """Recover one position and resume only when every safety gate is ready."""
        if self.trade_mode is TradeMode.LIVE:
            self.runtime_control.set_position_protection_ready(False)
            if not await self._recover_incomplete_live_entry():
                return False

            if self.market_type is not MarketType.FUTURES:
                _LOGGER.critical(
                    "Automatic live position recovery currently requires FUTURES"
                )
                return False

            portfolio_result = await self.live_portfolio_recovery_service.recover()
            if portfolio_result.status is LivePortfolioRecoveryStatus.NO_POSITIONS:
                self.runtime_control.clear_runtime_contexts()
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
                self.runtime_control.set_runtime_contexts(
                    contexts=tuple(
                        self._to_runtime_context(position=position)
                        for position in portfolio_result.recovered_positions
                    ),
                )
                _LOGGER.critical(
                    "LIVE portfolio is protected but singular runtime activation "
                    "remains blocked: count=%d",
                    len(portfolio_result.recovered_positions),
                )
                return False

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

        if post_entry_result is LivePostEntryRecoveryResult.COMPLETED:
            return True

        _LOGGER.critical(
            "LIVE startup blocked because acknowledged entry position is not visible"
        )
        return False

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
