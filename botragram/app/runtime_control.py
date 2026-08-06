"""Cooperative trading runtime pause and resume control."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

__all__ = ["TradingRuntimeControl"]


@dataclass(slots=True, kw_only=True)
class TradingRuntimeControl:
    """Coordinate pause/resume state without cancelling application resources."""

    _active_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Start in the active state."""
        self._active_event.set()

    @property
    def is_paused(self) -> bool:
        """Return whether new trading cycles are paused."""
        return not self._active_event.is_set()

    def pause(self) -> bool:
        """Pause future cycles and return whether state changed."""
        if self.is_paused:
            return False

        self._active_event.clear()
        return True

    def resume(self) -> bool:
        """Resume future cycles and return whether state changed."""
        if not self.is_paused:
            return False

        self._active_event.set()
        return True

    async def wait_until_active(self, *, stop_event: asyncio.Event) -> bool:
        """Wait until resumed or stopped; return false when stop wins."""
        if stop_event.is_set():
            return False

        if not self.is_paused:
            return True

        active_task = asyncio.create_task(self._active_event.wait())
        stop_task = asyncio.create_task(stop_event.wait())
        tasks = (active_task, stop_task)

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        return not stop_event.is_set()
