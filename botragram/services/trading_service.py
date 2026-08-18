"""
Botragram

Description:
    Main trading application service.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import TradingEngine
from botragram.enums import Interval, OrderType, StrategyType, TradeMode
from botragram.models import (
    Candle,
    LiveRecoveredPositionManagementAuthorization,
    LiveRuntimePositionContext,
    Order,
    Position,
    RiskResult,
    Signal,
    TradingDecision,
    TradingResult,
)
from botragram.services.paper_trading_service import PaperTradingService

__all__ = [
    "TradingService",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DEFAULT_BALANCE_ASSET = "USDT"
_APPROVED_DECISION_RISK_ERROR = "Approved trading decision requires a risk result"
_ORDER_SUBMISSION_DISABLED_REASON = "Order submission is disabled in paper mode"
_RECOVERED_POSITION_NOT_OPEN_REASON = (
    "Recovered LIVE position is no longer open; portfolio reconciliation is required"
)
_RECOVERED_MANAGEMENT_ENTRY_DENIED_REASON = (
    "Recovered LIVE management authorization does not permit new position entry"
)


# =============================================================================
# Dependency Contracts
# =============================================================================
class _MarketDataProvider(Protocol):
    """Provide normalized historical candles for one trading cycle."""

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> Sequence[Candle]:
        """Return normalized candles for a market interval."""
        ...


class _SignalGenerator(Protocol):
    """Generate and durably record one trading signal."""

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Return a generated signal after persistence."""
        ...


class _AccountBalanceProvider(Protocol):
    """Provide free account balance for risk evaluation."""

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return free balance for an asset."""
        ...


class _PositionPortfolioProvider(Protocol):
    """Provide authoritative or cached active position portfolios."""

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return active positions."""
        ...


class _OrderSubmitter(Protocol):
    """Submit a standard order after risk approval."""

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Submit and return one order."""
        ...


class _LiveFuturesEntryExecutor(Protocol):
    """Submit one protected LIVE Futures entry."""

    async def execute(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        interval: Interval,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Submit and return one protected entry order."""
        ...


# =============================================================================
# Trading Service
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class TradingService:
    """Execute a complete trading workflow."""

    market_service: _MarketDataProvider
    strategy_service: _SignalGenerator
    account_service: _AccountBalanceProvider
    position_service: _PositionPortfolioProvider
    order_service: _OrderSubmitter
    trading_engine: TradingEngine
    paper_trading_service: PaperTradingService | None = None
    live_futures_entry_service: _LiveFuturesEntryExecutor | None = None

    balance_asset: str = _DEFAULT_BALANCE_ASSET
    trade_mode: TradeMode = TradeMode.PAPER

    def __post_init__(self) -> None:
        """Normalize immutable service configuration."""
        object.__setattr__(
            self,
            "balance_asset",
            self._normalize_asset(self.balance_asset),
        )

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        strategy_type: StrategyType | None = None,
        live_management_authorization: (
            LiveRecoveredPositionManagementAuthorization | None
        ) = None,
        current_drawdown_pct: Decimal = _DECIMAL_ZERO,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        open_positions: Sequence[Position] | None = None,
        submit_order: bool = True,
    ) -> TradingResult:
        """Execute one complete trading cycle.

        Args:
            symbol: Trading pair symbol.
            interval: Candle interval used by the strategy.
            strategy_type: Explicit strategy for a runtime context. Omitted only
                by existing non-context callers using the configured default.
            live_management_authorization: Exact recovered LIVE context capability.
                It permits management only and never authorizes a new LIVE entry.
            candle_limit: Maximum historical candles to evaluate.
            current_drawdown_pct: Current account drawdown as a ratio.
            order_type: Exchange order type when execution is approved.
            price: Optional limit or stop price.
            account_balance_override: Optional balance used instead of reading
                the exchange account. Intended for paper-mode evaluation.
            synchronize_position: Whether to refresh the position from the
                exchange before loading a portfolio snapshot.
            open_positions: Optional portfolio snapshot. When omitted, the
                current portfolio is loaded once for this execution. A caller
                processing ranked candidates can refresh or update a snapshot
                between evaluations.
            submit_order: Whether an approved decision may reach the exchange.
                Set this to false for paper trading.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        if (
            live_management_authorization is not None
            and self.trade_mode is not TradeMode.LIVE
        ):
            raise ValueError(
                "Recovered LIVE management authorization requires LIVE mode"
            )

        if account_balance_override is not None and account_balance_override <= 0:
            raise ValueError("Account balance override must be greater than zero")

        candles = await self.market_service.get_candles(
            symbol=normalized_symbol,
            interval=interval,
            limit=candle_limit,
        )

        signal = await self.strategy_service.generate_and_save(
            candles=candles,
            strategy_type=strategy_type,
        )

        if not submit_order and self.paper_trading_service is not None:
            return await self.paper_trading_service.execute(
                signal=signal,
                current_drawdown_pct=current_drawdown_pct,
                initial_balance=account_balance_override,
                order_type=order_type,
                price=price,
                interval=interval,
            )

        # LIVE entry must evaluate an authoritative portfolio snapshot directly
        # before the protected entry boundary; caller snapshots are PAPER-only.
        portfolio_positions = (
            None if self.trade_mode is TradeMode.LIVE else open_positions
        )

        if portfolio_positions is None:
            portfolio_positions = await self.position_service.get_all(
                synchronize=(self.trade_mode is TradeMode.LIVE or synchronize_position),
            )

        has_position = any(
            position.symbol.upper() == normalized_symbol
            and position.quantity > _DECIMAL_ZERO
            for position in portfolio_positions
        )

        management_authorization = live_management_authorization
        if management_authorization is not None:
            if strategy_type is None:
                raise ValueError(
                    "Recovered LIVE management requires an explicit strategy type"
                )

            runtime_context = LiveRuntimePositionContext(
                symbol=normalized_symbol,
                interval=interval,
                strategy_type=strategy_type,
            )
            if not management_authorization.authorizes_context(
                context=runtime_context,
            ):
                raise RuntimeError(
                    "Recovered LIVE management authorization does not cover runtime "
                    "context: "
                    f"{runtime_context.symbol}:{runtime_context.interval.value}"
                )

            if not has_position:
                return self._non_executing_result(
                    signal=signal,
                    reason=_RECOVERED_POSITION_NOT_OPEN_REASON,
                    requires_portfolio_reconciliation=True,
                )

        balance = (
            None if self.trade_mode is TradeMode.LIVE else account_balance_override
        )

        if balance is None:
            balance = await self.account_service.get_free_balance(
                asset=self.balance_asset,
            )

        decision = self.trading_engine.evaluate(
            signal=signal,
            account_balance=balance,
            has_open_position=has_position,
            open_positions=portfolio_positions,
            current_drawdown_pct=current_drawdown_pct,
        )

        if not decision.should_execute:
            return TradingResult(
                executed=False,
                decision=decision,
                order=None,
                reason=decision.reason,
            )

        if (
            management_authorization is not None
            and not management_authorization.new_live_entry_allowed
        ):
            return TradingResult(
                executed=False,
                decision=replace(
                    decision,
                    should_execute=False,
                    reason=_RECOVERED_MANAGEMENT_ENTRY_DENIED_REASON,
                ),
                order=None,
                reason=_RECOVERED_MANAGEMENT_ENTRY_DENIED_REASON,
            )

        if not submit_order:
            return TradingResult(
                executed=False,
                decision=decision,
                order=None,
                reason=_ORDER_SUBMISSION_DISABLED_REASON,
            )

        if self.trade_mode is TradeMode.LIVE:
            live_entry_service = self.live_futures_entry_service

            if live_entry_service is None:
                raise RuntimeError("LIVE trading requires protected Futures entry")

            order = await live_entry_service.execute(
                signal=signal,
                risk_result=self._require_risk_result(decision=decision),
                interval=interval,
                order_type=order_type,
                price=price,
            )
            return TradingResult(
                executed=True,
                decision=decision,
                order=order,
            )

        order = await self.order_service.submit(
            signal=signal,
            risk_result=self._require_risk_result(decision=decision),
            order_type=order_type,
            price=price,
        )

        return TradingResult(
            executed=True,
            decision=decision,
            order=order,
        )

    @staticmethod
    def _require_risk_result(*, decision: TradingDecision) -> RiskResult:
        """Return an approved decision risk result with explicit narrowing."""
        risk_result = decision.risk_result

        if risk_result is None:
            raise RuntimeError(_APPROVED_DECISION_RISK_ERROR)

        return risk_result

    @staticmethod
    def _non_executing_result(
        *,
        signal: Signal,
        reason: str,
        requires_portfolio_reconciliation: bool = False,
    ) -> TradingResult:
        """Return an explicit non-executing result for a denied LIVE boundary."""
        return TradingResult(
            executed=False,
            decision=TradingDecision(
                should_execute=False,
                signal=signal,
                risk_result=None,
                reason=reason,
                requires_portfolio_reconciliation=requires_portfolio_reconciliation,
            ),
            order=None,
            reason=reason,
        )

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol

    @staticmethod
    def _normalize_asset(
        asset: str,
    ) -> str:
        """Normalize and validate a balance asset."""
        normalized_asset = asset.strip().upper()

        if not normalized_asset:
            raise ValueError("Balance asset must not be empty")

        return normalized_asset
