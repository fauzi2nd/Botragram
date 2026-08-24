"""
Botragram

Description:
    Regression tests for LIVE position lifecycle serialization.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.services import LivePositionLifecycleCoordinator


# =============================================================================
# Regression Tests
# =============================================================================
def test_natural_exit_deletion_runs_before_a_later_protection_tick() -> None:
    """Prevent a stale tick from updating a position after natural exit deletion."""
    asyncio.run(_run_natural_exit_and_tick_race())


async def _run_natural_exit_and_tick_race() -> None:
    """Serialize a deletion and a stale tick with the production coordinator."""
    coordinator = LivePositionLifecycleCoordinator()
    deletion_entered = asyncio.Event()
    allow_deletion = asyncio.Event()
    position_exists = True
    events: list[str] = []

    async def natural_exit() -> None:
        """Delete the already-proven zero-exposure local position."""
        nonlocal position_exists
        async with coordinator.hold(symbol="AIOUSDT"):
            deletion_entered.set()
            await allow_deletion.wait()
            position_exists = False
            events.append("delete")

    async def protection_tick() -> None:
        """Update only a position that remains after lifecycle ownership."""
        async with coordinator.hold(symbol="AIOUSDT"):
            if position_exists:
                events.append("update")

    deletion_task = asyncio.create_task(natural_exit())
    await deletion_entered.wait()
    tick_task = asyncio.create_task(protection_tick())
    await asyncio.sleep(0)
    allow_deletion.set()
    await asyncio.gather(deletion_task, tick_task)

    assert events == ["delete"]


def test_position_deletion_invalidates_the_normalized_symbol_cache_version() -> None:
    """Expose one monotonic cache version after a durable natural exit."""
    coordinator = LivePositionLifecycleCoordinator()

    assert coordinator.get_position_version(symbol="aiousdt") == 0

    coordinator.record_position_deletion(symbol="AIOUSDT")

    assert coordinator.get_position_version(symbol="aiousdt") == 1
