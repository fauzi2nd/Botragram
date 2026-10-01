"""
Botragram

Description:
    Compose fresh in-memory PAPER sessions for isolated historical replay.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass

from botragram.config.risk_settings import RiskSettings
from botragram.engine.accounting.pnl_engine import PnLEngine
from botragram.engine.backtest.backtest_engine import BacktestSession
from botragram.engine.risk.risk_engine import RiskEngine
from botragram.engine.trading.trading_engine import TradingEngine
from botragram.models import BacktestRequest
from botragram.services.paper_trading_service import PaperTradingService
from botragram.storage.memory import (
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)

__all__ = ["InMemoryBacktestSessionFactory"]


@dataclass(slots=True, kw_only=True, frozen=True)
class InMemoryBacktestSessionFactory:
    """Create a fresh PAPER session without runtime DB or network authority."""

    def create(
        self, *, request: BacktestRequest, risk_settings: RiskSettings
    ) -> BacktestSession:
        """Build one request-scoped memory-backed PAPER execution session."""
        order_repository = MemoryOrderRepository()
        trade_repository = MemoryTradeRepository()
        position_repository = MemoryPositionRepository()
        paper_service = PaperTradingService(
            order_repository=order_repository,
            trade_repository=trade_repository,
            position_repository=position_repository,
            trading_engine=TradingEngine(
                risk_engine=RiskEngine(settings=risk_settings),
            ),
            pnl_engine=PnLEngine(),
            initial_balance=request.initial_balance,
            fee_rate=request.fee_rate,
            slippage_rate=request.slippage_rate,
            close_on_opposite_signal=request.close_on_opposite_signal,
        )
        return BacktestSession(
            paper_service=paper_service,
            position_repository=position_repository,
            trade_repository=trade_repository,
        )
