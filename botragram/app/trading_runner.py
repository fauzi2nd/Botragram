"""
Botragram

Description:
    Cancellable trading-cycle runtime orchestration.

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
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderType, SignalType, TradeMode
from botragram.models import ExecutionAuthorization, TradingDecision, TradingResult

__all__ = [
    "AutonomousPaperTradingCycleExecutor",
    "HumanConfirmedPaperTradingCycleExecutor",
    "SingleSymbolTradingCycleExecutor",
    "TradingCycleExecutor",
    "TradingRunner",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_CANDLE_LIMIT: Final[int] = 100
_DEFAULT_PAPER_ACCOUNT_BALANCE: Final[Decimal] = Decimal("10000")
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 30.0
_RESULT_REASON_UNAVAILABLE: Final[str] = "No reason provided"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Runtime Contracts
# =============================================================================
class TradingCycleExecutor(Protocol):
    """Execute one complete runtime trading cycle."""

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Execute and return all results produced by one runtime cycle."""
        ...


class SingleSymbolExecutionProvider(Protocol):
    """Execute the existing single-symbol trading workflow."""

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> TradingResult:
        """Execute and return one single-symbol trading result."""
        ...


class AutonomousPaperExecutionProvider(Protocol):
    """Execute a bounded autonomous PAPER opportunity cycle."""

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        initial_balance: Decimal | None = None,
    ) -> Sequence[TradingResult]:
        """Discover and execute ranked PAPER candidates."""
        ...


class HumanConfirmedPaperExecutionProvider(Protocol):
    """Prepare bounded PAPER opportunities for explicit human approval."""

    async def execute(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[ExecutionAuthorization]:
        """Return newly prepared non-executed authorizations."""
        ...


class TradingRuntimeObserver(Protocol):
    """Observe runtime lifecycle without controlling trading decisions."""

    async def on_started(self) -> None:
        """Observe runtime startup."""
        ...

    async def on_cycle_completed(self, *, result: TradingResult) -> None:
        """Observe a completed trading cycle."""
        ...

    async def on_cycle_failed(
        self,
        *,
        error: Exception,
        consecutive_failures: int,
        maximum_failures: int,
    ) -> None:
        """Observe a failed cycle before retry or propagation."""
        ...

    async def on_stopped(self) -> None:
        """Observe runtime shutdown."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class SingleSymbolTradingCycleExecutor:
    """Adapt the established single-symbol service to the runtime contract."""

    trading_service: SingleSymbolExecutionProvider

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Execute the existing single-symbol workflow as one cycle result."""
        result = await self.trading_service.execute(
            symbol=symbol,
            interval=interval,
            candle_limit=candle_limit,
            current_drawdown_pct=current_drawdown_pct,
            order_type=order_type,
            price=price,
            account_balance_override=account_balance_override,
            synchronize_position=synchronize_position,
            submit_order=submit_order,
        )
        return (result,)


@dataclass(slots=True, kw_only=True, frozen=True)
class AutonomousPaperTradingCycleExecutor:
    """Adapt autonomous discovery to a runtime cycle with PAPER-only safety."""

    autonomous_execution_service: AutonomousPaperExecutionProvider
    quote_asset: str
    max_symbols: int
    top_n: int

    def __post_init__(self) -> None:
        """Normalize and validate static autonomous-discovery inputs."""
        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Autonomous execution quote asset must not be empty")

        if self.max_symbols <= 0:
            raise ValueError("Autonomous execution maximum symbols must be positive")

        if self.top_n <= 0:
            raise ValueError("Autonomous execution top N must be positive")

        object.__setattr__(self, "quote_asset", normalized_quote_asset)

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Execute one bounded PAPER discovery cycle without order submission."""
        del symbol, current_drawdown_pct, order_type, price, synchronize_position

        if submit_order:
            raise RuntimeError("Autonomous execution is restricted to paper mode")

        return await self.autonomous_execution_service.execute(
            quote_asset=self.quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
            initial_balance=account_balance_override,
        )


@dataclass(slots=True, kw_only=True, frozen=True)
class HumanConfirmedPaperTradingCycleExecutor:
    """Adapt confirmation discovery to a PAPER runtime cycle without execution."""

    human_confirmation_service: HumanConfirmedPaperExecutionProvider
    quote_asset: str
    max_symbols: int
    top_n: int

    def __post_init__(self) -> None:
        """Normalize and validate static confirmation-discovery inputs."""
        normalized_quote_asset = self.quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Human confirmation quote asset must not be empty")

        if self.max_symbols <= 0:
            raise ValueError("Human confirmation maximum symbols must be positive")

        if self.top_n <= 0:
            raise ValueError("Human confirmation top N must be positive")

        object.__setattr__(self, "quote_asset", normalized_quote_asset)

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Prepare human approvals while structurally rejecting order submission."""
        del (
            symbol,
            current_drawdown_pct,
            order_type,
            price,
            account_balance_override,
            synchronize_position,
        )

        if submit_order:
            raise RuntimeError("Human-confirmed execution is restricted to paper mode")

        authorizations = await self.human_confirmation_service.execute(
            quote_asset=self.quote_asset,
            interval=interval,
            candle_limit=candle_limit,
            max_symbols=self.max_symbols,
            top_n=self.top_n,
        )
        return tuple(
            TradingResult(
                executed=False,
                decision=TradingDecision(
                    should_execute=False,
                    signal=authorization.signal,
                    risk_result=None,
                    reason="Pending human PAPER approval",
                ),
                order=None,
                reason="Pending human PAPER approval",
            )
            for authorization in authorizations
        )


# =============================================================================
# Runtime Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
)
class TradingRunner:
    """Continuously execute trading cycles until stopped or cancelled."""

    executor: TradingCycleExecutor
    symbol: str
    interval: Interval
    trade_mode: TradeMode = TradeMode.PAPER
    candle_limit: int = _DEFAULT_CANDLE_LIMIT
    cycle_interval_seconds: float | None = None
    paper_account_balance: Decimal = _DEFAULT_PAPER_ACCOUNT_BALANCE
    runtime_control: TradingRuntimeControl = field(
        default_factory=TradingRuntimeControl,
    )
    runtime_observer: TradingRuntimeObserver | None = None
    maximum_consecutive_failures: int = 1
    failure_retry_delay_seconds: float = 5.0
    heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS

    _running: bool = field(default=False, init=False)
    _stop_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize and validate immutable runtime inputs."""
        self.symbol = self.symbol.strip().upper()

        if not self.symbol:
            raise ValueError("Trading runner symbol must not be empty")

        self.runtime_control.symbol = self.symbol

        if self.candle_limit <= 0:
            raise ValueError("Trading runner candle limit must be greater than zero")

        if self.cycle_interval_seconds is not None and self.cycle_interval_seconds <= 0:
            raise ValueError("Trading runner cycle interval must be greater than zero")

        if self.paper_account_balance <= 0:
            raise ValueError("Paper account balance must be greater than zero")

        if self.maximum_consecutive_failures <= 0:
            raise ValueError("Maximum consecutive failures must be greater than zero")

        if self.failure_retry_delay_seconds <= 0:
            raise ValueError("Failure retry delay must be greater than zero")

        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("Heartbeat interval must be greater than zero")

    @property
    def is_running(self) -> bool:
        """Return whether the continuous runtime loop is active."""
        return self._running

    @property
    def order_submission_enabled(self) -> bool:
        """Return whether this runtime may submit exchange orders."""
        return self.trade_mode is TradeMode.LIVE

    @property
    def effective_cycle_interval_seconds(self) -> float:
        """Return the fixed override or current Telegram interval cadence."""
        configured_interval = self.cycle_interval_seconds

        if configured_interval is not None:
            return configured_interval

        return float(self.runtime_control.interval.seconds)

    async def run_once(self) -> tuple[TradingResult, ...]:
        """Execute one configured trading cycle."""
        live_trading = self.order_submission_enabled
        self.symbol = self.runtime_control.symbol
        self.interval = self.runtime_control.interval
        _LOGGER.info(
            "Trading cycle started: symbol=%s interval=%s cadence_seconds=%s",
            self.symbol,
            self.interval.value,
            self.effective_cycle_interval_seconds,
        )
        self.runtime_control.begin_cycle()

        try:
            results = tuple(
                await self.executor.execute(
                    symbol=self.symbol,
                    interval=self.interval,
                    candle_limit=self.candle_limit,
                    account_balance_override=(
                        None if live_trading else self.paper_account_balance
                    ),
                    synchronize_position=live_trading,
                    submit_order=live_trading,
                )
            )
        finally:
            self.runtime_control.end_cycle()

        self._log_results(results=results)

        return results

    async def run(self) -> None:
        """Run trading cycles until stop is requested or the task is cancelled.

        Raises:
            RuntimeError: If the runner is already active.
            Exception: Propagates any trading-cycle failure to the application
                boundary so lifecycle cleanup and failure logging remain
                deterministic.
        """
        if self._running:
            raise RuntimeError("Trading runner is already running")

        self._running = True
        self._stop_event.clear()
        self.symbol = self.runtime_control.symbol
        self.interval = self.runtime_control.interval
        _LOGGER.info(
            "Trading runner started: symbol=%s interval=%s mode=%s "
            "candle_limit=%d cycle_interval_seconds=%s",
            self.symbol,
            self.interval.value,
            self.trade_mode.value,
            self.candle_limit,
            self.effective_cycle_interval_seconds,
        )

        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="botragram-runtime-heartbeat",
        )

        try:
            consecutive_failures = 0
            await self._notify_started()

            while not self._stop_event.is_set():
                active = await self.runtime_control.wait_until_active(
                    stop_event=self._stop_event,
                )

                if not active:
                    break

                try:
                    results = await self.run_once()
                except Exception as error:
                    consecutive_failures += 1
                    _LOGGER.warning(
                        "Trading cycle failed: symbol=%s error_type=%s attempt=%d/%d",
                        self.symbol,
                        type(error).__name__,
                        consecutive_failures,
                        self.maximum_consecutive_failures,
                    )
                    await self._notify_cycle_failed(
                        error=error,
                        consecutive_failures=consecutive_failures,
                    )

                    if consecutive_failures >= self.maximum_consecutive_failures:
                        raise

                    await self._wait_for_delay(
                        delay_seconds=self.failure_retry_delay_seconds,
                    )
                    continue

                consecutive_failures = 0
                await self._notify_cycle_completed(results=results)
                await self._wait_for_next_cycle()
        except asyncio.CancelledError:
            _LOGGER.info("Trading runner cancellation requested")
            raise
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            self._running = False
            await self._notify_stopped()
            _LOGGER.info("Trading runner stopped")

    def stop(self) -> None:
        """Request graceful runtime termination."""
        self._stop_event.set()

    async def _wait_for_next_cycle(self) -> None:
        """Wait for the next cycle while remaining immediately stoppable."""
        await self._wait_for_delay(
            delay_seconds=self.effective_cycle_interval_seconds,
        )

    async def _wait_for_delay(self, *, delay_seconds: float) -> None:
        """Wait for a configured delay while remaining immediately stoppable."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=delay_seconds,
            )
        except TimeoutError:
            return

    async def _heartbeat_loop(self) -> None:
        """Log periodic liveness while the runtime remains active."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.heartbeat_interval_seconds,
                )
            except TimeoutError:
                state = "PAUSED" if self.runtime_control.is_paused else "RUNNING"
                _LOGGER.info(
                    "Runtime heartbeat: state=%s symbol=%s strategy=%s stream=%s",
                    state,
                    self.runtime_control.symbol,
                    self.runtime_control.strategy_type.value,
                    "ON" if self.runtime_control.stream_enabled else "OFF",
                )

    async def _notify_started(self) -> None:
        """Notify the optional observer without affecting runtime startup."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_started()
        except Exception:
            _LOGGER.exception("Trading runtime startup observer failed")

    async def _notify_cycle_completed(
        self,
        *,
        results: Sequence[TradingResult],
    ) -> None:
        """Notify the optional observer about a successful cycle."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            for result in results:
                await observer.on_cycle_completed(result=result)
        except Exception:
            _LOGGER.exception("Trading runtime cycle observer failed")

    async def _notify_cycle_failed(
        self,
        *,
        error: Exception,
        consecutive_failures: int,
    ) -> None:
        """Notify the optional observer about a failed cycle."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_cycle_failed(
                error=error,
                consecutive_failures=consecutive_failures,
                maximum_failures=self.maximum_consecutive_failures,
            )
        except Exception:
            _LOGGER.exception("Trading runtime failure observer failed")

    async def _notify_stopped(self) -> None:
        """Notify the optional observer without affecting cleanup."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_stopped()
        except Exception:
            _LOGGER.exception("Trading runtime shutdown observer failed")

    def _log_results(self, *, results: Sequence[TradingResult]) -> None:
        """Log safe summaries without credentials or sensitive payloads."""
        for result in results:
            self._log_result(result=result)

    def _log_result(self, *, result: TradingResult) -> None:
        """Log one safe execution summary without sensitive payloads."""
        reason = self._get_result_reason(result=result)

        if result.executed:
            order_id = result.order.order_id if result.order is not None else "unknown"
            risk_result = result.decision.risk_result
            risk_amount = risk_result.metrics.risk_amount if risk_result else None
            stop_loss = risk_result.metrics.stop_loss if risk_result else None
            take_profit = risk_result.metrics.take_profit if risk_result else None
            _LOGGER.info(
                "Trading cycle submitted an order: symbol=%s order_id=%s "
                "position=%s reason=%s risk_amount=%s stop_loss=%s take_profit=%s",
                self.symbol,
                order_id,
                self._get_position_action(
                    signal_type=result.decision.signal.signal_type,
                ),
                reason,
                self._format_optional_decimal(risk_amount),
                self._format_optional_decimal(stop_loss),
                self._format_optional_decimal(take_profit),
            )
            return

        if result.decision.should_execute:
            _LOGGER.info(
                "Trading cycle approved without order submission: symbol=%s "
                "mode=%s reason=%s",
                self.symbol,
                self.trade_mode.value,
                reason,
            )
            return

        _LOGGER.info(
            "Trading cycle completed without execution: symbol=%s reason=%s",
            self.symbol,
            reason,
        )

    @staticmethod
    def _get_result_reason(*, result: TradingResult) -> str:
        """Return the most specific workflow or strategy reason available."""
        return (
            result.reason
            or result.decision.reason
            or result.decision.signal.reason
            or _RESULT_REASON_UNAVAILABLE
        )

    @staticmethod
    def _get_position_action(*, signal_type: SignalType) -> str:
        """Return the position action represented by a strategy signal."""
        match signal_type:
            case SignalType.BUY:
                return "LONG"
            case SignalType.SELL:
                return "SHORT"
            case SignalType.CLOSE_LONG:
                return "CLOSE_LONG"
            case SignalType.CLOSE_SHORT:
                return "CLOSE_SHORT"
            case SignalType.HOLD:
                return "NONE"

    @staticmethod
    def _format_optional_decimal(value: Decimal | None) -> str:
        """Format optional numeric order context for plain-text logging."""
        return format(value, "f") if value is not None else "N/A"
