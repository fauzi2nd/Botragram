from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent


def write(root: Path, path: str, content: str) -> None:
    (root / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(root: Path, path: str, old: str, new: str) -> None:
    file_path = root / path
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one protocol replacement in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def patch_protocol_contracts(root: Path) -> None:
    path = "botragram/services/operator_exit_service.py"
    replacements = (
        (
            '        """Return current positions, optionally synchronized from exchange."""\n',
            '        """Return current positions, optionally synchronized from exchange."""\n        ...\n',
        ),
        (
            '        """Read one authoritative position without mutating persistence."""\n',
            '        """Read one authoritative position without mutating persistence."""\n        ...\n',
        ),
        (
            '        """Submit one reduce-only close with a durable client identity."""\n',
            '        """Submit one reduce-only close with a durable client identity."""\n        ...\n',
        ),
        (
            '        """Return one exact close order without creating another order."""\n',
            '        """Return one exact close order without creating another order."""\n        ...\n',
        ),
        (
            '        """Close one PAPER position or return None when already flat."""\n',
            '        """Close one PAPER position or return None when already flat."""\n        ...\n',
        ),
        (
            '        """Return one current market ticker."""\n',
            '        """Return one current market ticker."""\n        ...\n',
        ),
        (
            '        """Return reconciled context or None when safety remains unresolved."""\n',
            '        """Return reconciled context or None when safety remains unresolved."""\n        ...\n',
        ),
        (
            '        """Stop every owned market stream."""\n',
            '        """Stop every owned market stream."""\n        ...\n',
        ),
        (
            '        """Return the policy owned by the current runtime session."""\n',
            '        """Return the policy owned by the current runtime session."""\n        ...\n',
        ),
        (
            '        """Return policies inside the immutable boot capability envelope."""\n',
            '        """Return policies inside the immutable boot capability envelope."""\n        ...\n',
        ),
        (
            '        """Stage one target after fresh safety validation."""\n',
            '        """Stage one target after fresh safety validation."""\n        ...\n',
        ),
        (
            '        """Commit one already-staged target."""\n',
            '        """Commit one already-staged target."""\n        ...\n',
        ),
    )
    for old, new in replacements:
        replace_once(root, path, old, new)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: fix_operator_exit_generated_tests.py <target-root>")
    root = Path(sys.argv[1]).resolve()
    patch_protocol_contracts(root)

    write(
        root,
        "tests/test_operator_exit_runtime_recovery.py",
        dedent(
            '''\
            """Operator-exit ordering inside canonical runtime recovery."""

            from __future__ import annotations

            from dataclasses import dataclass
            from typing import cast

            import pytest

            from botragram.app.runtime_control import TradingRuntimeControl
            from botragram.enums import MarketType, TradeMode
            from botragram.models import (
                LiveMarketStreamIdentity,
                LiveMarketStreamState,
                LiveProtectionMonitorState,
                LiveRuntimePositionContext,
            )
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

                async def start(
                    self,
                    *,
                    context: LiveRuntimePositionContext,
                ) -> LiveMarketStreamIdentity:
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
                def monitor_states(self) -> tuple[LiveProtectionMonitorState, ...]:
                    return ()

                def register(self, *, context: LiveRuntimePositionContext) -> bool:
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
                    protection_monitoring_service=_ProtectionOwner(),
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

    write(
        root,
        "tests/test_operator_exit_natural_exit_guard.py",
        dedent(
            '''\
            """Natural-exit cleanup must not steal an operator-close lifecycle."""

            from __future__ import annotations

            from dataclasses import dataclass
            from typing import cast

            import pytest

            from botragram.services import LiveNaturalExitRecoveryService
            from botragram.services.live_natural_exit_recovery_service import (
                LiveNaturalExitExchange,
            )
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

                async def get_positions(
                    self,
                    *,
                    symbol: str | None = None,
                ) -> tuple[object, ...]:
                    del symbol
                    self.calls += 1
                    raise AssertionError("natural-exit exchange reads must be blocked")


            @pytest.mark.asyncio
            async def test_incomplete_operator_close_blocks_natural_exit_reconciliation() -> None:
                exchange = _UnexpectedExchange()
                service = LiveNaturalExitRecoveryService(
                    exchange_client=cast(LiveNaturalExitExchange, exchange),
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

    print("Operator-exit protocol contracts and generated tests tightened")


if __name__ == "__main__":
    main()
