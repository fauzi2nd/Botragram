"""
Botragram

Description:
    Application dependency construction and lifecycle provider.

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
import logging
from pathlib import Path
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config import Settings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.constants import (
    BINANCE_REST_BASE_URL,
    BINANCE_TESTNET_REST_BASE_URL,
    BINANCE_TESTNET_WEBSOCKET_BASE_URL,
    BINANCE_WEBSOCKET_BASE_URL,
)
from botragram.engine import (
    OrderEngine,
    PositionEngine,
    RiskEngine,
    SignalEngine,
    TradingEngine,
)
from botragram.enums import ExchangeType
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.exchanges.factory import ExchangeFactory
from botragram.repositories import (
    CandleRepository,
    OrderRepository,
    PositionRepository,
    SignalRepository,
    TradeRepository,
)
from botragram.services import (
    AccountService,
    MarketService,
    OrderService,
    PositionService,
    StrategyService,
)
from botragram.services.trading_service import TradingService
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteOrderRepository,
    SQLitePositionRepository,
    SQLiteSignalRepository,
    SQLiteTradeRepository,
)
from botragram.strategies.factory import StrategyFactory

__all__ = [
    "DependencyProvider",
]


# =============================================================================
# Constants
# =============================================================================
_DATABASE_PATH_ERROR = "Database path must not be empty"
_PROVIDER_NOT_INITIALIZED_ERROR = "Dependency provider has not been initialized"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Dependency Provider
# =============================================================================
class DependencyProvider:
    """Construct and own application dependencies from one settings object."""

    __slots__ = (
        "_account_service",
        "_candle_repository",
        "_database",
        "_database_path",
        "_exchange_client",
        "_initialized",
        "_market_service",
        "_order_engine",
        "_order_repository",
        "_order_service",
        "_position_engine",
        "_position_repository",
        "_position_service",
        "_risk_engine",
        "_settings",
        "_signal_engine",
        "_signal_repository",
        "_strategy_service",
        "_stream_client",
        "_trade_repository",
        "_trading_engine",
        "_trading_service",
    )

    def __init__(
        self,
        *,
        database_path: str | Path,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the application dependency provider.

        Args:
            database_path: SQLite database file path.
            settings: Immutable application configuration. Defaults preserve
                the existing repository-only construction API.

        Raises:
            ValueError: If the database path is empty.
        """
        normalized_database_path = str(database_path).strip()

        if not normalized_database_path:
            raise ValueError(_DATABASE_PATH_ERROR)

        self._database_path = Path(normalized_database_path)
        self._settings = (
            settings
            if settings is not None
            else Settings(exchange=ExchangeSettings(exchange=ExchangeType.BINANCE))
        )
        self._database: SQLiteDatabase | None = None
        self._exchange_client: BaseExchangeClient | None = None
        self._stream_client: BaseStreamClient | None = None

        self._candle_repository: CandleRepository | None = None
        self._signal_repository: SignalRepository | None = None
        self._order_repository: OrderRepository | None = None
        self._trade_repository: TradeRepository | None = None
        self._position_repository: PositionRepository | None = None

        self._signal_engine: SignalEngine | None = None
        self._risk_engine: RiskEngine | None = None
        self._trading_engine: TradingEngine | None = None
        self._order_engine: OrderEngine | None = None
        self._position_engine: PositionEngine | None = None

        self._market_service: MarketService | None = None
        self._strategy_service: StrategyService | None = None
        self._order_service: OrderService | None = None
        self._position_service: PositionService | None = None
        self._account_service: AccountService | None = None
        self._trading_service: TradingService | None = None
        self._initialized = False

    # =========================================================================
    # Lifecycle
    # =========================================================================

    @property
    def is_initialized(self) -> bool:
        """Return whether dependencies have been initialized."""
        return self._initialized

    @property
    def settings(self) -> Settings:
        """Return the immutable settings used to construct dependencies."""
        return self._settings

    async def initialize(self) -> None:
        """Initialize repositories, exchange clients, engines, and services."""
        if self._initialized:
            _LOGGER.debug("Dependency provider is already initialized")
            return

        database = SQLiteDatabase(database_path=self._database_path)
        _LOGGER.info(
            "Dependency initialization starting",
            extra={
                "database_path": str(self._database_path),
                "exchange": self._settings.exchange.exchange.value,
                "testnet": self._settings.exchange.testnet,
            },
        )

        try:
            await database.connect()
            await SQLiteMigrationManager(database=database).initialize()

            self._database = database
            self._build_repositories(database=database)
            await self._build_exchange_dependencies()
            self._build_engines()
            self._build_services()
            self._initialized = True
            _LOGGER.info("Dependencies initialized")
        except BaseException:
            await self.close()
            _LOGGER.exception("Dependency initialization failed")
            raise

    async def close(self) -> None:
        """Close owned network and database resources in reverse order."""
        exchange_client = self._exchange_client
        stream_client = self._stream_client
        database = self._database

        self._clear_dependencies()
        _LOGGER.debug("Dependency shutdown starting")

        try:
            if stream_client is not None:
                await stream_client.close()
        finally:
            try:
                if exchange_client is not None:
                    await exchange_client.close()
            finally:
                if database is not None:
                    await database.close()

        _LOGGER.info("Dependencies shut down")

    # =========================================================================
    # Repository Dependencies
    # =========================================================================

    @property
    def candle_repository(self) -> CandleRepository:
        """Return the configured candle repository."""
        return self._require(self._candle_repository)

    @property
    def signal_repository(self) -> SignalRepository:
        """Return the configured signal repository."""
        return self._require(self._signal_repository)

    @property
    def order_repository(self) -> OrderRepository:
        """Return the configured order repository."""
        return self._require(self._order_repository)

    @property
    def trade_repository(self) -> TradeRepository:
        """Return the configured trade repository."""
        return self._require(self._trade_repository)

    @property
    def position_repository(self) -> PositionRepository:
        """Return the configured position repository."""
        return self._require(self._position_repository)

    # =========================================================================
    # Exchange, Engine, and Service Dependencies
    # =========================================================================

    @property
    def exchange_client(self) -> BaseExchangeClient:
        """Return the configured exchange client."""
        return self._require(self._exchange_client)

    @property
    def stream_client(self) -> BaseStreamClient:
        """Return the configured exchange stream client."""
        return self._require(self._stream_client)

    @property
    def signal_engine(self) -> SignalEngine:
        """Return the configured signal engine."""
        return self._require(self._signal_engine)

    @property
    def risk_engine(self) -> RiskEngine:
        """Return the configured risk engine."""
        return self._require(self._risk_engine)

    @property
    def trading_engine(self) -> TradingEngine:
        """Return the configured trading engine."""
        return self._require(self._trading_engine)

    @property
    def order_engine(self) -> OrderEngine:
        """Return the configured order engine."""
        return self._require(self._order_engine)

    @property
    def position_engine(self) -> PositionEngine:
        """Return the configured position engine."""
        return self._require(self._position_engine)

    @property
    def market_service(self) -> MarketService:
        """Return the configured market service."""
        return self._require(self._market_service)

    @property
    def strategy_service(self) -> StrategyService:
        """Return the configured strategy service."""
        return self._require(self._strategy_service)

    @property
    def order_service(self) -> OrderService:
        """Return the configured order service."""
        return self._require(self._order_service)

    @property
    def position_service(self) -> PositionService:
        """Return the configured position service."""
        return self._require(self._position_service)

    @property
    def account_service(self) -> AccountService:
        """Return the configured account service."""
        return self._require(self._account_service)

    @property
    def trading_service(self) -> TradingService:
        """Return the configured trading service."""
        return self._require(self._trading_service)

    # =========================================================================
    # Construction Helpers
    # =========================================================================

    def _build_repositories(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Construct SQLite repository implementations."""
        self._candle_repository = SQLiteCandleRepository(database=database)
        self._signal_repository = SQLiteSignalRepository(database=database)
        self._order_repository = SQLiteOrderRepository(database=database)
        self._trade_repository = SQLiteTradeRepository(database=database)
        self._position_repository = SQLitePositionRepository(database=database)

    async def _build_exchange_dependencies(self) -> None:
        """Construct and connect the configured exchange dependencies."""
        exchange = self._settings.exchange

        if exchange.exchange is not ExchangeType.BINANCE:
            raise ValueError(
                "DependencyProvider currently supports the Binance exchange"
            )

        rest_base_url, websocket_base_url = self._get_binance_urls(
            testnet=exchange.testnet,
        )
        exchange_client, stream_client = ExchangeFactory.create(
            exchange_type=exchange.exchange,
            rest_base_url=rest_base_url,
            websocket_base_url=websocket_base_url,
            api_key=exchange.api_key,
            api_secret=exchange.api_secret,
        )
        self._exchange_client = exchange_client
        self._stream_client = stream_client

        await exchange_client.connect()
        await stream_client.connect()

    def _build_engines(self) -> None:
        """Construct engines from configured strategies and exchange clients."""
        exchange_client = self.exchange_client
        self._signal_engine = SignalEngine(
            strategy=StrategyFactory.create(settings=self._settings.strategy),
        )
        self._risk_engine = RiskEngine(settings=self._settings.risk)
        self._trading_engine = TradingEngine(risk_engine=self.risk_engine)
        self._order_engine = OrderEngine(exchange_client=exchange_client)
        self._position_engine = PositionEngine(exchange_client=exchange_client)

    def _build_services(self) -> None:
        """Construct services from repositories, engines, and clients."""
        exchange_client = self.exchange_client
        self._market_service = MarketService(
            exchange_client=exchange_client,
            stream_client=self.stream_client,
            candle_repository=self.candle_repository,
        )
        self._strategy_service = StrategyService(
            signal_engine=self.signal_engine,
            signal_repository=self.signal_repository,
        )
        self._order_service = OrderService(
            order_engine=self.order_engine,
            order_repository=self.order_repository,
        )
        self._position_service = PositionService(
            position_engine=self.position_engine,
            position_repository=self.position_repository,
        )
        self._account_service = AccountService(exchange_client=exchange_client)
        self._trading_service = TradingService(
            market_service=self.market_service,
            strategy_service=self.strategy_service,
            account_service=self.account_service,
            position_service=self.position_service,
            order_service=self.order_service,
            trading_engine=self.trading_engine,
            balance_asset=self._settings.market.quote_asset,
        )

    @staticmethod
    def _get_binance_urls(
        *,
        testnet: bool,
    ) -> tuple[str, str]:
        """Return REST and WebSocket URLs for the selected Binance network."""
        if testnet:
            return (
                BINANCE_TESTNET_REST_BASE_URL,
                BINANCE_TESTNET_WEBSOCKET_BASE_URL,
            )

        return BINANCE_REST_BASE_URL, BINANCE_WEBSOCKET_BASE_URL

    @staticmethod
    def _require[Dependency](
        dependency: Dependency | None,
    ) -> Dependency:
        """Return an initialized dependency or raise a lifecycle error."""
        if dependency is None:
            raise RuntimeError(_PROVIDER_NOT_INITIALIZED_ERROR)

        return dependency

    def _clear_dependencies(self) -> None:
        """Clear initialized dependencies before releasing resources."""
        self._candle_repository = None
        self._signal_repository = None
        self._order_repository = None
        self._trade_repository = None
        self._position_repository = None
        self._exchange_client = None
        self._stream_client = None
        self._signal_engine = None
        self._risk_engine = None
        self._trading_engine = None
        self._order_engine = None
        self._position_engine = None
        self._market_service = None
        self._strategy_service = None
        self._order_service = None
        self._position_service = None
        self._account_service = None
        self._trading_service = None
        self._database = None
        self._initialized = False

    async def __aenter__(self) -> DependencyProvider:
        """Initialize dependencies for an asynchronous context."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Close dependencies after an asynchronous context."""
        del exc_type, exc_value, traceback
        await self.close()
