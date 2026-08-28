from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

EXPECTED_HEAD = "8639a6922981b9e1facecd52aec2c60858567bd8"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def replace_once(root: Path, path: str, old: str, new: str) -> None:
    file_path = root / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one replacement in {path}, found {count}: "
            f"{old.splitlines()[0]!r}"
        )
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def write_new(root: Path, path: str, content: str) -> None:
    file_path = root / path
    if file_path.exists():
        if file_path.read_text(encoding="utf-8") == content:
            return
        raise RuntimeError(f"Refusing to overwrite unexpected existing file: {path}")
    file_path.write_text(content, encoding="utf-8", newline="\n")


def patch_dependency_provider(root: Path) -> None:
    path = "botragram/app/dependency_provider.py"
    replace_once(
        root,
        path,
        "    ExecutionAuthorizationRepository,\n    OrderRepository,\n",
        "    ExecutionAuthorizationRepository,\n    OperatorExitRepository,\n    OrderRepository,\n",
    )
    replace_once(
        root,
        path,
        "    OpportunityDiscoveryService,\n    OrderService,\n",
        "    OpportunityDiscoveryService,\n    OperatorExitService,\n    OrderService,\n",
    )
    replace_once(
        root,
        path,
        "    SQLiteMigrationManager,\n    SQLiteOrderRepository,\n",
        "    SQLiteMigrationManager,\n    SQLiteOperatorExitRepository,\n    SQLiteOrderRepository,\n",
    )
    replace_once(
        root,
        path,
        '        "_market_type_switch_service",\n        "_opportunity_discovery_service",\n',
        '        "_market_type_switch_service",\n        "_operator_exit_service",\n        "_opportunity_discovery_service",\n',
    )
    replace_once(
        root,
        path,
        '        "_order_engine",\n        "_order_repository",\n',
        '        "_operator_exit_repository",\n        "_order_engine",\n        "_order_repository",\n',
    )
    replace_once(
        root,
        path,
        "        self._runtime_risk_limit_repository: RuntimeRiskLimitRepository | None = None\n"
        "        self._order_repository: OrderRepository | None = None\n",
        "        self._runtime_risk_limit_repository: RuntimeRiskLimitRepository | None = None\n"
        "        self._operator_exit_repository: OperatorExitRepository | None = None\n"
        "        self._order_repository: OrderRepository | None = None\n",
    )
    replace_once(
        root,
        path,
        "        self._market_type_switch_service: MarketTypeSwitchService | None = None\n"
        "        self._initialized = False\n",
        "        self._market_type_switch_service: MarketTypeSwitchService | None = None\n"
        "        self._operator_exit_service: OperatorExitService | None = None\n"
        "        self._initialized = False\n",
    )
    replace_once(
        root,
        path,
        "    @property\n"
        "    def runtime_risk_limit_repository(self) -> RuntimeRiskLimitRepository:\n"
        "        return self._require(self._runtime_risk_limit_repository)\n\n"
        "    @property\n"
        "    def order_repository(self) -> OrderRepository:\n",
        "    @property\n"
        "    def runtime_risk_limit_repository(self) -> RuntimeRiskLimitRepository:\n"
        "        return self._require(self._runtime_risk_limit_repository)\n\n"
        "    @property\n"
        "    def operator_exit_repository(self) -> OperatorExitRepository:\n"
        "        return self._require(self._operator_exit_repository)\n\n"
        "    @property\n"
        "    def order_repository(self) -> OrderRepository:\n",
    )
    replace_once(
        root,
        path,
        "    @property\n"
        "    def market_type_switch_service(self) -> MarketTypeSwitchService:\n"
        "        return self._require(self._market_type_switch_service)\n\n"
        "    @property\n"
        "    def strategy_service(self) -> StrategyService:\n",
        "    @property\n"
        "    def market_type_switch_service(self) -> MarketTypeSwitchService:\n"
        "        return self._require(self._market_type_switch_service)\n\n"
        "    @property\n"
        "    def operator_exit_service(self) -> OperatorExitService:\n"
        "        return self._require(self._operator_exit_service)\n\n"
        "    @property\n"
        "    def strategy_service(self) -> StrategyService:\n",
    )
    replace_once(
        root,
        path,
        "        self._runtime_risk_limit_repository = SQLiteRuntimeRiskLimitRepository(\n"
        "            database=database\n"
        "        )\n"
        "        self._order_repository = SQLiteOrderRepository(database=database)\n",
        "        self._runtime_risk_limit_repository = SQLiteRuntimeRiskLimitRepository(\n"
        "            database=database\n"
        "        )\n"
        "        self._operator_exit_repository = SQLiteOperatorExitRepository(\n"
        "            database=database\n"
        "        )\n"
        "        self._order_repository = SQLiteOrderRepository(database=database)\n",
    )
    replace_once(
        root,
        path,
        "        self._live_natural_exit_recovery_service = LiveNaturalExitRecoveryService(\n"
        "            exchange_client=exchange_client,\n"
        "            position_repository=self.position_repository,\n"
        "            submission_attempt_repository=self.submission_attempt_repository,\n"
        "            closed_lifecycle_service=self._closed_position_lifecycle_service,\n",
        "        self._live_natural_exit_recovery_service = LiveNaturalExitRecoveryService(\n"
        "            exchange_client=exchange_client,\n"
        "            position_repository=self.position_repository,\n"
        "            submission_attempt_repository=self.submission_attempt_repository,\n"
        "            operator_exit_repository=self.operator_exit_repository,\n"
        "            closed_lifecycle_service=self._closed_position_lifecycle_service,\n",
    )

    old_runtime_start = """            self._telegram_query_service = query_service
            self._runtime_recovery_service = RuntimeRecoveryService(
"""
    new_runtime_start = """            self._telegram_query_service = query_service
            self._market_type_switch_service = MarketTypeSwitchService(
                trade_mode=self._settings.app.trade_mode,
                runtime_control=self.runtime_control,
                position_repository=self.position_repository,
                position_service=self.position_service,
                restart_coordinator=self.restart_coordinator,
                settings=self._settings,
                submission_attempt_repository=self.submission_attempt_repository,
            )
            self._operator_exit_service = OperatorExitService(
                trade_mode=self._settings.app.trade_mode,
                market_type=self._settings.exchange.market_type,
                exchange_environment=self._settings.exchange.environment,
                runtime_control=self.runtime_control,
                operator_exit_repository=self.operator_exit_repository,
                position_repository=self.position_repository,
                market_stream_owner=self.live_market_stream_service,
                execution_policy_switcher=self.market_type_switch_service,
                live_position_service=self.position_service,
                live_exchange=self.exchange_client,
                submission_attempt_repository=self.submission_attempt_repository,
                closed_lifecycle_service=self._closed_position_lifecycle_service,
                live_runtime_reconciler=(
                    self.live_runtime_portfolio_reconciliation_service
                ),
                order_repository=self.order_repository,
                lifecycle_coordinator=self._live_position_lifecycle_coordinator,
                paper_trading_service=self.paper_trading_service,
                market_price_provider=self.market_service,
            )
            await self.operator_exit_service.initialize()
            self._runtime_recovery_service = RuntimeRecoveryService(
"""
    replace_once(root, path, old_runtime_start, new_runtime_start)

    replace_once(
        root,
        path,
        "                live_natural_exit_recovery_service=(\n"
        "                    self.live_natural_exit_recovery_service\n"
        "                ),\n"
        "                autonomous_live_entry_authorization=(\n",
        "                live_natural_exit_recovery_service=(\n"
        "                    self.live_natural_exit_recovery_service\n"
        "                ),\n"
        "                operator_exit_recovery_service=self.operator_exit_service,\n"
        "                autonomous_live_entry_authorization=(\n",
    )

    duplicate_switcher = """            self._market_type_switch_service = MarketTypeSwitchService(
                trade_mode=self._settings.app.trade_mode,
                runtime_control=self.runtime_control,
                position_repository=self.position_repository,
                position_service=self.position_service,
                restart_coordinator=self.restart_coordinator,
                settings=self._settings,
                submission_attempt_repository=self.submission_attempt_repository,
            )
"""
    text = (root / path).read_text(encoding="utf-8")
    if text.count(duplicate_switcher) != 2:
        raise RuntimeError("Expected two MarketTypeSwitchService blocks before de-dup")
    first_index = text.index(duplicate_switcher)
    second_index = text.index(duplicate_switcher, first_index + len(duplicate_switcher))
    text = text[:second_index] + text[second_index + len(duplicate_switcher) :]
    (root / path).write_text(text, encoding="utf-8", newline="\n")

    replace_once(
        root,
        path,
        "                    runtime_risk_limit_service=self._runtime_risk_limit_service,\n"
        "                )\n",
        "                    runtime_risk_limit_service=self._runtime_risk_limit_service,\n"
        "                    operator_exit_service=self.operator_exit_service,\n"
        "                )\n",
    )

    replace_once(
        root,
        path,
        "        telegram_bot = self._telegram_bot\n"
        "        live_market_stream_service = self._live_market_stream_service\n",
        "        telegram_bot = self._telegram_bot\n"
        "        operator_exit_service = self._operator_exit_service\n"
        "        live_market_stream_service = self._live_market_stream_service\n",
    )

    old_cleanup = """        try:
            if telegram_bot is not None:
                await telegram_bot.stop()
        finally:
            try:
                if live_futures_user_data_service is not None:
                    await live_futures_user_data_service.close()
            finally:
                try:
                    if live_protection_monitoring_service is not None:
                        live_protection_monitoring_service.stop_all()
                finally:
                    try:
                        if live_market_stream_service is not None:
                            await live_market_stream_service.stop_all()
                    finally:
                        try:
                            if stream_client is not None:
                                await stream_client.close()
                        finally:
                            try:
                                if exchange_client is not None:
                                    await exchange_client.close()
                            finally:
                                if database is not None:
                                    await database.close()
"""
    new_cleanup = """        try:
            if telegram_bot is not None:
                await telegram_bot.stop()
        finally:
            try:
                if operator_exit_service is not None:
                    await operator_exit_service.close()
            finally:
                try:
                    if live_futures_user_data_service is not None:
                        await live_futures_user_data_service.close()
                finally:
                    try:
                        if live_protection_monitoring_service is not None:
                            live_protection_monitoring_service.stop_all()
                    finally:
                        try:
                            if live_market_stream_service is not None:
                                await live_market_stream_service.stop_all()
                        finally:
                            try:
                                if stream_client is not None:
                                    await stream_client.close()
                            finally:
                                try:
                                    if exchange_client is not None:
                                        await exchange_client.close()
                                finally:
                                    if database is not None:
                                        await database.close()
"""
    replace_once(root, path, old_cleanup, new_cleanup)

    replace_once(
        root,
        path,
        "        self._runtime_risk_limit_repository = None\n"
        "        self._runtime_risk_limit_service = None\n"
        "        self._order_repository = None\n",
        "        self._runtime_risk_limit_repository = None\n"
        "        self._runtime_risk_limit_service = None\n"
        "        self._operator_exit_repository = None\n"
        "        self._operator_exit_service = None\n"
        "        self._order_repository = None\n",
    )


def patch_natural_exit(root: Path) -> None:
    path = "botragram/services/live_natural_exit_recovery_service.py"
    replace_once(
        root,
        path,
        "\n\n@dataclass(slots=True, kw_only=True, frozen=True)\nclass LiveNaturalExitRecoveryService:\n",
        """

class LiveOperatorExitRecoveryState(Protocol):
    \"\"\"Expose operator closes that still own exact exit reconciliation.\"\"\"

    async def get_incomplete_attempts(self) -> Sequence[object]:
        \"\"\"Return operator-exit attempts that must block natural cleanup.\"\"\"
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveNaturalExitRecoveryService:
""",
    )
    replace_once(
        root,
        path,
        "    submission_attempt_repository: SubmissionAttemptRepository\n"
        "    closed_lifecycle_service: ClosedPositionLifecycleService | None = None\n",
        "    submission_attempt_repository: SubmissionAttemptRepository\n"
        "    operator_exit_repository: LiveOperatorExitRecoveryState | None = None\n"
        "    closed_lifecycle_service: ClosedPositionLifecycleService | None = None\n",
    )
    replace_once(
        root,
        path,
        "    async def reconcile(self) -> None:\n"
        "        \"\"\"Remove proven orphan protection and stale local positions.\"\"\"\n"
        "        incomplete_attempts = tuple(\n",
        "    async def reconcile(self) -> None:\n"
        "        \"\"\"Remove proven orphan protection and stale local positions.\"\"\"\n"
        "        operator_repository = self.operator_exit_repository\n"
        "        if (\n"
        "            operator_repository is not None\n"
        "            and await operator_repository.get_incomplete_attempts()\n"
        "        ):\n"
        "            raise RuntimeError(\n"
        "                \"Incomplete LIVE operator exit requires exact recovery before \"\n"
        "                \"natural-exit reconciliation\"\n"
        "            )\n"
        "        incomplete_attempts = tuple(\n",
    )


def patch_runtime_recovery(root: Path) -> None:
    path = "botragram/services/runtime_recovery_service.py"
    replace_once(
        root,
        path,
        "\n\nclass LiveProtectionMonitorOwner(Protocol):\n",
        """

class OperatorExitRecovery(Protocol):
    \"\"\"Recover durable operator exits before ordinary runtime recovery.\"\"\"

    async def has_incomplete_operation(self) -> bool:
        \"\"\"Return whether an operator action still owns the mutation boundary.\"\"\"
        ...

    async def recover_until_safe(self) -> None:
        \"\"\"Converge confirmed operator work without blind mutations.\"\"\"
        ...


class LiveProtectionMonitorOwner(Protocol):
""",
    )
    replace_once(
        root,
        path,
        "    live_natural_exit_recovery_service: LiveNaturalExitRecovery | None = None\n"
        "    autonomous_live_entry_authorization: AutonomousLiveEntryAuthorization | None = None\n",
        "    live_natural_exit_recovery_service: LiveNaturalExitRecovery | None = None\n"
        "    operator_exit_recovery_service: OperatorExitRecovery | None = None\n"
        "    autonomous_live_entry_authorization: AutonomousLiveEntryAuthorization | None = None\n",
    )
    replace_once(
        root,
        path,
        "    async def recover(self, *, activate_runtime: bool = True) -> bool:\n"
        "        \"\"\"Rebuild safe runtime state and optionally activate future cycles.\"\"\"\n"
        "        if self.trade_mode is TradeMode.LIVE:\n",
        "    async def recover(self, *, activate_runtime: bool = True) -> bool:\n"
        "        \"\"\"Rebuild safe runtime state and optionally activate future cycles.\"\"\"\n"
        "        operator_exit_recovery = self.operator_exit_recovery_service\n"
        "        if (\n"
        "            operator_exit_recovery is not None\n"
        "            and await operator_exit_recovery.has_incomplete_operation()\n"
        "        ):\n"
        "            self.runtime_control.pause()\n"
        "            await operator_exit_recovery.recover_until_safe()\n"
        "            if await operator_exit_recovery.has_incomplete_operation():\n"
        "                _LOGGER.info(\n"
        "                    \"Runtime recovery remains PAUSED for pending operator-exit \"\n"
        "                    \"transition\"\n"
        "                )\n"
        "                return False\n"
        "        if self.trade_mode is TradeMode.LIVE:\n",
    )


def patch_restart_lifecycle(root: Path) -> None:
    path = "botragram/app/market_type_switch.py"
    replace_once(
        root,
        path,
        "    async def wait(self) -> RuntimeRestartTarget:\n",
        "    @property\n"
        "    def has_committed_restart(self) -> bool:\n"
        "        \"\"\"Return whether a validated restart is waiting to be consumed.\"\"\"\n"
        "        return self._restart_event.is_set()\n\n"
        "    async def wait(self) -> RuntimeRestartTarget:\n",
    )

    path = "main.py"
    replace_once(
        root,
        path,
        "async def _recover_autonomous_live_until_ready(\n"
        "    *,\n"
        "    dependency_provider: DependencyProvider,\n"
        ") -> None:\n",
        "async def _recover_autonomous_live_until_ready(\n"
        "    *,\n"
        "    dependency_provider: DependencyProvider,\n"
        "    activate_runtime: bool,\n"
        ") -> None:\n",
    )
    replace_once(
        root,
        path,
        "            recovered = await dependency_provider.runtime_recovery_service.recover()\n",
        "            recovered = await dependency_provider.runtime_recovery_service.recover(\n"
        "                activate_runtime=activate_runtime,\n"
        "            )\n",
    )
    replace_once(
        root,
        path,
        "        if recovered:\n"
        "            if attempt:\n",
        "        if dependency_provider.restart_coordinator.has_committed_restart:\n"
        "            return\n\n"
        "        if recovered:\n"
        "            if attempt:\n",
    )
    replace_once(
        root,
        path,
        "        if settings.app.effective_execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE:\n"
        "            await _recover_autonomous_live_until_ready(\n"
        "                dependency_provider=dependency_provider,\n"
        "            )\n"
        "        else:\n"
        "            await dependency_provider.runtime_recovery_service.recover()\n"
        "        await prepare_restarted_runtime_session(\n",
        "        activate_runtime = not isinstance(restart_target, ExecutionPolicy)\n"
        "        if settings.app.effective_execution_policy is ExecutionPolicy.AUTONOMOUS_LIVE:\n"
        "            await _recover_autonomous_live_until_ready(\n"
        "                dependency_provider=dependency_provider,\n"
        "                activate_runtime=activate_runtime,\n"
        "            )\n"
        "        else:\n"
        "            await dependency_provider.runtime_recovery_service.recover(\n"
        "                activate_runtime=activate_runtime,\n"
        "            )\n"
        "        if restart_coordinator.has_committed_restart:\n"
        "            _LOGGER.info(\n"
        "                \"Runtime recovery committed a soft restart before runner \"\n"
        "                \"activation\"\n"
        "            )\n"
        "            return\n"
        "        await prepare_restarted_runtime_session(\n",
    )


def patch_project_structure(root: Path) -> None:
    path = "PROJECT_STRUCTURE.md"
    replace_once(
        root,
        path,
        "|   |-- closed_position_lifecycle.py # One authoritative closed LIVE position lifecycle\n",
        "|   |-- closed_position_lifecycle.py # One authoritative closed LIVE position lifecycle\n"
        "|   |-- operator_exit.py # Durable operator exit operation/attempt/confirmation snapshots\n",
    )
    replace_once(
        root,
        path,
        "|-- repositories/              # Persistence interfaces, including lifecycle ledger\n"
        "|   |-- closed_position_lifecycle_repository.py # Durable entry-identity ledger contract\n",
        "|-- repositories/              # Persistence interfaces, including lifecycle ledger\n"
        "|   |-- closed_position_lifecycle_repository.py # Durable entry-identity ledger contract\n"
        "|   |-- operator_exit_repository.py # Restart-safe operator exit ownership contract\n",
    )
    replace_once(
        root,
        path,
        "|   |-- opportunity_discovery_service.py # Bounded actionable signal discovery\n"
        "|   |-- order_service.py\n",
        "|   |-- opportunity_discovery_service.py # Bounded actionable signal discovery\n"
        "|   |-- operator_exit_service.py # Guarded PAPER/LIVE close + flatten-and-switch orchestration\n"
        "|   |-- order_service.py\n",
    )
    replace_once(
        root,
        path,
        "|       |-- migrations.py\n"
        "|       |-- runtime_risk_limit_repository.py # Current singleton + append-only audit\n",
        "|       |-- migrations.py\n"
        "|       |-- operator_exit_repository.py # Durable operator exit operations and attempts\n"
        "|       |-- runtime_risk_limit_repository.py # Current singleton + append-only audit\n",
    )
    replace_once(
        root,
        path,
        "|   |-- messages.py\n"
        "|   |-- risk_limit_commands.py # Paused durable runtime-limit controls\n",
        "|   |-- messages.py\n"
        "|   |-- operator_exit_commands.py # Explicit chat-bound portfolio exit controls\n"
        "|   |-- risk_limit_commands.py # Paused durable runtime-limit controls\n",
    )


def patch_wiring_test(root: Path) -> None:
    path = "tests/test_dependency_provider_wiring.py"
    replace_once(
        root,
        path,
        "        assert (\n"
        "            getattr(service, \"protection_reconciler\", None)\n"
        "            is provider.live_position_protection_service\n"
        "        )\n",
        "        assert (\n"
        "            getattr(service, \"protection_reconciler\", None)\n"
        "            is provider.live_position_protection_service\n"
        "        )\n"
        "        operator_exit = provider.operator_exit_service\n"
        "        assert (\n"
        "            operator_exit.operator_exit_repository\n"
        "            is provider.operator_exit_repository\n"
        "        )\n"
        "        assert (\n"
        "            provider.runtime_recovery_service.operator_exit_recovery_service\n"
        "            is operator_exit\n"
        "        )\n"
        "        assert (\n"
        "            provider.live_natural_exit_recovery_service.operator_exit_repository\n"
        "            is provider.operator_exit_repository\n"
        "        )\n",
    )


def add_runtime_recovery_tests(root: Path) -> None:
    write_new(
        root,
        "tests/test_operator_exit_runtime_recovery.py",
        dedent(
            '''\
            """Operator-exit ordering inside canonical runtime recovery."""

            from __future__ import annotations

            from dataclasses import dataclass, field
            from typing import cast

            import pytest

            from botragram.app.runtime_control import TradingRuntimeControl
            from botragram.enums import MarketType, TradeMode
            from botragram.models import LiveMarketStreamIdentity, LiveMarketStreamState
            from botragram.services import LivePortfolioRecoveryService, RuntimeRecoveryService
            from botragram.storage.memory import (
                MemoryCandleRepository,
                MemoryPositionRepository,
                MemorySignalRepository,
            )


            @dataclass(slots=True)
            class _OperatorRecovery:
                remains_incomplete: bool
                recover_calls: int = 0

                async def has_incomplete_operation(self) -> bool:
                    return self.remains_incomplete

                async def recover_until_safe(self) -> None:
                    self.recover_calls += 1


            @dataclass(slots=True)
            class _StreamController:
                start_calls: int = 0
                stop_calls: int = 0

                async def start_market_stream(self) -> bool:
                    self.start_calls += 1
                    return True

                async def stop_market_stream(self) -> bool:
                    self.stop_calls += 1
                    return True


            @dataclass(slots=True)
            class _MarketStreamOwner:
                @property
                def stream_states(self) -> tuple[LiveMarketStreamState, ...]:
                    return ()

                async def start(self, *, context: object) -> LiveMarketStreamIdentity:
                    del context
                    raise AssertionError("market stream must not start")

                async def wait_for_first_tick(
                    self,
                    *,
                    identity: LiveMarketStreamIdentity,
                    timeout_seconds: float,
                ) -> bool:
                    del identity, timeout_seconds
                    raise AssertionError("market stream must not wait")

                async def stop(self, *, identity: LiveMarketStreamIdentity) -> bool:
                    del identity
                    return False


            @dataclass(slots=True)
            class _ProtectionOwner:
                register_calls: int = 0
                stop_calls: int = 0

                @property
                def monitor_states(self) -> tuple[object, ...]:
                    return ()

                def register(self, *, context: object) -> bool:
                    del context
                    self.register_calls += 1
                    raise AssertionError("protection monitor must not register")

                def stop(self, *, symbol: str) -> bool:
                    del symbol
                    self.stop_calls += 1
                    return False


            @pytest.mark.asyncio
            async def test_pending_operator_transition_short_circuits_runtime_recovery() -> None:
                runtime = TradingRuntimeControl()
                operator = _OperatorRecovery(remains_incomplete=True)
                stream = _StreamController()
                service = RuntimeRecoveryService(
                    trade_mode=TradeMode.PAPER,
                    market_type=MarketType.FUTURES,
                    runtime_control=runtime,
                    stream_controller=stream,
                    market_stream_service=_MarketStreamOwner(),
                    protection_monitoring_service=cast(object, _ProtectionOwner()),
                    position_repository=MemoryPositionRepository(),
                    signal_repository=MemorySignalRepository(),
                    candle_repository=MemoryCandleRepository(),
                    live_portfolio_recovery_service=cast(
                        LivePortfolioRecoveryService,
                        object(),
                    ),
                    operator_exit_recovery_service=operator,
                )

                assert not await service.recover()
                assert operator.recover_calls == 1
                assert runtime.is_paused
                assert stream.start_calls == 0
            '''
        ),
    )


def add_natural_exit_guard_test(root: Path) -> None:
    write_new(
        root,
        "tests/test_operator_exit_natural_exit_guard.py",
        dedent(
            '''\
            """Natural-exit cleanup must not steal an operator-close lifecycle."""

            from __future__ import annotations

            from dataclasses import dataclass

            import pytest

            from botragram.services import LiveNaturalExitRecoveryService
            from botragram.storage.memory import (
                MemoryPositionRepository,
                MemorySubmissionAttemptRepository,
            )


            @dataclass(slots=True)
            class _OperatorState:
                async def get_incomplete_attempts(self) -> tuple[object, ...]:
                    return (object(),)


            @dataclass(slots=True)
            class _UnexpectedExchange:
                calls: int = 0

                async def get_positions(self, *, symbol: str | None = None) -> tuple[object, ...]:
                    del symbol
                    self.calls += 1
                    raise AssertionError("natural-exit exchange reads must be blocked")

                async def get_open_protection_orders(
                    self,
                    *,
                    symbol: str | None = None,
                ) -> tuple[object, ...]:
                    del symbol
                    raise AssertionError("natural-exit protection reads must be blocked")


            @pytest.mark.asyncio
            async def test_incomplete_operator_close_blocks_natural_exit_reconciliation() -> None:
                exchange = _UnexpectedExchange()
                service = LiveNaturalExitRecoveryService(
                    exchange_client=exchange,  # type: ignore[arg-type]
                    position_repository=MemoryPositionRepository(),
                    submission_attempt_repository=MemorySubmissionAttemptRepository(),
                    operator_exit_repository=_OperatorState(),
                )

                with pytest.raises(RuntimeError, match="Incomplete LIVE operator exit"):
                    await service.reconcile()

                assert exchange.calls == 0
            '''
        ),
    )


def add_restart_coordinator_test(root: Path) -> None:
    path = "tests/test_market_type_switch.py"
    replace_once(
        root,
        path,
        "def test_market_type_switch_fails_closed_for_live_positions() -> None:\n",
        "def test_restart_coordinator_exposes_committed_pre_runner_restart() -> None:\n"
        "    coordinator = RuntimeRestartCoordinator()\n"
        "    coordinator.stage(execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER)\n"
        "    assert not coordinator.has_committed_restart\n"
        "    coordinator.commit(execution_policy=ExecutionPolicy.AUTONOMOUS_PAPER)\n"
        "    assert coordinator.has_committed_restart\n"
        "    assert coordinator.consume() is ExecutionPolicy.AUTONOMOUS_PAPER\n"
        "    assert not coordinator.has_committed_restart\n\n\n"
        "def test_market_type_switch_fails_closed_for_live_positions() -> None:\n",
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_operator_exit_composition.py <target-root>")
    root = Path(sys.argv[1]).resolve()
    head = git(root, "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        raise SystemExit(f"Unexpected target HEAD {head}; expected {EXPECTED_HEAD}")
    if git(root, "status", "--short"):
        raise SystemExit("Target working tree must be clean")

    patch_dependency_provider(root)
    patch_natural_exit(root)
    patch_runtime_recovery(root)
    patch_restart_lifecycle(root)
    patch_project_structure(root)
    patch_wiring_test(root)
    add_runtime_recovery_tests(root)
    add_natural_exit_guard_test(root)
    add_restart_coordinator_test(root)

    print("Operator-exit composition patch applied")


if __name__ == "__main__":
    main()
