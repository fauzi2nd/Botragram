"""
Botragram

Description:
    Main Trading Engine orchestrator.

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
import logging
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.app_settings import AppSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.config.strategy_settings import StrategySettings
from botragram.enums.order_side import OrderSide
from botragram.enums.order_type import OrderType
from botragram.enums.signal_type import SignalType
from botragram.engine.order_engine import OrderEngine
from botragram.engine.pnl_engine import PnLEngine
from botragram.engine.position_engine import PositionEngine
from botragram.engine.risk_engine import RiskEngine
from botragram.engine.signal_engine import SignalEngine
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.bybit.client import BybitClient
from botragram.strategies.ema_cross import EMACrossStrategy

logger = logging.getLogger(__name__)


# =============================================================================
# Trading Engine Class
# =============================================================================
class TradingEngine:
    """Main trading bot orchestrator coordinating all sub-engines."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        exchange_client: BaseExchangeClient | None = None,
        market_settings: MarketSettings | None = None,
        risk_settings: RiskSettings | None = None,
        strategy_settings: StrategySettings | None = None,
    ) -> None:
        """Initialize TradingEngine and sub-engines.

        Args:
            settings: AppSettings instance.
            exchange_client: BaseExchangeClient instance.
            market_settings: MarketSettings instance.
            risk_settings: RiskSettings instance.
            strategy_settings: StrategySettings instance.
        """
        self._settings = settings or AppSettings()
        self._market = market_settings or MarketSettings()
        self._exchange = exchange_client or BybitClient(testnet=True)

        # Sub-engines
        self._strategy = EMACrossStrategy(
            fast_period=strategy_settings.fast_period if strategy_settings else 9,
            slow_period=strategy_settings.slow_period if strategy_settings else 21,
        )
        self._signal_engine = SignalEngine(strategy=self._strategy)
        self._risk_engine = RiskEngine(settings=risk_settings)
        self._position_engine = PositionEngine()
        self._order_engine = OrderEngine(exchange_client=self._exchange)
        self._pnl_engine = PnLEngine()

        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        """Return engine running state.

        Returns:
            True if running, False otherwise.
        """
        return self._is_running

    async def start(self) -> None:
        """Start trading engine lifecycle."""
        self._is_running = True
        logger.info(
            f"TradingEngine started: mode={self._settings.trade_mode.value}, "
            f"symbol={self._market.symbol}, strategy={self._strategy.name}"
        )

    async def stop(self) -> None:
        """Stop trading engine and close connections."""
        self._is_running = False
        await self._exchange.close()
        logger.info("TradingEngine stopped")

    async def process_tick(self) -> None:
        """Process a single market tick/cycle evaluation."""
        if not self._is_running:
            return

        ticker = await self._exchange.fetch_ticker(self._market.symbol)
        candles = await self._exchange.fetch_candles(
            symbol=self._market.symbol, interval=self._market.interval, limit=100
        )

        signal = self._signal_engine.evaluate(candles)
        if signal == SignalType.NEUTRAL:
            return

        # Check existing position state
        has_pos = self._position_engine.has_active_position(self._market.symbol)

        if signal in (SignalType.BUY_ENTRY, SignalType.SELL_ENTRY) and not has_pos:
            side = OrderSide.BUY if signal == SignalType.BUY_ENTRY else OrderSide.SELL
            qty = self._risk_engine.calculate_position_size(
                account_balance=Decimal("10000.0"),
                entry_price=ticker.last_price,
            )

            if self._risk_engine.validate_order(qty, ticker.last_price):
                order_res = await self._order_engine.execute_order(
                    symbol=self._market.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=qty,
                    price=ticker.last_price,
                )
                logger.info(f"Order executed successfully: id={order_res.order_id}")
