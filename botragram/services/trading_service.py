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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import TradingEngine
from botragram.enums import Interval, OrderType
from botragram.models import TradingResult
from botragram.services.account_service import AccountService
from botragram.services.market_service import MarketService
from botragram.services.order_service import OrderService
from botragram.services.position_service import PositionService
from botragram.services.strategy_service import StrategyService

__all__ = [
    "TradingService",
]


# =============================================================================
# Constants
# =============================================================================
_DEFAULT_BALANCE_ASSET = "USDT"

_DEFAULT_DRAWDOWN = Decimal("0")


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

    async def execute(
        self,
        *,
        symbol: str,
        interval: Interval,
        candle_limit: int,
        order_type: OrderType = OrderType.MARKET,
    ) -> TradingResult:
        """Execute one trading cycle."""

        normalized_symbol = self._normalize_symbol(symbol)

        candles = await self.market_service.get_candles(
            symbol=normalized_symbol,
            interval=interval,
            limit=candle_limit,
        )

        signal = await self.strategy_service.generate_and_save(
            candles=candles,
        )

        has_position = await self.position_service.has_position(
            symbol=normalized_symbol,
            synchronize=True,
        )

        balance = await self.account_service.get_free_balance(
            asset=_DEFAULT_BALANCE_ASSET,
        )

        decision = self.trading_engine.evaluate(
            signal=signal,
            account_balance=balance,
            has_open_position=has_position,
            current_drawdown_pct=_DEFAULT_DRAWDOWN,
        )

        if not decision.should_execute:
            return TradingResult(
                executed=False,
                decision=decision,
                order=None,
                reason=decision.reason,
            )

        if decision.risk_result is None:
            raise RuntimeError("Approved trading decision requires a risk result")

        order = await self.order_service.submit(
            signal=signal,
            risk_result=decision.risk_result,
            order_type=order_type,
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
        """Normalize a trading symbol."""

        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
