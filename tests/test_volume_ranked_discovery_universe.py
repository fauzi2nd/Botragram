"""Volume-ranked process-local discovery-universe rotation tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, dataclass, field
from decimal import Decimal

import pytest

from botragram.models import DiscoveryUniverseBatch, MarketUniverseEntry
from botragram.services import VolumeRankedDiscoveryUniverseService


def _entries(*, prefix: str, count: int) -> tuple[MarketUniverseEntry, ...]:
    return tuple(
        MarketUniverseEntry(
            symbol=f"{prefix}{rank:03d}USDT",
            quote_volume=Decimal(count - rank + 1),
        )
        for rank in range(1, count + 1)
    )


@dataclass(slots=True)
class _RankedUniverseProvider:
    outcomes: list[Sequence[MarketUniverseEntry] | Exception]
    calls: int = 0
    quote_assets: list[str] = field(default_factory=list[str])

    async def get_market_universe(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[MarketUniverseEntry]:
        self.calls += 1
        self.quote_assets.append(quote_asset)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_sweep_covers_complete_ranked_snapshot_before_refresh() -> None:
    """Cover 120 entries despite the legacy configured universe limit of 100."""
    asyncio.run(_run_complete_sweep_test())


async def _run_complete_sweep_test() -> None:
    first_snapshot = _entries(prefix="A", count=120)
    second_snapshot = _entries(prefix="B", count=120)
    provider = _RankedUniverseProvider(outcomes=[first_snapshot, second_snapshot])
    service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset=" usdt ",
        universe_limit=100,
        batch_size=20,
    )

    for batch_number in range(6):
        batch = await service.get_current_batch()
        assert await service.get_current_batch() is batch
        assert batch.universe_size == 120
        assert batch.rank_start == batch_number * 20 + 1
        assert batch.rank_end == (batch_number + 1) * 20
        assert (
            batch.entries == first_snapshot[batch_number * 20 : (batch_number + 1) * 20]
        )
        service.complete_batch(batch=batch)

    assert provider.calls == 1
    refreshed = await service.get_current_batch()
    assert provider.calls == 2
    assert provider.quote_assets == ["USDT", "USDT"]
    assert refreshed.rank_start == 1
    assert refreshed.rank_end == 20
    assert refreshed.entries == second_snapshot[:20]


def test_new_service_instance_restarts_from_rank_one() -> None:
    asyncio.run(_run_restart_rank_test())


async def _run_restart_rank_test() -> None:
    snapshot = _entries(prefix="A", count=40)
    provider = _RankedUniverseProvider(outcomes=[snapshot, snapshot])
    first_service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset="USDT",
        universe_limit=40,
        batch_size=20,
    )
    first_batch = await first_service.get_current_batch()
    first_service.complete_batch(batch=first_batch)
    assert (await first_service.get_current_batch()).rank_start == 21

    restarted_service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset="USDT",
        universe_limit=40,
        batch_size=20,
    )
    restarted_batch = await restarted_service.get_current_batch()
    assert provider.calls == 2
    assert restarted_batch.rank_start == 1
    assert restarted_batch.rank_end == 20


def test_failed_or_cancelled_discovery_keeps_the_real_current_batch() -> None:
    asyncio.run(_run_real_service_failure_and_cancellation_test())


async def _run_real_service_failure_and_cancellation_test() -> None:
    provider = _RankedUniverseProvider(outcomes=[_entries(prefix="A", count=2)])
    service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset="USDT",
        universe_limit=2,
        batch_size=1,
    )
    selected = await service.get_current_batch()

    async def fail_discovery() -> None:
        assert await service.get_current_batch() is selected
        raise RuntimeError("discovery failed")

    with pytest.raises(RuntimeError, match="discovery failed"):
        await fail_discovery()
    assert await service.get_current_batch() is selected

    discovery_started = asyncio.Event()

    async def block_discovery() -> None:
        assert await service.get_current_batch() is selected
        discovery_started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(block_discovery())
    await discovery_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await service.get_current_batch() is selected
    service.complete_batch(batch=selected)
    assert (await service.get_current_batch()).rank_start == 2


@pytest.mark.parametrize(
    ("universe_size", "expected_batch_sizes"),
    ((47, (20, 20, 7)), (7, (7,))),
)
def test_partial_sweeps_complete_the_tail_before_refresh(
    universe_size: int,
    expected_batch_sizes: tuple[int, ...],
) -> None:
    asyncio.run(
        _run_partial_sweep_test(
            universe_size=universe_size,
            expected_batch_sizes=expected_batch_sizes,
        )
    )


async def _run_partial_sweep_test(
    *,
    universe_size: int,
    expected_batch_sizes: tuple[int, ...],
) -> None:
    snapshot = _entries(prefix="A", count=universe_size)
    provider = _RankedUniverseProvider(outcomes=[snapshot, snapshot])
    service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset="USDT",
        universe_limit=100,
        batch_size=20,
    )
    observed_sizes: list[int] = []
    for _ in expected_batch_sizes:
        batch = await service.get_current_batch()
        observed_sizes.append(len(batch.entries))
        service.complete_batch(batch=batch)

    assert tuple(observed_sizes) == expected_batch_sizes
    assert provider.calls == 1
    refreshed = await service.get_current_batch()
    assert provider.calls == 2
    assert refreshed.rank_start == 1
    assert len(refreshed.entries) == min(20, universe_size)


def test_failed_required_refresh_cannot_reuse_the_completed_snapshot() -> None:
    asyncio.run(_run_failed_refresh_test())


async def _run_failed_refresh_test() -> None:
    previous_snapshot = _entries(prefix="A", count=3)
    replacement_snapshot = _entries(prefix="B", count=3)
    provider = _RankedUniverseProvider(
        outcomes=[
            previous_snapshot,
            RuntimeError("ranked refresh failed"),
            replacement_snapshot,
        ]
    )
    service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset="USDT",
        universe_limit=3,
        batch_size=3,
    )
    completed = await service.get_current_batch()
    service.complete_batch(batch=completed)
    with pytest.raises(RuntimeError, match="ranked refresh failed"):
        await service.get_current_batch()

    refreshed = await service.get_current_batch()
    assert provider.calls == 3
    assert refreshed.entries == replacement_snapshot
    assert refreshed.entries != previous_snapshot


def test_completion_requires_the_exact_current_batch_object() -> None:
    asyncio.run(_run_identity_checked_completion_test())


async def _run_identity_checked_completion_test() -> None:
    provider = _RankedUniverseProvider(outcomes=[_entries(prefix="A", count=2)])
    service = VolumeRankedDiscoveryUniverseService(
        market_service=provider,
        quote_asset="USDT",
        universe_limit=2,
        batch_size=1,
    )
    current = await service.get_current_batch()
    equal_batch = DiscoveryUniverseBatch(
        entries=current.entries,
        universe_size=current.universe_size,
        rank_start=current.rank_start,
        rank_end=current.rank_end,
    )
    with pytest.raises(ValueError, match="current discovery universe batch"):
        service.complete_batch(batch=equal_batch)
    service.complete_batch(batch=current)
    with pytest.raises(ValueError, match="current discovery universe batch"):
        service.complete_batch(batch=current)


def test_discovery_universe_batch_is_immutable_and_consistent() -> None:
    entry = _entries(prefix="A", count=1)[0]
    batch = DiscoveryUniverseBatch(
        entries=(entry,),
        universe_size=1,
        rank_start=1,
        rank_end=1,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(batch, "rank_end", 2)
    with pytest.raises(ValueError, match="size does not match"):
        DiscoveryUniverseBatch(
            entries=(entry,),
            universe_size=2,
            rank_start=1,
            rank_end=2,
        )


@pytest.mark.parametrize(
    ("universe_limit", "batch_size", "message"),
    ((0, 1, "universe limit"), (1, 0, "batch size")),
)
def test_rotation_service_rejects_invalid_bounds(
    universe_limit: int,
    batch_size: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        VolumeRankedDiscoveryUniverseService(
            market_service=_RankedUniverseProvider(outcomes=[]),
            quote_asset="USDT",
            universe_limit=universe_limit,
            batch_size=batch_size,
        )


def test_batch_may_exceed_legacy_universe_limit_without_truncating_coverage() -> None:
    service = VolumeRankedDiscoveryUniverseService(
        market_service=_RankedUniverseProvider(outcomes=[]),
        quote_asset="USDT",
        universe_limit=1,
        batch_size=20,
    )
    assert service.batch_size == 20
