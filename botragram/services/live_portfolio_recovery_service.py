"""Recover and protect the authoritative LIVE exchange portfolio."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    Interval,
    LivePortfolioRecoveryStatus,
    LivePortfolioRecoveryUnsafeReason,
    PositionSide,
    SignalType,
    StrategyType,
)
from botragram.models import LivePortfolioRecoveryResult, Position
from botragram.repositories import CandleRepository, SignalRepository

__all__ = ["LivePortfolioRecoveryService"]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class LivePortfolioPositionRecovery(Protocol):
    """Synchronize and persist authoritative positions for portfolio recovery."""

    async def sync(self) -> Sequence[Position]:
        """Return the complete active exchange portfolio with local metadata."""
        ...

    async def save(self, *, position: Position) -> None:
        """Persist one merged position before its protection verification."""
        ...


class LivePortfolioProtectionVerification(Protocol):
    """Verify exchange protection for one recovered live position."""

    async def ensure(self, *, position: Position) -> Position:
        """Return the position after authoritative protection verification."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LivePortfolioRecoveryService:
    """Recover each active LIVE position without selecting a runtime position."""

    position_service: LivePortfolioPositionRecovery
    protection_service: LivePortfolioProtectionVerification
    runtime_control: TradingRuntimeControl
    signal_repository: SignalRepository
    candle_repository: CandleRepository

    async def recover(self) -> LivePortfolioRecoveryResult:
        """Synchronize, persist, and verify the complete LIVE portfolio.

        Returns:
            A typed immutable portfolio safety result.

        Raises:
            asyncio.CancelledError: If synchronization or recovery is cancelled.
        """
        self.runtime_control.set_position_protection_ready(False)

        try:
            positions = tuple(await self.position_service.sync())
        except asyncio.CancelledError:
            raise
        except OSError, RuntimeError, ValueError:
            _LOGGER.exception("LIVE portfolio synchronization failed")
            return self._unsafe(
                recovered_positions=(),
                reason=LivePortfolioRecoveryUnsafeReason.PORTFOLIO_SYNC_FAILED,
            )

        ordered_positions = tuple(
            sorted(positions, key=lambda position: position.symbol.upper())
        )
        if not ordered_positions:
            self.runtime_control.set_position_protection_ready(True)
            return LivePortfolioRecoveryResult(
                status=LivePortfolioRecoveryStatus.NO_POSITIONS,
                recovered_positions=(),
            )

        recovered: list[Position] = []
        for position in ordered_positions:
            restored = await self._restore_metadata(position=position)
            if restored is None:
                return self._unsafe(
                    recovered_positions=tuple(recovered),
                    reason=(
                        LivePortfolioRecoveryUnsafeReason.UNKNOWN_POSITION_METADATA
                    ),
                    symbol=position.symbol,
                )

            try:
                await self.position_service.save(position=restored)
            except asyncio.CancelledError:
                raise
            except OSError, RuntimeError, ValueError:
                _LOGGER.exception(
                    "LIVE portfolio position persistence failed: symbol=%s",
                    restored.symbol,
                )
                return self._unsafe(
                    recovered_positions=tuple(recovered),
                    reason=(
                        LivePortfolioRecoveryUnsafeReason.POSITION_PERSISTENCE_FAILED
                    ),
                    symbol=restored.symbol,
                )

            try:
                protected = await self.protection_service.ensure(position=restored)
            except asyncio.CancelledError:
                raise
            except OSError, RuntimeError, ValueError:
                _LOGGER.exception(
                    "LIVE portfolio protection verification failed: symbol=%s",
                    restored.symbol,
                )
                return self._unsafe(
                    recovered_positions=tuple(recovered),
                    reason=LivePortfolioRecoveryUnsafeReason.PROTECTION_FAILED,
                    symbol=restored.symbol,
                )

            recovered.append(protected)

        result = LivePortfolioRecoveryResult(
            status=(
                LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
                if len(recovered) == 1
                else LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
            ),
            recovered_positions=tuple(recovered),
        )
        self.runtime_control.set_position_protection_ready(
            result.status is LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
        )
        return result

    async def _restore_metadata(self, *, position: Position) -> Position | None:
        """Return existing or uniquely reconstructed local position metadata."""
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

        return replace(
            position,
            interval=matching_intervals[0],
            strategy_type=strategy_type,
        )

    def _unsafe(
        self,
        *,
        recovered_positions: tuple[Position, ...],
        reason: LivePortfolioRecoveryUnsafeReason,
        symbol: str | None = None,
    ) -> LivePortfolioRecoveryResult:
        """Return an unsafe result after logging an expected operational error."""
        self.runtime_control.set_position_protection_ready(False)
        return LivePortfolioRecoveryResult(
            status=LivePortfolioRecoveryStatus.UNSAFE,
            recovered_positions=recovered_positions,
            unsafe_reason=reason,
            unsafe_symbol=symbol,
        )
