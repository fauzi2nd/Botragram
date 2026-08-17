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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import TradingEngine
from botragram.enums import Interval, OrderType
from botragram.models import Position, TradingResult
from botragram.services.account_service import AccountService
from botragram.services.market_service import MarketService
from botragram.services.order_service import OrderService
from botragram.services.paper_trading_service import PaperTradingService
from botragram.services.position_service import PositionService
from botragram.services.strategy_service import StrategyService

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

    market_service: MarketService
    strategy_service: StrategyService
    account_service: AccountService
    position_service: PositionService
    order_service: OrderService
    trading_engine: TradingEngine
    paper_trading_service: PaperTradingService | None = None

    balance_asset: str = _DEFAULT_BALANCE_ASSET

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

        if account_balance_override is not None and account_balance_override <= 0:
            raise ValueError("Account balance override must be greater than zero")

        candles = await self.market_service.get_candles(
            symbol=normalized_symbol,
            interval=interval,
            limit=candle_limit,
        )

        signal = await self.strategy_service.generate_and_save(
            candles=candles,
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

        portfolio_positions = open_positions

        if portfolio_positions is None:
            portfolio_positions = await self.position_service.get_all(
                synchronize=synchronize_position,
            )

        has_position = any(
            position.symbol.upper() == normalized_symbol
            and position.quantity > _DECIMAL_ZERO
            for position in portfolio_positions
        )

        balance = account_balance_override

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

        if not submit_order:
            return TradingResult(
                executed=False,
                decision=decision,
                order=None,
                reason=_ORDER_SUBMISSION_DISABLED_REASON,
            )

        risk_result = decision.risk_result

        if risk_result is None:
            raise RuntimeError(_APPROVED_DECISION_RISK_ERROR)

        order = await self.order_service.submit(
            signal=signal,
            risk_result=risk_result,
            order_type=order_type,
            price=price,
        )

        return TradingResult(
            executed=True,
            decision=decision,
            order=order,
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
