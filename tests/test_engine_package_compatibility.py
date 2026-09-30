"""
Botragram

Description:
    Stable engine import identity after domain-context grouping.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.engine import RiskEngine as PackageRiskEngine
from botragram.engine import TradingEngine as PackageTradingEngine
from botragram.engine.accounting.pnl_engine import PnLEngine as AccountingPnLEngine
from botragram.engine.backtest.backtest_engine import (
    BacktestEngine as ContextBacktestEngine,
)
from botragram.engine.backtest_engine import BacktestEngine
from botragram.engine.cfd.cfd_financing_engine import (
    CfdFinancingEngine as ContextCfdFinancingEngine,
)
from botragram.engine.cfd.cfd_sizing_engine import (
    CfdSizingEngine as ContextCfdSizingEngine,
)
from botragram.engine.cfd.market_calendar import (
    MarketCalendarEngine as ContextMarketCalendarEngine,
)
from botragram.engine.cfd_financing_engine import CfdFinancingEngine
from botragram.engine.cfd_sizing_engine import CfdSizingEngine
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.engine.order.order_engine import OrderEngine as ContextOrderEngine
from botragram.engine.order.order_engine import (
    OrderExchangeClient as ContextOrderExchangeClient,
)
from botragram.engine.order_engine import OrderEngine, OrderExchangeClient
from botragram.engine.pnl_engine import PnLEngine
from botragram.engine.portfolio.portfolio_engine import (
    PortfolioEngine as ContextPortfolioEngine,
)
from botragram.engine.portfolio_engine import PortfolioEngine
from botragram.engine.position.position_engine import (
    PositionEngine as ContextPositionEngine,
)
from botragram.engine.position.position_exit_engine import (
    PositionExitEngine as ContextPositionExitEngine,
)
from botragram.engine.position_engine import PositionEngine
from botragram.engine.position_exit_engine import PositionExitEngine
from botragram.engine.risk.risk_engine import (
    DEFAULT_BREAKEVEN_FEE_BUFFER as ContextBreakevenFeeBuffer,
)
from botragram.engine.risk.risk_engine import RiskEngine as ContextRiskEngine
from botragram.engine.risk_engine import DEFAULT_BREAKEVEN_FEE_BUFFER, RiskEngine
from botragram.engine.signal_engine import SignalEngine
from botragram.engine.trading.signal_engine import (
    SignalEngine as ContextSignalEngine,
)
from botragram.engine.trading.trading_engine import (
    TradingEngine as ContextTradingEngine,
)
from botragram.engine.trading_engine import TradingEngine

__all__: list[str] = []


def test_engine_legacy_imports_preserve_context_class_identity() -> None:
    """Consumers of old and grouped paths receive identical engine classes."""
    assert BacktestEngine is ContextBacktestEngine
    assert CfdFinancingEngine is ContextCfdFinancingEngine
    assert CfdSizingEngine is ContextCfdSizingEngine
    assert MarketCalendarEngine is ContextMarketCalendarEngine
    assert OrderEngine is ContextOrderEngine
    assert OrderExchangeClient is ContextOrderExchangeClient
    assert PnLEngine is AccountingPnLEngine
    assert PortfolioEngine is ContextPortfolioEngine
    assert PositionEngine is ContextPositionEngine
    assert PositionExitEngine is ContextPositionExitEngine
    assert RiskEngine is ContextRiskEngine is PackageRiskEngine
    assert SignalEngine is ContextSignalEngine
    assert TradingEngine is ContextTradingEngine is PackageTradingEngine
    assert DEFAULT_BREAKEVEN_FEE_BUFFER is ContextBreakevenFeeBuffer
