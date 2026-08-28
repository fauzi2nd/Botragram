from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_operator_exit_recovery_hardening.py TARGET")
    root = Path(sys.argv[1])

    path = root / "botragram/exchanges/base/client.py"
    text = path.read_text(encoding="utf-8")
    old = '''    @abstractmethod\n    async def close_position(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str | None = None,\n    ) -> Order:\n        \"\"\"Close the active position with an optional durable client identity.\"\"\"\n\n    @abstractmethod\n    async def close_all_positions(self) -> Sequence[Order]:\n'''
    new = '''    @abstractmethod\n    async def close_position(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str | None = None,\n    ) -> Order:\n        \"\"\"Close the active position with an optional durable client identity.\"\"\"\n\n    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        \"\"\"Submit one close from an already-authoritative position snapshot.\n\n        Connectors that cannot guarantee a single mutation without a second\n        position lookup fail closed. Futures connectors may override this for\n        durable operator-exit workflows.\n        \"\"\"\n        del position, client_order_id\n        raise NotImplementedError(\n            \"Exact position-snapshot closing is not supported\"\n        )\n\n    @abstractmethod\n    async def close_all_positions(self) -> Sequence[Order]:\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/exchanges/binance/futures_client.py"
    text = path.read_text(encoding="utf-8")
    old = '''    async def close_all_positions(self) -> Sequence[Order]:\n        \"\"\"Close all active one-way Futures positions.\"\"\"\n        positions = await self.get_positions()\n        closed: list[Order] = []\n\n        for position in positions:\n            closed.append(await self._close_position(position))\n\n        return tuple(closed)\n\n    def _build_order_params(\n'''
    new = '''    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        \"\"\"Submit one reduce-only close from a durable authoritative snapshot.\"\"\"\n        if not client_order_id.strip():\n            raise ValueError(\"Exact close requires a durable client order identity\")\n        return await self._close_position(\n            position,\n            client_order_id=client_order_id,\n        )\n\n    async def close_all_positions(self) -> Sequence[Order]:\n        \"\"\"Close all active one-way Futures positions.\"\"\"\n        positions = await self.get_positions()\n        closed: list[Order] = []\n\n        for position in positions:\n            closed.append(await self._close_position(position))\n\n        return tuple(closed)\n\n    def _build_order_params(\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/enums/operator_exit_attempt_status.py"
    text = path.read_text(encoding="utf-8")
    old = '''    RECONCILING = \"reconciling\"\n    COMPLETED = \"completed\"\n    REJECTED = \"rejected\"\n'''
    new = '''    RECONCILING = \"reconciling\"\n    COMPLETED = \"completed\"\n    REJECTED = \"rejected\"\n    PARTIAL = \"partial\"\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/storage/memory/operator_exit_repository.py"
    text = path.read_text(encoding="utf-8")
    old = '''                not in {\n                    OperatorExitAttemptStatus.COMPLETED,\n                    OperatorExitAttemptStatus.REJECTED,\n                }\n'''
    new = '''                not in {\n                    OperatorExitAttemptStatus.COMPLETED,\n                    OperatorExitAttemptStatus.REJECTED,\n                    OperatorExitAttemptStatus.PARTIAL,\n                }\n'''
    if text.count(old) != 2:
        raise RuntimeError(f"{path}: expected two terminal-status sets")
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")

    path = root / "botragram/storage/sqlite/operator_exit_repository.py"
    text = path.read_text(encoding="utf-8")
    old = '''WHERE NOT EXISTS (\n    SELECT 1 FROM operator_exit_attempts WHERE status NOT IN (?, ?)\n);\"\"\",\n            parameters=(\n                *self._attempt_params(attempt),\n                OperatorExitAttemptStatus.COMPLETED.value,\n                OperatorExitAttemptStatus.REJECTED.value,\n            ),\n'''
    new = '''WHERE NOT EXISTS (\n    SELECT 1 FROM operator_exit_attempts WHERE status NOT IN (?, ?, ?)\n);\"\"\",\n            parameters=(\n                *self._attempt_params(attempt),\n                OperatorExitAttemptStatus.COMPLETED.value,\n                OperatorExitAttemptStatus.REJECTED.value,\n                OperatorExitAttemptStatus.PARTIAL.value,\n            ),\n'''
    text = replace_once(text, old, new, label=f"{path}: reserve")
    old = '''                \"WHERE status NOT IN (?, ?) ORDER BY created_at ASC;\"\n            ),\n            parameters=(\n                OperatorExitAttemptStatus.COMPLETED.value,\n                OperatorExitAttemptStatus.REJECTED.value,\n            ),\n'''
    new = '''                \"WHERE status NOT IN (?, ?, ?) ORDER BY created_at ASC;\"\n            ),\n            parameters=(\n                OperatorExitAttemptStatus.COMPLETED.value,\n                OperatorExitAttemptStatus.REJECTED.value,\n                OperatorExitAttemptStatus.PARTIAL.value,\n            ),\n'''
    text = replace_once(text, old, new, label=f"{path}: incomplete")
    path.write_text(text, encoding="utf-8")

    path = root / "botragram/services/operator_exit_service.py"
    text = path.read_text(encoding="utf-8")
    old = '''    async def close_position(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str | None = None,\n    ) -> Order:\n        \"\"\"Submit one reduce-only close with a durable client identity.\"\"\"\n        ...\n'''
    new = '''    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        \"\"\"Submit one reduce-only close from the durable position snapshot.\"\"\"\n        ...\n'''
    text = replace_once(text, old, new, label=f"{path}: protocol")
    old = '''class _ExitRejected(RuntimeError):\n    \"\"\"Indicate a proven terminal close rejection without claiming success.\"\"\"\n\n\n@dataclass(slots=True, kw_only=True)\n'''
    new = '''class _ExitRejected(RuntimeError):\n    \"\"\"Indicate a proven terminal close rejection without claiming success.\"\"\"\n\n\nclass _ExitTerminalPartial(RuntimeError):\n    \"\"\"Indicate a terminal close that executed only part of the durable intent.\"\"\"\n\n\n@dataclass(slots=True, kw_only=True)\n'''
    text = replace_once(text, old, new, label=f"{path}: partial exception")
    old = '''        except _ExitRejected as error:\n            if not await self._handle_proven_rejection(\n                operation=operation,\n                reason=str(error),\n            ):\n                self._start_background_recovery()\n        except Exception as error:\n            await self._mark_recovery_required(\n                operation=operation,\n                reason=str(error),\n            )\n            self._start_background_recovery()\n'''
    new = '''        except (_ExitRejected, _ExitTerminalPartial) as error:\n            if not await self._handle_proven_terminal_failure(\n                operation=operation,\n                reason=str(error),\n            ):\n                self._start_background_recovery()\n        except Exception as error:\n            try:\n                await self._mark_recovery_required(\n                    operation=operation,\n                    reason=str(error),\n                )\n            finally:\n                self._start_background_recovery()\n'''
    text = replace_once(text, old, new, label=f"{path}: confirm handling")
    old = '''            except _ExitRejected as error:\n                if await self._handle_proven_rejection(\n                    operation=operation,\n                    reason=str(error),\n                ):\n                    return\n                recovery_attempt += 1\n'''
    new = '''            except (_ExitRejected, _ExitTerminalPartial) as error:\n                if await self._handle_proven_terminal_failure(\n                    operation=operation,\n                    reason=str(error),\n                ):\n                    return\n                recovery_attempt += 1\n'''
    text = replace_once(text, old, new, label=f"{path}: recovery handling")
    old = '''                order = await exchange.close_position(\n                    symbol=attempt.symbol,\n                    client_order_id=attempt.client_order_id,\n                )\n'''
    new = '''                order = await exchange.close_position_exact(\n                    position=authoritative,\n                    client_order_id=attempt.client_order_id,\n                )\n'''
    text = replace_once(text, old, new, label=f"{path}: exact close")

    partial_block = '''                if order.executed_quantity != Decimal(\"0\"):\n                    await self.operator_exit_repository.save_attempt(\n                        attempt=replace(\n                            attempt,\n                            status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,\n                            exchange_order_id=order.order_id,\n                            failure_reason=\"Terminal close has partial execution\",\n                            updated_at=datetime.now(UTC),\n                        )\n                    )\n                    raise _RecoveryPending(\n                        \"Terminal operator close has partial execution\"\n                    )\n'''
    partial_new = '''                if order.executed_quantity != Decimal(\"0\"):\n                    await self.operator_exit_repository.save_attempt(\n                        attempt=replace(\n                            attempt,\n                            status=OperatorExitAttemptStatus.PARTIAL,\n                            exchange_order_id=order.order_id,\n                            failure_reason=\"Terminal close has partial execution\",\n                            updated_at=datetime.now(UTC),\n                        )\n                    )\n                    raise _ExitTerminalPartial(\n                        \"Operator close terminated after partial execution\"\n                    )\n'''
    if text.count(partial_block) != 1:
        raise RuntimeError(f"{path}: expected one submit partial block")
    text = text.replace(partial_block, partial_new, 1)

    partial_block = '''                if order.executed_quantity != Decimal(\"0\"):\n                    await self.operator_exit_repository.save_attempt(\n                        attempt=replace(\n                            reconciling,\n                            status=OperatorExitAttemptStatus.RECOVERY_REQUIRED,\n                            exchange_order_id=order.order_id,\n                            failure_reason=\"Terminal close has partial execution\",\n                            updated_at=datetime.now(UTC),\n                        )\n                    )\n                    raise _RecoveryPending(\n                        \"Terminal operator close has partial execution\"\n                    )\n'''
    partial_new = '''                if order.executed_quantity != Decimal(\"0\"):\n                    await self.operator_exit_repository.save_attempt(\n                        attempt=replace(\n                            reconciling,\n                            status=OperatorExitAttemptStatus.PARTIAL,\n                            exchange_order_id=order.order_id,\n                            failure_reason=\"Terminal close has partial execution\",\n                            updated_at=datetime.now(UTC),\n                        )\n                    )\n                    raise _ExitTerminalPartial(\n                        \"Operator close terminated after partial execution\"\n                    )\n'''
    text = replace_once(text, partial_block, partial_new, label=f"{path}: recover partial")
    old = '''    async def _handle_proven_rejection(\n        self,\n        *,\n        operation: OperatorExitOperation,\n        reason: str,\n    ) -> bool:\n        \"\"\"Restore canonical protection before releasing a proven rejected close.\"\"\"\n'''
    new = '''    async def _handle_proven_terminal_failure(\n        self,\n        *,\n        operation: OperatorExitOperation,\n        reason: str,\n    ) -> bool:\n        \"\"\"Restore canonical protection before releasing a proven terminal close.\"\"\"\n'''
    text = replace_once(text, old, new, label=f"{path}: handler rename")
    path.write_text(text, encoding="utf-8")

    path = root / "tests/test_binance_futures.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''@pytest.mark.asyncio\nasync def test_futures_close_position_is_reduce_only() -> None:\n'''
    if anchor not in text:
        raise RuntimeError(f"{path}: close-position test anchor missing")
    insert_at = text.index(anchor)
    new_test = '''@pytest.mark.asyncio\nasync def test_futures_exact_close_uses_snapshot_without_position_lookup() -> None:\n    rest = _FakeRestClient()\n    client = BinanceFuturesClient(rest=rest)\n    position = _position(symbol=\"BTCUSDT\")\n    rest.responses[(\"POST\", \"/fapi/v1/order\")] = _order_payload(\n        client_order_id=\"bop-exact\",\n        side=\"SELL\",\n        quantity=\"1\",\n        executed_quantity=\"1\",\n        status=\"FILLED\",\n    )\n\n    order = await client.close_position_exact(\n        position=position,\n        client_order_id=\"bop-exact\",\n    )\n\n    assert order.client_order_id == \"bop-exact\"\n    assert [call[0] for call in rest.calls] == [\"POST\"]\n    assert rest.calls[0][2][\"reduceOnly\"] == \"true\"\n\n\n'''
    text = text[:insert_at] + new_test + text[insert_at:]
    path.write_text(text, encoding="utf-8")

    path = root / "tests/test_operator_exit_service.py"
    text = path.read_text(encoding="utf-8")
    old = '''from botragram.enums import (\n    ExchangeEnvironment,\n    ExecutionPolicy,\n    MarketType,\n    OperatorExitStatus,\n    OperatorExitType,\n    PositionSide,\n    TradeMode,\n)\n'''
    new = '''from botragram.enums import (\n    ExchangeEnvironment,\n    ExecutionPolicy,\n    MarketType,\n    OperatorExitAttemptStatus,\n    OperatorExitStatus,\n    OperatorExitType,\n    OrderSide,\n    OrderStatus,\n    OrderType,\n    PositionSide,\n    TradeMode,\n)\n'''
    text = replace_once(text, old, new, label=f"{path}: imports")
    old = '''from botragram.models import OperatorExitOperation, Position, Ticker, TradingResult\n'''
    new = '''from botragram.models import (\n    OperatorExitOperation,\n    Order,\n    Position,\n    Ticker,\n    TradingResult,\n)\n'''
    text = replace_once(text, old, new, label=f"{path}: model imports")
    append = '''\n\n@dataclass(slots=True)\nclass _LiveAuthority:\n    position: Position | None\n\n    async def get_all(self, *, synchronize: bool = False) -> tuple[Position, ...]:\n        del synchronize\n        return () if self.position is None else (self.position,)\n\n    async def observe(self, *, symbol: str) -> Position | None:\n        del symbol\n        return self.position\n\n\n@dataclass(slots=True)\nclass _LiveExchange:\n    order: Order\n    exact_calls: int = 0\n\n    async def close_position_exact(\n        self,\n        *,\n        position: Position,\n        client_order_id: str,\n    ) -> Order:\n        del position, client_order_id\n        self.exact_calls += 1\n        return self.order\n\n    async def get_order_by_client_order_id(\n        self,\n        *,\n        symbol: str,\n        client_order_id: str,\n    ) -> Order:\n        del symbol, client_order_id\n        return self.order\n\n\n@dataclass(slots=True)\nclass _NoopReconciler:\n    runtime: TradingRuntimeControl\n    calls: int = 0\n\n    async def reconcile_context(self) -> object | None:\n        self.calls += 1\n        self.runtime.set_position_protection_ready(True)\n        return object()\n\n\n@pytest.mark.asyncio\nasync def test_terminal_partial_operator_close_becomes_terminal_failed_state() -> None:\n    repository = MemoryPositionRepository()\n    position = _position(symbol=\"BTCUSDT\")\n    await repository.save(position=position)\n    operator_repository = MemoryOperatorExitRepository()\n    runtime = TradingRuntimeControl()\n    runtime.pause()\n    runtime.restore_configuration(\n        symbol=\"BTCUSDT\",\n        interval=position.interval,\n        strategy_type=position.strategy_type,\n    )\n    runtime.set_position_protection_ready(True)\n    authority = _LiveAuthority(position=position)\n    order = Order(\n        order_id=\"exit-1\",\n        client_order_id=None,\n        symbol=\"BTCUSDT\",\n        side=OrderSide.SELL,\n        order_type=OrderType.MARKET,\n        status=OrderStatus.CANCELED,\n        quantity=Decimal(\"1\"),\n        executed_quantity=Decimal(\"0.4\"),\n        created_at=_NOW,\n        updated_at=_NOW,\n    )\n    exchange = _LiveExchange(order=order)\n    reconciler = _NoopReconciler(runtime=runtime)\n\n    service = OperatorExitService(\n        trade_mode=TradeMode.LIVE,\n        market_type=MarketType.FUTURES,\n        exchange_environment=ExchangeEnvironment.TESTNET,\n        runtime_control=runtime,\n        operator_exit_repository=operator_repository,\n        position_repository=repository,\n        market_stream_owner=_StreamOwner(),\n        live_position_service=authority,\n        live_exchange=exchange,\n        submission_attempt_repository=MemorySubmissionAttemptRepository(),\n        closed_lifecycle_service=cast(ClosedPositionLifecycleService, object()),\n        live_runtime_reconciler=reconciler,\n        lifecycle_coordinator=LivePositionLifecycleCoordinator(),\n    )\n\n    now = datetime.now(UTC)\n    operation = OperatorExitOperation(\n        operation_id=\"operation-partial\",\n        operation_type=OperatorExitType.CLOSE_POSITION,\n        status=OperatorExitStatus.FLATTENING,\n        requested_by=\"telegram:7\",\n        symbol=\"BTCUSDT\",\n        created_at=now,\n        updated_at=now,\n    )\n    await operator_repository.save_operation(operation=operation)\n    runtime.begin_operator_exit()\n\n    attempt = OperatorExitAttempt(\n        client_order_id=\"bop-partial\",\n        operation_id=operation.operation_id,\n        symbol=\"BTCUSDT\",\n        position_side=PositionSide.LONG,\n        quantity=Decimal(\"1\"),\n        status=OperatorExitAttemptStatus.ACKNOWLEDGED,\n        created_at=now,\n        updated_at=now,\n    )\n    await operator_repository.save_attempt(attempt=attempt)\n\n    await service.recover_until_safe()\n\n    stored_operation = await operator_repository.get_operation(\n        operation_id=operation.operation_id\n    )\n    stored_attempt = await operator_repository.get_attempt_by_client_order_id(\n        client_order_id=attempt.client_order_id\n    )\n    assert stored_operation is not None\n    assert stored_operation.status is OperatorExitStatus.FAILED\n    assert stored_attempt is not None\n    assert stored_attempt.status is OperatorExitAttemptStatus.PARTIAL\n    assert reconciler.calls == 1\n    assert not runtime.operator_exit_in_progress\n\n'''
    # The live regression requires project types already used elsewhere in tests.
    extra_imports = '''from typing import cast\n\n'''
    if "from typing import cast\n" not in text:
        text = replace_once(text, "from decimal import Decimal\n\n", "from decimal import Decimal\nfrom typing import cast\n\n", label=f"{path}: cast import")
    extra_models = '''    OperatorExitAttempt,\n'''
    text = text.replace("    OperatorExitOperation,\n", extra_models + "    OperatorExitOperation,\n", 1)
    storage_old = '''from botragram.storage.memory import (\n    MemoryOperatorExitRepository,\n    MemoryPositionRepository,\n)\n'''
    storage_new = '''from botragram.storage.memory import (\n    MemoryOperatorExitRepository,\n    MemoryPositionRepository,\n    MemorySubmissionAttemptRepository,\n)\nfrom botragram.services.closed_position_lifecycle_service import (\n    ClosedPositionLifecycleService,\n)\nfrom botragram.services.live_position_lifecycle_coordinator import (\n    LivePositionLifecycleCoordinator,\n)\n'''
    text = replace_once(text, storage_old, storage_new, label=f"{path}: storage imports")
    text += append
    path.write_text(text, encoding="utf-8")

    print("operator-exit recovery hardening applied")


if __name__ == "__main__":
    main()
