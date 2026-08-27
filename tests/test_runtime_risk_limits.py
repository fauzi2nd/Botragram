"""Durable autonomous LIVE runtime risk-limit tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.config import RiskSettings
from botragram.engine import RiskEngine, TradingEngine
from botragram.enums import SignalType
from botragram.models import RuntimeRiskLimits, Signal
from botragram.repositories import RuntimeRiskLimitRepository
from botragram.services import RuntimeRiskLimitService

_NOW = datetime(2026, 8, 27, tzinfo=UTC)


@dataclass(slots=True)
class _MemoryRuntimeRiskLimitRepository(RuntimeRiskLimitRepository):
    stored: RuntimeRiskLimits | None = None
    fail_next_save: bool = False

    async def get(self) -> RuntimeRiskLimits | None:
        return self.stored

    async def save(self, *, limits: RuntimeRiskLimits) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("configured save failure")
        self.stored = limits


def _service(
    *,
    repository: _MemoryRuntimeRiskLimitRepository,
    control: TradingRuntimeControl | None = None,
) -> RuntimeRiskLimitService:
    return RuntimeRiskLimitService(
        repository=repository,
        runtime_guard=control if control is not None else TradingRuntimeControl(),
        initial_max_open_positions=5,
        initial_max_position_size_usdt=Decimal("100"),
        hard_max_open_positions=5,
        hard_max_position_size_usdt=Decimal("100"),
    )


@pytest.mark.asyncio
async def test_runtime_limits_persist_then_publish_while_paused() -> None:
    repository = _MemoryRuntimeRiskLimitRepository()
    control = TradingRuntimeControl()
    service = _service(repository=repository, control=control)
    await service.initialize()

    updated = await service.update(
        max_open_positions=2,
        max_position_size_usdt=Decimal("25"),
        updated_by="telegram:7",
    )

    assert repository.stored == updated
    assert service.get_snapshot() == updated
    assert updated.max_open_positions == 2
    assert updated.max_position_size_usdt == Decimal("25")
    assert not control.risk_limit_change_in_progress


@pytest.mark.asyncio
async def test_runtime_limits_do_not_publish_when_durable_write_fails() -> None:
    repository = _MemoryRuntimeRiskLimitRepository()
    control = TradingRuntimeControl()
    service = _service(repository=repository, control=control)
    await service.initialize()
    before = service.get_snapshot()
    repository.fail_next_save = True

    with pytest.raises(RuntimeError, match="configured save failure"):
        await service.update(
            max_open_positions=1,
            max_position_size_usdt=Decimal("10"),
            updated_by="telegram:7",
        )

    assert service.get_snapshot() == before
    assert repository.stored == before
    assert not control.risk_limit_change_in_progress


@pytest.mark.asyncio
async def test_runtime_limits_reject_update_while_runtime_is_active() -> None:
    repository = _MemoryRuntimeRiskLimitRepository()
    control = TradingRuntimeControl()
    service = _service(repository=repository, control=control)
    await service.initialize()
    control.resume_global_cycle()

    with pytest.raises(RuntimeError, match="Pause trading"):
        await service.update(
            max_open_positions=1,
            max_position_size_usdt=Decimal("10"),
            updated_by="telegram:7",
        )


@pytest.mark.asyncio
async def test_runtime_limits_reject_values_above_environment_ceiling() -> None:
    service = _service(repository=_MemoryRuntimeRiskLimitRepository())
    await service.initialize()

    with pytest.raises(ValueError, match="exceeds hard limit"):
        await service.update(
            max_open_positions=6,
            max_position_size_usdt=Decimal("10"),
            updated_by="telegram:7",
        )
    with pytest.raises(ValueError, match="exceeds hard limit"):
        await service.update(
            max_open_positions=1,
            max_position_size_usdt=Decimal("101"),
            updated_by="telegram:7",
        )


def test_risk_engine_runtime_notional_override_is_bounded_by_env_ceiling() -> None:
    engine = RiskEngine(
        settings=RiskSettings(max_position_size_usdt=Decimal("100")),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.8"),
        strategy_name="ema_cross",
        generated_at=_NOW,
    )

    result = engine.evaluate(
        signal=signal,
        account_balance=Decimal("1000"),
        max_position_size_usdt=Decimal("10"),
    )
    assert result.position.notional == Decimal("10")

    with pytest.raises(ValueError, match="configured ceiling"):
        engine.evaluate(
            signal=signal,
            account_balance=Decimal("1000"),
            max_position_size_usdt=Decimal("101"),
        )


def test_trading_engine_runtime_capacity_override_is_bounded_by_env_ceiling() -> None:
    engine = TradingEngine(
        risk_engine=RiskEngine(settings=RiskSettings(max_open_positions=5)),
    )

    assert engine._resolve_max_open_positions(runtime_limit=2) == 2
    with pytest.raises(ValueError, match="configured ceiling"):
        engine._resolve_max_open_positions(runtime_limit=6)
