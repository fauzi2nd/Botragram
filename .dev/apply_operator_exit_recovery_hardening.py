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

    path = root / "botragram/models/operator_exit.py"
    text = path.read_text(encoding="utf-8")
    old = '''    symbol: str | None = None\n    target_execution_policy: ExecutionPolicy | None = None\n    failure_reason: str | None = None\n'''
    new = '''    symbol: str | None = None\n    authorized_symbols: tuple[str, ...] = ()\n    target_execution_policy: ExecutionPolicy | None = None\n    failure_reason: str | None = None\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/storage/sqlite/migrations.py"
    text = path.read_text(encoding="utf-8")
    old = '''        CREATE INDEX IF NOT EXISTS idx_operator_exit_attempts_status\n        ON operator_exit_attempts (status, created_at);\n        \"\"\",\n    ),\n)\n'''
    new = '''        CREATE INDEX IF NOT EXISTS idx_operator_exit_attempts_status\n        ON operator_exit_attempts (status, created_at);\n        \"\"\",\n    ),\n    _Migration(\n        version=18,\n        script=\"\"\"\n        ALTER TABLE operator_exit_operations\n        ADD COLUMN authorized_symbols TEXT NOT NULL DEFAULT '';\n        \"\"\",\n    ),\n)\n'''
    path.write_text(replace_once(text, old, new, label=str(path)), encoding="utf-8")

    path = root / "botragram/storage/sqlite/operator_exit_repository.py"
    text = path.read_text(encoding="utf-8")
    old = '''_OPERATION_COLUMNS = \"\"\"operation_id, operation_type, status, requested_by,\nsymbol, target_execution_policy, failure_reason, created_at, updated_at\"\"\"\n'''
    new = '''_OPERATION_COLUMNS = \"\"\"operation_id, operation_type, status, requested_by,\nsymbol, authorized_symbols, target_execution_policy, failure_reason, created_at, updated_at\"\"\"\n'''
    text = replace_once(text, old, new, label=f"{path}: columns")
    text = replace_once(
        text,
        '''({_OPERATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n''',
        '''({_OPERATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n''',
        label=f"{path}: upsert placeholders",
    )
    text = replace_once(
        text,
        '''SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?\nWHERE NOT EXISTS (\n''',
        '''SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?\nWHERE NOT EXISTS (\n''',
        label=f"{path}: reserve placeholders",
    )
    old = '''            operation.requested_by,\n            operation.symbol,\n            (\n                operation.target_execution_policy.value\n'''
    new = '''            operation.requested_by,\n            operation.symbol,\n            \"|\".join(operation.authorized_symbols),\n            (\n                operation.target_execution_policy.value\n'''
    text = replace_once(text, old, new, label=f"{path}: params")
    old = '''            requested_by=str(row[\"requested_by\"]),\n            symbol=str(row[\"symbol\"]) if row[\"symbol\"] is not None else None,\n            target_execution_policy=(\n'''
    new = '''            requested_by=str(row[\"requested_by\"]),\n            symbol=str(row[\"symbol\"]) if row[\"symbol\"] is not None else None,\n            authorized_symbols=tuple(\n                symbol\n                for symbol in str(row[\"authorized_symbols\"]).split(\"|\")\n                if symbol\n            ),\n            target_execution_policy=(\n'''
    text = replace_once(text, old, new, label=f"{path}: row mapping")
    path.write_text(text, encoding="utf-8")

    path = root / "botragram/services/operator_exit_service.py"
    text = path.read_text(encoding="utf-8")
    old = '''            requested_by=pending.requested_by,\n            symbol=pending.symbol,\n            target_execution_policy=challenge.target_execution_policy,\n'''
    new = '''            requested_by=pending.requested_by,\n            symbol=pending.symbol,\n            authorized_symbols=challenge.symbols,\n            target_execution_policy=challenge.target_execution_policy,\n'''
    text = replace_once(text, old, new, label=f"{path}: persist scope")

    old = '''            positions = tuple(\n                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())\n            )\n            targets = self._operation_targets(operation=operation, positions=positions)\n            if not targets:\n                return\n'''
    new = '''            positions = tuple(\n                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())\n            )\n            self._require_confirmed_portfolio_scope(\n                operation=operation,\n                positions=positions,\n            )\n            targets = self._operation_targets(operation=operation, positions=positions)\n            if not targets:\n                return\n'''
    text = replace_once(text, old, new, label=f"{path}: paper scope")

    old = '''            positions = tuple(\n                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())\n            )\n            targets = self._operation_targets(operation=operation, positions=positions)\n            if not targets:\n                await self._reconcile_live_runtime()\n                return\n'''
    new = '''            positions = tuple(\n                sorted(await self.get_positions(), key=lambda item: item.symbol.upper())\n            )\n            self._require_confirmed_portfolio_scope(\n                operation=operation,\n                positions=positions,\n            )\n            targets = self._operation_targets(operation=operation, positions=positions)\n            if not targets:\n                await self._reconcile_live_runtime()\n                return\n'''
    text = replace_once(text, old, new, label=f"{path}: live scope")

    old = '''        positions = await self.get_positions()\n        targets = self._operation_targets(operation=operation, positions=positions)\n        if targets:\n            raise _RecoveryPending(\"Authoritative target exposure remains open\")\n'''
    new = '''        positions = await self.get_positions()\n        self._require_confirmed_portfolio_scope(\n            operation=operation,\n            positions=positions,\n        )\n        targets = self._operation_targets(operation=operation, positions=positions)\n        if targets:\n            raise _RecoveryPending(\"Authoritative target exposure remains open\")\n'''
    text = replace_once(text, old, new, label=f"{path}: completion scope")

    old = '''    @staticmethod\n    def _operation_targets(\n        *,\n        operation: OperatorExitOperation,\n        positions: Sequence[Position],\n    ) -> tuple[Position, ...]:\n        \"\"\"Return the authoritative positions covered by one confirmed operation.\"\"\"\n        if operation.operation_type is OperatorExitType.CLOSE_POSITION:\n            return tuple(\n                position\n                for position in positions\n                if position.symbol.upper() == operation.symbol\n            )\n        return tuple(positions)\n\n    @staticmethod\n    def _validate_exit_order(\n'''
    new = '''    @classmethod\n    def _operation_targets(\n        cls,\n        *,\n        operation: OperatorExitOperation,\n        positions: Sequence[Position],\n    ) -> tuple[Position, ...]:\n        \"\"\"Return only positions inside the exact durable confirmation scope.\"\"\"\n        if not positions:\n            return ()\n        authorized = cls._get_authorized_symbols(operation=operation)\n        return tuple(\n            position\n            for position in positions\n            if position.symbol.upper() in authorized\n        )\n\n    @classmethod\n    def _require_confirmed_portfolio_scope(\n        cls,\n        *,\n        operation: OperatorExitOperation,\n        positions: Sequence[Position],\n    ) -> None:\n        \"\"\"Block broad exits when exposure appears outside confirmed scope.\"\"\"\n        if (\n            not positions\n            or operation.operation_type is OperatorExitType.CLOSE_POSITION\n        ):\n            return\n        authorized = cls._get_authorized_symbols(operation=operation)\n        unconfirmed = tuple(\n            sorted(\n                {position.symbol.upper() for position in positions}.difference(\n                    authorized\n                )\n            )\n        )\n        if unconfirmed:\n            raise _RecoveryPending(\n                \"Authoritative exposure appeared outside the confirmed \"\n                f\"operator-exit scope: {', '.join(unconfirmed)}\"\n            )\n\n    @staticmethod\n    def _get_authorized_symbols(\n        *,\n        operation: OperatorExitOperation,\n    ) -> frozenset[str]:\n        \"\"\"Return durable scope, with a safe legacy fallback for one symbol.\"\"\"\n        authorized = frozenset(\n            symbol.strip().upper()\n            for symbol in operation.authorized_symbols\n            if symbol.strip()\n        )\n        if authorized:\n            return authorized\n        if (\n            operation.operation_type is OperatorExitType.CLOSE_POSITION\n            and operation.symbol is not None\n            and operation.symbol.strip()\n        ):\n            return frozenset({operation.symbol.strip().upper()})\n        raise _RecoveryPending(\n            \"Durable operator-exit confirmation scope is unavailable\"\n        )\n\n    @staticmethod\n    def _validate_exit_order(\n'''
    text = replace_once(text, old, new, label=f"{path}: target scope helpers")
    path.write_text(text, encoding="utf-8")

    path = root / "tests/test_operator_exit_repository.py"
    text = path.read_text(encoding="utf-8")
    old = '''        assert await manager.initialize() == 17\n        after = await database.fetch_all(\n'''
    new = '''        assert await manager.initialize(target_version=17) == 17\n        after = await database.fetch_all(\n'''
    text = replace_once(text, old, new, label=f"{path}: migration 17 target")
    old = '''        assert tuple(str(row[\"name\"]) for row in after) == (\n            \"operator_exit_attempts\",\n            \"operator_exit_operations\",\n        )\n    finally:\n'''
    new = '''        assert tuple(str(row[\"name\"]) for row in after) == (\n            \"operator_exit_attempts\",\n            \"operator_exit_operations\",\n        )\n\n        assert await manager.initialize() == 18\n        columns = await database.fetch_all(\n            statement=\"PRAGMA table_info(operator_exit_operations);\"\n        )\n        assert \"authorized_symbols\" in {str(row[\"name\"]) for row in columns}\n    finally:\n'''
    text = replace_once(text, old, new, label=f"{path}: migration 18 assertion")
    old = '''            requested_by=\"telegram:7\",\n            target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,\n            created_at=_NOW,\n'''
    new = '''            requested_by=\"telegram:7\",\n            authorized_symbols=(\"BTCUSDT\", \"ETHUSDT\"),\n            target_execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER,\n            created_at=_NOW,\n'''
    text = replace_once(text, old, new, label=f"{path}: roundtrip scope")
    path.write_text(text, encoding="utf-8")

    path = root / "tests/test_operator_exit_service.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''@pytest.mark.asyncio\nasync def test_confirmation_requires_exact_explicit_token() -> None:\n'''
    if anchor not in text:
        raise RuntimeError(f"{path}: confirmation test anchor missing")
    insert_at = text.index(anchor)
    test = '''@pytest.mark.asyncio\nasync def test_close_all_rejects_exposure_added_after_confirmation() -> None:\n    \"\"\"Never close a symbol that was outside the explicit confirmation scope.\"\"\"\n    repository = MemoryPositionRepository()\n    await repository.save(position=_position(symbol=\"BTCUSDT\"))\n    operator_repository = MemoryOperatorExitRepository()\n    runtime_control = TradingRuntimeControl()\n    paper_exit = _PaperExit(repository=repository)\n    service = _paper_service(\n        repository=repository,\n        operator_repository=operator_repository,\n        runtime_control=runtime_control,\n        paper_exit=paper_exit,\n        stream_owner=_StreamOwner(),\n        switcher=_PolicySwitcher(),\n    )\n    confirmation = await service.request_close_all(requested_by=\"telegram:7\")\n    assert confirmation.symbols == (\"BTCUSDT\",)\n\n    await repository.save(position=_position(symbol=\"ETHUSDT\"))\n    snapshot = await service.confirm(\n        confirmation_id=confirmation.confirmation_id,\n        requested_by=\"telegram:7\",\n        token=\"CONFIRM\",\n    )\n    await service.close()\n\n    stored = await operator_repository.get_operation(\n        operation_id=confirmation.confirmation_id\n    )\n    assert stored is not None\n    assert stored.authorized_symbols == (\"BTCUSDT\",)\n    assert stored.status is OperatorExitStatus.RECOVERY_REQUIRED\n    assert snapshot.status is OperatorExitStatus.RECOVERY_REQUIRED\n    assert paper_exit.close_calls == 0\n    assert tuple(\n        sorted(position.symbol for position in await repository.get_open_positions())\n    ) == (\"BTCUSDT\", \"ETHUSDT\")\n    assert runtime_control.operator_exit_in_progress\n\n\n'''
    text = text[:insert_at] + test + text[insert_at:]
    path.write_text(text, encoding="utf-8")

    print("durable operator-exit confirmation scope applied")


if __name__ == "__main__":
    main()
