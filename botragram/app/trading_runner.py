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
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Protocol

from botragram.app.runtime_control import TradingRuntimeControl

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderType, TradeMode
from botragram.models import TradingResult

__all__ = [
    "TradingCycleExecutor",
    "TradingRunner",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_CANDLE_LIMIT: Final[int] = 100
_DEFAULT_CYCLE_INTERVAL_SECONDS: Final[float] = 60.0
_DEFAULT_PAPER_ACCOUNT_BALANCE: Final[Decimal] = Decimal("10000")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Runtime Contracts
# =============================================================================
class TradingCycleExecutor(Protocol):
    """Execute one complete trading workflow."""

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
        """Execute and return one trading-cycle result."""
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
    cycle_interval_seconds: float = _DEFAULT_CYCLE_INTERVAL_SECONDS
    paper_account_balance: Decimal = _DEFAULT_PAPER_ACCOUNT_BALANCE
    runtime_control: TradingRuntimeControl = field(
        default_factory=TradingRuntimeControl,
    )
    runtime_observer: TradingRuntimeObserver | None = None
    maximum_consecutive_failures: int = 1
    failure_retry_delay_seconds: float = 5.0

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

        if self.candle_limit <= 0:
            raise ValueError("Trading runner candle limit must be greater than zero")

        if self.cycle_interval_seconds <= 0:
            raise ValueError("Trading runner cycle interval must be greater than zero")

        if self.paper_account_balance <= 0:
            raise ValueError("Paper account balance must be greater than zero")

        if self.maximum_consecutive_failures <= 0:
            raise ValueError("Maximum consecutive failures must be greater than zero")

        if self.failure_retry_delay_seconds <= 0:
            raise ValueError("Failure retry delay must be greater than zero")

    @property
    def is_running(self) -> bool:
        """Return whether the continuous runtime loop is active."""
        return self._running

    @property
    def order_submission_enabled(self) -> bool:
        """Return whether this runtime may submit exchange orders."""
        return self.trade_mode is TradeMode.LIVE

    async def run_once(self) -> TradingResult:
        """Execute one configured trading cycle."""
        live_trading = self.order_submission_enabled
        result = await self.executor.execute(
            symbol=self.symbol,
            interval=self.interval,
            candle_limit=self.candle_limit,
            account_balance_override=(
                None if live_trading else self.paper_account_balance
            ),
            synchronize_position=live_trading,
            submit_order=live_trading,
        )
        self._log_result(result=result)

        return result

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
        _LOGGER.info(
            "Trading runner started: symbol=%s interval=%s mode=%s "
            "candle_limit=%d cycle_interval_seconds=%s",
            self.symbol,
            self.interval.value,
            self.trade_mode.value,
            self.candle_limit,
            self.cycle_interval_seconds,
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
                    result = await self.run_once()
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
                await self._notify_cycle_completed(result=result)
                await self._wait_for_next_cycle()
        except asyncio.CancelledError:
            _LOGGER.info("Trading runner cancellation requested")
            raise
        finally:
            self._running = False
            await self._notify_stopped()
            _LOGGER.info("Trading runner stopped")

    def stop(self) -> None:
        """Request graceful runtime termination."""
        self._stop_event.set()

    async def _wait_for_next_cycle(self) -> None:
        """Wait for the next cycle while remaining immediately stoppable."""
        await self._wait_for_delay(delay_seconds=self.cycle_interval_seconds)

    async def _wait_for_delay(self, *, delay_seconds: float) -> None:
        """Wait for a configured delay while remaining immediately stoppable."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=delay_seconds,
            )
        except TimeoutError:
            return

    async def _notify_started(self) -> None:
        """Notify the optional observer without affecting runtime startup."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
            await observer.on_started()
        except Exception:
            _LOGGER.exception("Trading runtime startup observer failed")

    async def _notify_cycle_completed(self, *, result: TradingResult) -> None:
        """Notify the optional observer about a successful cycle."""
        observer = self.runtime_observer

        if observer is None:
            return

        try:
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

    def _log_result(self, *, result: TradingResult) -> None:
        """Log a safe summary without credentials or sensitive payloads."""
        if result.executed:
            order_id = result.order.order_id if result.order is not None else "unknown"
            _LOGGER.info(
                "Trading cycle submitted an order: symbol=%s order_id=%s",
                self.symbol,
                order_id,
            )
            return

        if result.decision.should_execute:
            _LOGGER.info(
                "Trading cycle approved without order submission: symbol=%s "
                "mode=%s reason=%s",
                self.symbol,
                self.trade_mode.value,
                result.reason,
            )
            return

        _LOGGER.info(
            "Trading cycle completed without execution: symbol=%s reason=%s",
            self.symbol,
            result.reason,
        )
