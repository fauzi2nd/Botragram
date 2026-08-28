"""Operator-exit durability and transition regression tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    ExchangeEnvironment,
    ExecutionPolicy,
    MarketType,
    OperatorExitStatus,
    OperatorExitType,
    PositionSide,
    TradeMode,
)
from botragram.exceptions import OperatorExitConfirmationUnavailableError
from botragram.models import OperatorExitOperation, Position, Ticker, TradingResult
from botragram.services.operator_exit_service import OperatorExitService
from botragram.storage.memory import (
    MemoryOperatorExitRepository,
    MemoryPositionRepository,
)

_NOW = datetime(2026, 8, 28, tzinfo=UTC)


@dataclass(slots=True)
class _PaperExit:
    repository: MemoryPositionRepository
    close_calls: int = 0

    async def close_position_for_operator(
        self,
        *,
        symbol: str,
        current_price: Decimal,
        closed_at: datetime,
    ) -> TradingResult | None:
        del current_price, closed_at
        self.close_calls += 1
        await self.repository.delete(symbol=symbol)
        return None


@dataclass(slots=True)
class _PriceProvider:
    async def get_ticker(self, *, symbol: str) -> Ticker:
        return Ticker(
            symbol=symbol,
            bid_price=Decimal("99"),
            ask_price=Decimal("101"),
            last_price=Decimal("100"),
            timestamp=_NOW,
        )


@dataclass(slots=True)
class _StreamOwner:
    stop_calls: int = 0

    async def stop_all(self) -> None:
        self.stop_calls += 1


@dataclass(slots=True)
class _PolicySwitcher:
    current_policy: ExecutionPolicy = ExecutionPolicy.SINGLE_SYMBOL
    prepare_calls: int = 0
    commit_calls: int = 0
    prepared_policy: ExecutionPolicy | None = None
    committed_policy: ExecutionPolicy | None = None

    @property
    def current_execution_policy(self) -> ExecutionPolicy:
        return self.current_policy

    def available_execution_policies(self) -> tuple[ExecutionPolicy, ...]:
        return (
            ExecutionPolicy.SINGLE_SYMBOL,
            ExecutionPolicy.AUTONOMOUS_PAPER,
        )

    async def prepare_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
        allow_operator_exit: bool = False,
    ) -> bool:
        assert allow_operator_exit
        self.prepare_calls += 1
        self.prepared_policy = execution_policy
        return execution_policy is not self.current_policy

    def commit_execution_policy(
        self,
        *,
        execution_policy: ExecutionPolicy,
    ) -> None:
        self.commit_calls += 1
        self.committed_policy = execution_policy


def _position(*, symbol: str) -> Position:
    return Position(
        symbol=symbol,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


def _paper_service(
    *,
    repository: MemoryPositionRepository,
    operator_repository: MemoryOperatorExitRepository,
    runtime_control: TradingRuntimeControl,
    paper_exit: _PaperExit,
    stream_owner: _StreamOwner,
    switcher: _PolicySwitcher,
) -> OperatorExitService:
    return OperatorExitService(
        trade_mode=TradeMode.PAPER,
        market_type=MarketType.FUTURES,
        exchange_environment=ExchangeEnvironment.TESTNET,
        runtime_control=runtime_control,
        operator_exit_repository=operator_repository,
        position_repository=repository,
        market_stream_owner=stream_owner,
        execution_policy_switcher=switcher,
        paper_trading_service=paper_exit,
        market_price_provider=_PriceProvider(),
    )


@pytest.mark.asyncio
async def test_flatten_and_switch_stays_pending_until_target_session() -> None:
    repository = MemoryPositionRepository()
    await repository.save(position=_position(symbol="BTCUSDT"))
    await repository.save(position=_position(symbol="ETHUSDT"))
    operator_repository = MemoryOperatorExitRepository()
    runtime_control = TradingRuntimeControl()
    paper_exit = _PaperExit(repository=repository)
    stream_owner = _StreamOwner()
    switcher = _PolicySwitcher()
    service = _paper_service(
        repository=repository,
        operator_repository=operator_repository,
        runtime_control=runtime_control,
        paper_exit=paper_exit,
        stream_owner=stream_owner,
        switcher=switcher,
    )

    confirmation = await service.request_close_all(
        requested_by="telegram:7",
        target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
    )
    snapshot = await service.confirm(
        confirmation_id=confirmation.confirmation_id,
        requested_by="telegram:7",
        token="CONFIRM",
    )

    assert snapshot.status is OperatorExitStatus.SWITCH_PENDING
    assert paper_exit.close_calls == 2
    assert await repository.get_open_positions() == ()
    assert stream_owner.stop_calls == 1
    assert switcher.prepared_policy is ExecutionPolicy.AUTONOMOUS_PAPER
    assert switcher.committed_policy is ExecutionPolicy.AUTONOMOUS_PAPER
    assert runtime_control.operator_exit_in_progress


@pytest.mark.asyncio
async def test_switch_pending_target_session_completes_without_closing_again() -> None:
    repository = MemoryPositionRepository()
    operator_repository = MemoryOperatorExitRepository()
    operation = OperatorExitOperation(
        operation_id="operation-1",
        operation_type=OperatorExitType.FLATTEN_AND_SWITCH,
        status=OperatorExitStatus.SWITCH_PENDING,
        requested_by="telegram:7",
        target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
        created_at=_NOW,
        updated_at=_NOW,
    )
    await operator_repository.save_operation(operation=operation)
    runtime_control = TradingRuntimeControl()
    paper_exit = _PaperExit(repository=repository)
    stream_owner = _StreamOwner()
    switcher = _PolicySwitcher(current_policy=ExecutionPolicy.AUTONOMOUS_PAPER)
    service = _paper_service(
        repository=repository,
        operator_repository=operator_repository,
        runtime_control=runtime_control,
        paper_exit=paper_exit,
        stream_owner=stream_owner,
        switcher=switcher,
    )
    await service.initialize()

    await service.recover_until_safe()

    stored = await operator_repository.get_operation(operation_id="operation-1")
    assert stored is not None
    assert stored.status is OperatorExitStatus.COMPLETE
    assert paper_exit.close_calls == 0
    assert switcher.prepare_calls == 1
    assert switcher.commit_calls == 0
    assert not runtime_control.operator_exit_in_progress


@pytest.mark.asyncio
async def test_switch_pending_old_session_hands_off_once_and_returns() -> None:
    repository = MemoryPositionRepository()
    operator_repository = MemoryOperatorExitRepository()
    operation = OperatorExitOperation(
        operation_id="operation-1",
        operation_type=OperatorExitType.FLATTEN_AND_SWITCH,
        status=OperatorExitStatus.SWITCH_PENDING,
        requested_by="telegram:7",
        target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
        created_at=_NOW,
        updated_at=_NOW,
    )
    await operator_repository.save_operation(operation=operation)
    runtime_control = TradingRuntimeControl()
    paper_exit = _PaperExit(repository=repository)
    stream_owner = _StreamOwner()
    switcher = _PolicySwitcher()
    service = _paper_service(
        repository=repository,
        operator_repository=operator_repository,
        runtime_control=runtime_control,
        paper_exit=paper_exit,
        stream_owner=stream_owner,
        switcher=switcher,
    )
    await service.initialize()

    await service.recover_until_safe()

    stored = await operator_repository.get_operation(operation_id="operation-1")
    assert stored is not None
    assert stored.status is OperatorExitStatus.SWITCH_PENDING
    assert switcher.prepare_calls == 1
    assert switcher.commit_calls == 1
    assert runtime_control.operator_exit_in_progress


@pytest.mark.asyncio
async def test_switch_pending_operation_blocks_new_reservation() -> None:
    repository = MemoryOperatorExitRepository()
    await repository.save_operation(
        operation=OperatorExitOperation(
            operation_id="operation-1",
            operation_type=OperatorExitType.FLATTEN_AND_SWITCH,
            status=OperatorExitStatus.SWITCH_PENDING,
            requested_by="telegram:7",
            target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )

    reserved = await repository.reserve_operation(
        operation=OperatorExitOperation(
            operation_id="operation-2",
            operation_type=OperatorExitType.CLOSE_ALL,
            status=OperatorExitStatus.FLATTENING,
            requested_by="telegram:8",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )

    assert not reserved


@pytest.mark.asyncio
async def test_close_all_rejects_exposure_added_after_confirmation() -> None:
    """Never close a symbol that was outside the explicit confirmation scope."""
    repository = MemoryPositionRepository()
    await repository.save(position=_position(symbol="BTCUSDT"))
    operator_repository = MemoryOperatorExitRepository()
    runtime_control = TradingRuntimeControl()
    paper_exit = _PaperExit(repository=repository)
    service = _paper_service(
        repository=repository,
        operator_repository=operator_repository,
        runtime_control=runtime_control,
        paper_exit=paper_exit,
        stream_owner=_StreamOwner(),
        switcher=_PolicySwitcher(),
    )
    confirmation = await service.request_close_all(requested_by="telegram:7")
    assert confirmation.symbols == ("BTCUSDT",)

    await repository.save(position=_position(symbol="ETHUSDT"))
    snapshot = await service.confirm(
        confirmation_id=confirmation.confirmation_id,
        requested_by="telegram:7",
        token="CONFIRM",
    )
    await service.close()

    stored = await operator_repository.get_operation(
        operation_id=confirmation.confirmation_id
    )
    assert stored is not None
    assert stored.authorized_symbols == ("BTCUSDT",)
    assert stored.status is OperatorExitStatus.RECOVERY_REQUIRED
    assert snapshot.status is OperatorExitStatus.RECOVERY_REQUIRED
    assert paper_exit.close_calls == 0
    assert tuple(
        sorted(position.symbol for position in await repository.get_open_positions())
    ) == ("BTCUSDT", "ETHUSDT")
    assert runtime_control.operator_exit_in_progress


@pytest.mark.asyncio
async def test_confirmation_requires_exact_explicit_token() -> None:
    repository = MemoryPositionRepository()
    await repository.save(position=_position(symbol="BTCUSDT"))
    operator_repository = MemoryOperatorExitRepository()
    runtime_control = TradingRuntimeControl()
    paper_exit = _PaperExit(repository=repository)
    service = _paper_service(
        repository=repository,
        operator_repository=operator_repository,
        runtime_control=runtime_control,
        paper_exit=paper_exit,
        stream_owner=_StreamOwner(),
        switcher=_PolicySwitcher(),
    )
    confirmation = await service.request_close_all(requested_by="telegram:7")

    with pytest.raises(RuntimeError, match="confirmation token is invalid"):
        await service.confirm(
            confirmation_id=confirmation.confirmation_id,
            requested_by="telegram:7",
            token="WRONG",
        )

    assert paper_exit.close_calls == 0
    assert await repository.get_open_positions()
    await service.cancel_confirmation(
        confirmation_id=confirmation.confirmation_id,
        requested_by="telegram:7",
    )
    assert not runtime_control.operator_exit_in_progress


@pytest.mark.asyncio
async def test_rebuilt_session_rejects_stale_confirmation_without_mutation() -> None:
    """Treat a callback from the prior in-process session as expired UI state."""
    repository = MemoryPositionRepository()
    operator_repository = MemoryOperatorExitRepository()
    runtime_control = TradingRuntimeControl()
    service = _paper_service(
        repository=repository,
        operator_repository=operator_repository,
        runtime_control=runtime_control,
        paper_exit=_PaperExit(repository=repository),
        stream_owner=_StreamOwner(),
        switcher=_PolicySwitcher(),
    )

    with pytest.raises(OperatorExitConfirmationUnavailableError):
        await service.confirm(
            confirmation_id="prior-session-confirmation",
            requested_by="telegram:7",
            token="CONFIRM",
        )

    assert await operator_repository.get_latest_operation() is None
    assert not runtime_control.operator_exit_in_progress
