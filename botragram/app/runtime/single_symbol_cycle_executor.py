"""
Botragram

Description:
    Single-symbol service adapter for runtime cycle execution.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderType, StrategyType
from botragram.models import LiveRecoveredPositionManagementAuthorization, TradingResult

__all__ = ["SingleSymbolTradingCycleExecutor"]


class SingleSymbolExecutionProvider(Protocol):
    """Execute the existing single-symbol trading workflow."""

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
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> TradingResult:
        """Execute and return one single-symbol trading result."""
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
        strategy_type: StrategyType | None = None,
        live_management_authorization: (
            LiveRecoveredPositionManagementAuthorization | None
        ) = None,
        current_drawdown_pct: Decimal = Decimal("0"),
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        account_balance_override: Decimal | None = None,
        synchronize_position: bool = True,
        submit_order: bool = True,
    ) -> Sequence[TradingResult]:
        """Execute the existing single-symbol workflow as one cycle result."""
        if live_management_authorization is None:
            result = await self.trading_service.execute(
                symbol=symbol,
                interval=interval,
                strategy_type=strategy_type,
                candle_limit=candle_limit,
                current_drawdown_pct=current_drawdown_pct,
                order_type=order_type,
                price=price,
                account_balance_override=account_balance_override,
                synchronize_position=synchronize_position,
                submit_order=submit_order,
            )
            return (result,)

        result = await self.trading_service.execute(
            symbol=symbol,
            interval=interval,
            strategy_type=strategy_type,
            live_management_authorization=live_management_authorization,
            candle_limit=candle_limit,
            current_drawdown_pct=current_drawdown_pct,
            order_type=order_type,
            price=price,
            account_balance_override=account_balance_override,
            synchronize_position=synchronize_position,
            submit_order=submit_order,
        )
        return (result,)
