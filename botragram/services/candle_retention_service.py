"""
Botragram

Description:
    Automated retention policy and periodic pruning for stored candlestick data.

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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.repositories import CandleRepository
from botragram.storage.sqlite import SQLiteDatabase

__all__ = [
    "CandleRetentionService",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class CandleRetentionService:
    """Periodically prune expired candlestick rows to prevent database bloat."""

    candle_repository: CandleRepository
    database: SQLiteDatabase | None = None
    retention_days: int = 7
    pruning_interval_hours: int = 6
    startup_delay_seconds: float = 60.0
    utc_now: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
    )
    _task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate positive retention limits."""
        if self.retention_days <= 0:
            raise ValueError("Retention days must be a positive integer")
        if self.pruning_interval_hours <= 0:
            raise ValueError("Pruning interval hours must be a positive integer")

    async def prune_expired_candles(self) -> int:
        """Delete candles older than the retention boundary.

        Returns:
            The number of deleted candlestick records.
        """
        cutoff = self.utc_now() - timedelta(days=self.retention_days)
        deleted_count = await self.candle_repository.delete_before(before=cutoff)

        if deleted_count > 0:
            _LOGGER.info(
                "Pruned %d expired candles older than %s (retention=%d days)",
                deleted_count,
                cutoff.isoformat(),
                self.retention_days,
            )
            if self.database is not None:
                try:
                    await self.database.execute(statement="PRAGMA optimize;")
                except Exception as err:
                    _LOGGER.debug(
                        "SQLite PRAGMA optimize skipped after candle pruning: %s",
                        err,
                    )
        else:
            _LOGGER.debug(
                "Candle retention check completed: 0 candles older than %s",
                cutoff.isoformat(),
            )

        return deleted_count

    @property
    def is_running(self) -> bool:
        """Return whether the periodic background task is active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the periodic candle retention background worker."""
        if self.is_running:
            return
        self._task = asyncio.create_task(
            self._run_loop(),
            name="candle_retention_worker",
        )
        _LOGGER.info(
            "Candle retention service started (retention=%d days, interval=%dh)",
            self.retention_days,
            self.pruning_interval_hours,
        )

    async def stop(self) -> None:
        """Stop the periodic candle retention background worker cleanly."""
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _LOGGER.info("Candle retention service stopped")

    async def _run_loop(self) -> None:
        """Run periodic pruning cycles indefinitely until cancelled."""
        try:
            if self.startup_delay_seconds > 0:
                await asyncio.sleep(self.startup_delay_seconds)
            await self.prune_expired_candles()
            while True:
                sleep_seconds = float(self.pruning_interval_hours * 3600)
                await asyncio.sleep(sleep_seconds)
                await self.prune_expired_candles()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unexpected error in candle retention worker loop")
