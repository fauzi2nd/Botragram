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
_DECIMAL_ZERO = Decimal("0")
_DEFAULT_BALANCE_ASSET = "USDT"
_APPROVED_DECISION_RISK_ERROR = "Approved trading decision requires a risk result"


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
    ) -> TradingResult:
        """Execute one complete trading cycle."""
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
            asset=self.balance_asset,
        )

        decision = self.trading_engine.evaluate(
            signal=signal,
            account_balance=balance,
            has_open_position=has_position,
            current_drawdown_pct=current_drawdown_pct,
        )

        if not decision.should_execute:
            return TradingResult(
                executed=False,
                decision=decision,
                order=None,
                reason=decision.reason,
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
