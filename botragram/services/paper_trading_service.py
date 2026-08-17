"""
Botragram

Description:
    Persistent paper-trading execution and portfolio simulation.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Final, Protocol
from uuid import NAMESPACE_URL, uuid5

from botragram.engine import PnLEngine, TradingEngine
from botragram.enums import (
    Interval,
    NotificationType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
)
from botragram.models import (
    Notification,
    Order,
    Position,
    RiskResult,
    Signal,
    Ticker,
    Trade,
    TradingDecision,
    TradingResult,
)
from botragram.repositories import (
    OrderRepository,
    PositionRepository,
    TradeRepository,
)
from botragram.telegram.messages import (
    get_paper_entry_message,
    get_paper_exit_message,
)

__all__ = [
    "NotificationPublisher",
    "PaperPortfolioSnapshot",
    "PaperTradingService",
]


_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_ONE: Final[Decimal] = Decimal("1")
_DEFAULT_INITIAL_BALANCE: Final[Decimal] = Decimal("10000")
_DEFAULT_FEE_RATE: Final[Decimal] = Decimal("0.001")
_DEFAULT_SLIPPAGE_RATE: Final[Decimal] = Decimal("0.0005")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class NotificationPublisher(Protocol):
    """Publish application notifications to an optional external channel."""

    async def publish(self, *, notification: Notification) -> None:
        """Publish one notification."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class PaperPortfolioSnapshot:
    """Immutable reconstructed paper portfolio metrics."""

    available_balance: Decimal
    realized_pnl: Decimal


@dataclass(slots=True, kw_only=True, frozen=True)
class PaperTradingService:
    """Simulate fills and persist a reconstructable paper portfolio."""

    order_repository: OrderRepository
    trade_repository: TradeRepository
    position_repository: PositionRepository
    trading_engine: TradingEngine
    pnl_engine: PnLEngine
    notification_publisher: NotificationPublisher | None = None
    quote_asset: str = "USDT"
    initial_balance: Decimal = _DEFAULT_INITIAL_BALANCE
    fee_rate: Decimal = _DEFAULT_FEE_RATE
    slippage_rate: Decimal = _DEFAULT_SLIPPAGE_RATE
    _execution_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Validate immutable simulation settings."""
        normalized_asset = self.quote_asset.strip().upper()

        if not normalized_asset:
            raise ValueError("Paper quote asset must not be empty")

        if self.initial_balance <= _DECIMAL_ZERO:
            raise ValueError("Paper initial balance must be greater than zero")

        if not _DECIMAL_ZERO <= self.fee_rate < _DECIMAL_ONE:
            raise ValueError("Paper fee rate must be between zero and one")

        if not _DECIMAL_ZERO <= self.slippage_rate < _DECIMAL_ONE:
            raise ValueError("Paper slippage rate must be between zero and one")

        object.__setattr__(self, "quote_asset", normalized_asset)

    async def execute(
        self,
        *,
        signal: Signal,
        current_drawdown_pct: Decimal = _DECIMAL_ZERO,
        initial_balance: Decimal | None = None,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        interval: Interval | None = None,
    ) -> TradingResult:
        """Evaluate and simulate one signal against the persisted portfolio."""
        async with self._execution_lock:
            return await self._execute_unlocked(
                signal=signal,
                current_drawdown_pct=current_drawdown_pct,
                initial_balance=initial_balance,
                order_type=order_type,
                price=price,
                interval=interval,
            )

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Close a paper position immediately when streamed SL or TP is hit."""
        async with self._execution_lock:
            position = await self.position_repository.get_by_symbol(
                symbol=ticker.symbol,
            )

            if position is None:
                return

            signal = Signal(
                symbol=ticker.symbol,
                signal_type=SignalType.HOLD,
                price=ticker.last_price,
                confidence=_DECIMAL_ZERO,
                strategy_name=(
                    position.strategy_type.value
                    if position.strategy_type is not None
                    else "paper_stream_protection"
                ),
                generated_at=ticker.timestamp,
                reason="Paper stream protection check",
            )
            marked_position = replace(
                position,
                current_price=ticker.last_price,
                unrealized_pnl=self.pnl_engine.calculate_unrealized(
                    position=position,
                    current_price=ticker.last_price,
                ),
                updated_at=ticker.timestamp,
            )
            close_reason = self._close_reason(
                position=marked_position,
                signal=signal,
            )

            if close_reason is None:
                return

            await self._close_position(
                signal=signal,
                position=marked_position,
                close_reason=close_reason,
                initial_balance=self.initial_balance,
                order_type=OrderType.MARKET,
                price=ticker.last_price,
            )

    async def _execute_unlocked(
        self,
        *,
        signal: Signal,
        current_drawdown_pct: Decimal,
        initial_balance: Decimal | None,
        order_type: OrderType,
        price: Decimal | None,
        interval: Interval | None,
    ) -> TradingResult:
        """Execute one paper action while the caller owns the execution lock."""
        starting_balance = (
            self.initial_balance if initial_balance is None else initial_balance
        )

        if starting_balance <= _DECIMAL_ZERO:
            raise ValueError("Paper initial balance must be greater than zero")

        position = await self.position_repository.get_by_symbol(symbol=signal.symbol)

        if position is not None:
            return await self._manage_position(
                signal=signal,
                position=position,
                initial_balance=starting_balance,
                order_type=order_type,
                price=price,
            )

        available_balance = await self.get_available_balance(
            initial_balance=starting_balance,
        )

        if available_balance <= _DECIMAL_ZERO:
            decision = TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason="No free paper balance is available",
            )
            return self._without_execution(decision=decision)

        if signal.signal_type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            decision = TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason="No matching paper position is open",
            )
            return self._without_execution(decision=decision)

        decision = self.trading_engine.evaluate(
            signal=signal,
            account_balance=available_balance,
            has_open_position=False,
            open_positions=await self.position_repository.get_open_positions(),
            current_drawdown_pct=current_drawdown_pct,
        )

        if not decision.should_execute:
            return self._without_execution(decision=decision)

        risk_result = decision.risk_result

        if risk_result is None:
            raise RuntimeError("Approved paper decision requires a risk result")

        return await self._open_position(
            signal=signal,
            decision=decision,
            risk_result=risk_result,
            available_balance=available_balance,
            order_type=order_type,
            price=price,
            interval=interval,
        )

    async def get_available_balance(
        self,
        *,
        initial_balance: Decimal | None = None,
    ) -> Decimal:
        """Reconstruct free balance from persisted trades and open positions."""
        snapshot = await self.get_portfolio_snapshot(
            initial_balance=initial_balance,
        )
        return snapshot.available_balance

    async def get_portfolio_snapshot(
        self,
        *,
        initial_balance: Decimal | None = None,
    ) -> PaperPortfolioSnapshot:
        """Reconstruct available balance and realized PnL in one read path."""
        starting_balance = (
            self.initial_balance if initial_balance is None else initial_balance
        )

        if starting_balance <= _DECIMAL_ZERO:
            raise ValueError("Paper initial balance must be greater than zero")

        realized_pnl = await self.get_realized_pnl()

        reserved_balance = sum(
            (
                self._reserved_balance(position)
                for position in await self.position_repository.get_all()
            ),
            start=_DECIMAL_ZERO,
        )

        return PaperPortfolioSnapshot(
            available_balance=starting_balance + realized_pnl - reserved_balance,
            realized_pnl=realized_pnl,
        )

    async def get_realized_pnl(self) -> Decimal:
        """Return cumulative net realized PnL from persisted closing trades."""
        trade_count = await self.trade_repository.count()

        if trade_count == 0:
            return _DECIMAL_ZERO

        trades = await self.trade_repository.get_latest(limit=trade_count)
        return sum(
            (trade.realized_pnl for trade in trades if trade.realized_pnl is not None),
            start=_DECIMAL_ZERO,
        )

    async def _open_position(
        self,
        *,
        signal: Signal,
        decision: TradingDecision,
        risk_result: RiskResult,
        available_balance: Decimal,
        order_type: OrderType,
        price: Decimal | None,
        interval: Interval | None,
    ) -> TradingResult:
        """Create a simulated entry fill and active position."""
        order_side, position_side = self._entry_sides(signal.signal_type)
        reference_price = signal.price if price is None else price
        fill_price = self._apply_slippage(price=reference_price, side=order_side)
        quantity = risk_result.position.quantity
        quote_quantity = fill_price * quantity
        fee = quote_quantity * self.fee_rate
        required_balance = quote_quantity / Decimal(risk_result.position.leverage) + fee

        if required_balance > available_balance:
            blocked_decision = replace(
                decision,
                should_execute=False,
                reason="Insufficient paper balance for simulated order",
            )
            return self._without_execution(decision=blocked_decision)

        order_id = self._identifier(signal=signal, action="order")
        duplicate = await self.order_repository.get_by_id(
            order_id=order_id,
            symbol=signal.symbol,
        )

        if duplicate is not None:
            return self._duplicate_result(signal=signal)

        order = self._create_order(
            order_id=order_id,
            signal=signal,
            side=order_side,
            order_type=order_type,
            quantity=quantity,
            fill_price=fill_price,
        )
        trade = self._create_trade(
            signal=signal,
            order=order,
            price=fill_price,
            fee=fee,
            realized_pnl=None,
            action="trade",
        )
        stop_loss, take_profit = (
            self.trading_engine.risk_engine.calculate_protection_levels(
                side=position_side,
                entry_price=fill_price,
                strategy_type=self._resolve_strategy_type(signal.strategy_name),
            )
        )
        position = Position(
            symbol=signal.symbol,
            side=position_side,
            quantity=quantity,
            entry_price=fill_price,
            current_price=fill_price,
            unrealized_pnl=_DECIMAL_ZERO,
            leverage=risk_result.position.leverage,
            opened_at=signal.generated_at,
            updated_at=signal.generated_at,
            stop_loss=stop_loss,
            take_profit=take_profit,
            interval=interval,
            strategy_type=self._resolve_strategy_type(signal.strategy_name),
        )

        await self.order_repository.save(order=order)
        await self.trade_repository.save(trade=trade)
        await self.position_repository.save(position=position)
        await self._publish_notification(
            notification=Notification(
                title="Paper entry executed",
                message=get_paper_entry_message(
                    order=order,
                    trade=trade,
                    position=position,
                    available_balance=available_balance - required_balance,
                ),
                level=NotificationType.ORDER,
                created_at=signal.generated_at,
            )
        )

        return TradingResult(executed=True, decision=decision, order=order)

    async def _manage_position(
        self,
        *,
        signal: Signal,
        position: Position,
        initial_balance: Decimal,
        order_type: OrderType,
        price: Decimal | None,
    ) -> TradingResult:
        """Mark an active position and close it when an exit condition fires."""
        marked_position = replace(
            position,
            current_price=signal.price,
            unrealized_pnl=self.pnl_engine.calculate_unrealized(
                position=position,
                current_price=signal.price,
            ),
            updated_at=signal.generated_at,
        )
        close_reason = self._close_reason(position=marked_position, signal=signal)

        if close_reason is None:
            await self.position_repository.update(position=marked_position)
            decision = TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason="Paper position remains open",
            )
            return self._without_execution(decision=decision)

        return await self._close_position(
            signal=signal,
            position=marked_position,
            close_reason=close_reason,
            initial_balance=initial_balance,
            order_type=order_type,
            price=price,
        )

    async def _close_position(
        self,
        *,
        signal: Signal,
        position: Position,
        close_reason: str,
        initial_balance: Decimal,
        order_type: OrderType,
        price: Decimal | None,
    ) -> TradingResult:
        """Persist a simulated exit fill and remove the active position."""
        order_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        reference_price = signal.price if price is None else price
        fill_price = self._apply_slippage(price=reference_price, side=order_side)
        quote_quantity = fill_price * position.quantity
        entry_fee = position.entry_price * position.quantity * self.fee_rate
        exit_fee = quote_quantity * self.fee_rate
        realized_pnl = self.pnl_engine.calculate_realized(
            side=position.side,
            entry_price=position.entry_price,
            exit_price=fill_price,
            quantity=position.quantity,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
        )
        order_id = self._identifier(signal=signal, action="order")
        duplicate = await self.order_repository.get_by_id(
            order_id=order_id,
            symbol=signal.symbol,
        )

        if duplicate is not None:
            return self._duplicate_result(signal=signal)

        order = self._create_order(
            order_id=order_id,
            signal=signal,
            side=order_side,
            order_type=order_type,
            quantity=position.quantity,
            fill_price=fill_price,
        )
        trade = self._create_trade(
            signal=signal,
            order=order,
            price=fill_price,
            fee=exit_fee,
            realized_pnl=realized_pnl,
            action="trade",
        )
        decision = TradingDecision(
            should_execute=True,
            signal=signal,
            risk_result=None,
            reason=close_reason,
        )

        await self.order_repository.save(order=order)
        await self.trade_repository.save(trade=trade)
        await self.position_repository.delete(symbol=position.symbol)
        available_balance = await self.get_available_balance(
            initial_balance=initial_balance,
        )
        await self._publish_notification(
            notification=Notification(
                title="Paper position closed",
                message=get_paper_exit_message(
                    order=order,
                    trade=trade,
                    available_balance=available_balance,
                    reason=close_reason,
                ),
                level=NotificationType.TRADE,
                created_at=signal.generated_at,
            )
        )

        return TradingResult(
            executed=True,
            decision=decision,
            order=order,
            reason=close_reason,
        )

    def _create_order(
        self,
        *,
        order_id: str,
        signal: Signal,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        fill_price: Decimal,
    ) -> Order:
        """Create an immutable filled paper order."""
        return Order(
            order_id=order_id,
            symbol=signal.symbol,
            side=side,
            order_type=order_type,
            status=OrderStatus.FILLED,
            quantity=quantity,
            executed_quantity=quantity,
            price=fill_price,
            created_at=signal.generated_at,
            updated_at=signal.generated_at,
        )

    @staticmethod
    def _resolve_strategy_type(strategy_name: str) -> StrategyType | None:
        """Resolve known runtime strategies while preserving custom signals."""
        try:
            return StrategyType(strategy_name)
        except ValueError:
            return None

    def _create_trade(
        self,
        *,
        signal: Signal,
        order: Order,
        price: Decimal,
        fee: Decimal,
        realized_pnl: Decimal | None,
        action: str,
    ) -> Trade:
        """Create an immutable paper fill."""
        return Trade(
            trade_id=self._identifier(signal=signal, action=action),
            order_id=order.order_id,
            symbol=signal.symbol,
            side=order.side,
            price=price,
            quantity=order.executed_quantity,
            quote_quantity=price * order.executed_quantity,
            fee=fee,
            fee_asset=self.quote_asset,
            executed_at=signal.generated_at,
            realized_pnl=realized_pnl,
        )

    def _reserved_balance(self, position: Position) -> Decimal:
        """Return margin and entry fee reserved by an open position."""
        notional = position.entry_price * position.quantity
        return notional / Decimal(position.leverage) + notional * self.fee_rate

    def _apply_slippage(self, *, price: Decimal, side: OrderSide) -> Decimal:
        """Apply adverse slippage to a simulated fill."""
        if price <= _DECIMAL_ZERO:
            raise ValueError("Paper fill price must be greater than zero")

        multiplier = (
            _DECIMAL_ONE + self.slippage_rate
            if side is OrderSide.BUY
            else _DECIMAL_ONE - self.slippage_rate
        )
        return price * multiplier

    @staticmethod
    def _entry_sides(signal_type: SignalType) -> tuple[OrderSide, PositionSide]:
        """Resolve entry order and position sides."""
        if signal_type is SignalType.BUY:
            return OrderSide.BUY, PositionSide.LONG

        if signal_type is SignalType.SELL:
            return OrderSide.SELL, PositionSide.SHORT

        raise ValueError(f"Unsupported paper entry signal: {signal_type.value!r}")

    @staticmethod
    def _close_reason(*, position: Position, signal: Signal) -> str | None:
        """Return the active exit trigger, if any."""
        if position.side is PositionSide.LONG:
            if position.stop_loss is not None and signal.price <= position.stop_loss:
                return "Paper stop-loss triggered"
            if (
                position.take_profit is not None
                and signal.price >= position.take_profit
            ):
                return "Paper take-profit triggered"
            if signal.signal_type in (SignalType.SELL, SignalType.CLOSE_LONG):
                return "Paper long position closed by signal"
            return None

        if position.side is PositionSide.SHORT:
            if position.stop_loss is not None and signal.price >= position.stop_loss:
                return "Paper stop-loss triggered"
            if (
                position.take_profit is not None
                and signal.price <= position.take_profit
            ):
                return "Paper take-profit triggered"
            if signal.signal_type in (SignalType.BUY, SignalType.CLOSE_SHORT):
                return "Paper short position closed by signal"
            return None

        raise ValueError("Paper trading does not support hedged position side")

    @staticmethod
    def _identifier(*, signal: Signal, action: str) -> str:
        """Create a deterministic identifier for duplicate protection."""
        identity = (
            f"{signal.symbol}|{signal.strategy_name}|"
            f"{signal.generated_at.isoformat()}|{action}"
        )
        return f"paper-{uuid5(NAMESPACE_URL, identity).hex}"

    async def _publish_notification(self, *, notification: Notification) -> None:
        """Publish without allowing notification failure to roll back a fill."""
        publisher = self.notification_publisher

        if publisher is None:
            return

        try:
            await publisher.publish(notification=notification)
        except Exception:
            _LOGGER.exception(
                "Paper notification failed after persistence: %s",
                notification.title,
            )

    @staticmethod
    def _without_execution(*, decision: TradingDecision) -> TradingResult:
        """Create a non-executed result from a decision."""
        return TradingResult(
            executed=False,
            decision=decision,
            order=None,
            reason=decision.reason,
        )

    @classmethod
    def _duplicate_result(cls, *, signal: Signal) -> TradingResult:
        """Create a deterministic duplicate-cycle result."""
        decision = TradingDecision(
            should_execute=False,
            signal=signal,
            risk_result=None,
            reason="Paper signal was already executed",
        )
        return cls._without_execution(decision=decision)
