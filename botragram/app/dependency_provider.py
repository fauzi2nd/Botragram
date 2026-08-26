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

from botragram.app.live_futures_user_data_service import (
    LiveFuturesUserDataService,
)
from botragram.app.market_type_switch import (
    MarketTypeSwitchService,
    RuntimeRestartCoordinator,
)
from botragram.app.runtime_control import TradingRuntimeControl
from botragram.app.trading_runner import (
    AutonomousLiveTradingCycleExecutor,
    AutonomousPaperTradingCycleExecutor,
    HumanConfirmedPaperTradingCycleExecutor,
    SingleSymbolTradingCycleExecutor,
    TradingCycleExecutor,
)

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config import Settings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.constants import (
    BINANCE_FUTURES_REST_BASE_URL,
    BINANCE_FUTURES_TESTNET_REST_BASE_URL,
    BINANCE_FUTURES_TESTNET_WEBSOCKET_BASE_URL,
    BINANCE_FUTURES_WEBSOCKET_BASE_URL,
    BINANCE_REST_BASE_URL,
    BINANCE_TESTNET_REST_BASE_URL,
    BINANCE_TESTNET_WEBSOCKET_BASE_URL,
    BINANCE_WEBSOCKET_BASE_URL,
)
from botragram.engine import (
    OrderEngine,
    PnLEngine,
    PortfolioEngine,
    PositionEngine,
    RiskEngine,
    SignalEngine,
    TradingEngine,
)
from botragram.enums import (
    ExchangeEnvironment,
    ExchangeType,
    ExecutionPolicy,
    MarketType,
    StrategyType,
    TradeMode,
)
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.exchanges.binance import (
    BinanceFuturesExchangeClient,
    BinanceFuturesUserDataStream,
)
from botragram.exchanges.factory import ExchangeFactory
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    LiveRuntimePositionContext,
)
from botragram.repositories import (
    AutonomousLiveOpportunityClaimRepository,
    CandleRepository,
    ClosedPositionLifecycleRepository,
    ExecutionAuthorizationRepository,
    OrderRepository,
    PositionRepository,
    SignalRepository,
    SubmissionAttemptRepository,
    TradeRepository,
)
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository
from botragram.services import (
    AccountService,
    AutonomousLiveEntryExecutionService,
    AutonomousLiveEntryIntentService,
    AutonomousLiveRecoveryObservabilityService,
    AutonomousPaperExecutionService,
    ClosedPositionLifecycleService,
    ExecutionAuthorizationService,
    HealthService,
    HumanConfirmedPaperExecutionService,
    LiveAccountDrawdownService,
    LiveEntryRiskEvaluationService,
    LiveFuturesEntryService,
    LiveMarketStreamService,
    LiveNaturalExitRecoveryService,
    LivePortfolioRecoveryService,
    LivePositionLifecycleCoordinator,
    LivePositionProtectionService,
    LivePostEntryRecoveryService,
    LiveProtectionMonitoringService,
    LiveRuntimeHealthService,
    LiveRuntimePortfolioReconciliationService,
    LiveSubmissionRecoveryService,
    LiveTradingPerformanceService,
    MarketService,
    OpportunityDiscoveryService,
    OrderService,
    PaperTradingService,
    PositionProtectionManager,
    PositionService,
    RuntimeRecoveryService,
    RuntimeReporter,
    StrategyService,
    VolumeRankedDiscoveryUniverseService,
)
from botragram.services.live_market_stream_service import MarketTickListener
from botragram.services.trading_service import TradingService
from botragram.storage.memory import MemoryExecutionAuthorizationRepository
from botragram.storage.sqlite import (
    SQLiteAutonomousLiveOpportunityClaimRepository,
    SQLiteCandleRepository,
    SQLiteClosedPositionLifecycleRepository,
    SQLiteDatabase,
    SQLiteLiveEquityHighWaterRepository,
    SQLiteMigrationManager,
    SQLiteOrderRepository,
    SQLitePositionRepository,
    SQLiteSignalRepository,
    SQLiteSubmissionAttemptRepository,
    SQLiteTestnetLegacyLiveLedgerMigration,
    SQLiteTradeRepository,
)
from botragram.storage.sqlite.live_recovery_repository import (
    SQLiteLiveRecoveryRepository,
)
from botragram.strategies.factory import StrategyFactory
from botragram.telegram import TelegramBot
from botragram.telegram.context import BotContext
from botragram.telegram.query_service import TelegramQueryService

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
        "_autonomous_live_entry_authorization",
        "_autonomous_live_entry_execution_service",
        "_autonomous_live_entry_intent_service",
        "_autonomous_live_opportunity_claim_repository",
        "_autonomous_live_recovery_observability_service",
        "_live_account_drawdown_service",
        "_live_entry_risk_evaluation_service",
        "_autonomous_paper_execution_service",
        "_execution_authorization_repository",
        "_execution_authorization_service",
        "_human_confirmed_paper_execution_service",
        "_candle_repository",
        "_closed_position_lifecycle_repository",
        "_closed_position_lifecycle_service",
        "_database",
        "_database_path",
        "_exchange_client",
        "_health_service",
        "_live_futures_entry_service",
        "_live_futures_user_data_service",
        "_live_market_stream_service",
        "_live_natural_exit_recovery_service",
        "_live_position_lifecycle_coordinator",
        "_live_post_entry_recovery_service",
        "_live_position_protection_service",
        "_live_protection_monitoring_service",
        "_live_portfolio_recovery_service",
        "_live_runtime_health_service",
        "_live_runtime_portfolio_reconciliation_service",
        "_live_trading_performance_service",
        "_live_submission_recovery_service",
        "_initialized",
        "_market_service",
        "_market_type_switch_service",
        "_order_engine",
        "_opportunity_discovery_service",
        "_order_repository",
        "_order_service",
        "_paper_trading_service",
        "_pnl_engine",
        "_portfolio_engine",
        "_position_engine",
        "_position_repository",
        "_position_service",
        "_risk_engine",
        "_runtime_control",
        "_restart_coordinator",
        "_runtime_reporter",
        "_runtime_recovery_service",
        "_settings",
        "_signal_engine",
        "_signal_repository",
        "_submission_attempt_repository",
        "_strategy_service",
        "_stream_client",
        "_telegram_bot",
        "_telegram_query_service",
        "_trade_repository",
        "_trading_engine",
        "_trading_cycle_executor",
        "_trading_service",
    )

    def __init__(
        self,
        *,
        database_path: str | Path,
        settings: Settings | None = None,
        restart_coordinator: RuntimeRestartCoordinator | None = None,
        market_type_confirmed: bool = False,
    ) -> None:
        """Initialize the application dependency provider.

        Args:
            database_path: SQLite database file path.
            settings: Immutable application configuration. Defaults preserve
                the existing repository-only construction API.
            restart_coordinator: Optional process-level soft-restart coordinator.
            market_type_confirmed: Whether Telegram selected the loaded product.

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
        self._autonomous_live_entry_authorization = (
            self._build_autonomous_live_entry_authorization()
        )
        self._autonomous_live_entry_intent_service = (
            self._build_autonomous_live_entry_intent_service()
        )
        self._runtime_control = TradingRuntimeControl(
            exchange_type=self._settings.exchange.exchange,
            market_type=self._settings.exchange.market_type,
            symbol=self._settings.market.symbol,
            interval=self._settings.market.interval,
            strategy_type=self._settings.strategy.strategy_type,
        )
        if market_type_confirmed:
            self._runtime_control.confirm_market_type(
                self._settings.exchange.market_type
            )
        self._restart_coordinator = (
            restart_coordinator
            if restart_coordinator is not None
            else RuntimeRestartCoordinator()
        )
        self._database: SQLiteDatabase | None = None
        self._exchange_client: BaseExchangeClient | None = None
        self._stream_client: BaseStreamClient | None = None
        self._telegram_bot: TelegramBot | None = None
        self._telegram_query_service: TelegramQueryService | None = None
        self._health_service: HealthService | None = None
        self._live_futures_entry_service: LiveFuturesEntryService | None = None
        self._live_futures_user_data_service: LiveFuturesUserDataService | None = None
        self._live_market_stream_service: LiveMarketStreamService | None = None
        self._live_account_drawdown_service: LiveAccountDrawdownService | None = None
        self._live_natural_exit_recovery_service: (
            LiveNaturalExitRecoveryService | None
        ) = None
        self._live_position_lifecycle_coordinator = LivePositionLifecycleCoordinator()
        self._live_post_entry_recovery_service: LivePostEntryRecoveryService | None = (
            None
        )
        self._live_position_protection_service: LivePositionProtectionService | None = (
            None
        )
        self._live_protection_monitoring_service: (
            LiveProtectionMonitoringService | None
        ) = None
        self._live_portfolio_recovery_service: LivePortfolioRecoveryService | None = (
            None
        )
        self._live_runtime_health_service: LiveRuntimeHealthService | None = None
        self._live_runtime_portfolio_reconciliation_service: (
            LiveRuntimePortfolioReconciliationService | None
        ) = None
        self._live_trading_performance_service: LiveTradingPerformanceService | None = (
            None
        )
        self._live_submission_recovery_service: LiveSubmissionRecoveryService | None = (
            None
        )
        self._runtime_reporter: RuntimeReporter | None = None
        self._runtime_recovery_service: RuntimeRecoveryService | None = None

        self._candle_repository: CandleRepository | None = None
        self._closed_position_lifecycle_repository: (
            ClosedPositionLifecycleRepository | None
        ) = None
        self._closed_position_lifecycle_service: (
            ClosedPositionLifecycleService | None
        ) = None
        self._execution_authorization_repository: (
            ExecutionAuthorizationRepository | None
        ) = None
        self._signal_repository: SignalRepository | None = None
        self._autonomous_live_opportunity_claim_repository: (
            AutonomousLiveOpportunityClaimRepository | None
        ) = None
        self._submission_attempt_repository: SubmissionAttemptRepository | None = None
        self._order_repository: OrderRepository | None = None
        self._trade_repository: TradeRepository | None = None
        self._position_repository: PositionRepository | None = None

        self._signal_engine: SignalEngine | None = None
        self._risk_engine: RiskEngine | None = None
        self._pnl_engine: PnLEngine | None = None
        self._portfolio_engine: PortfolioEngine | None = None
        self._trading_engine: TradingEngine | None = None
        self._order_engine: OrderEngine | None = None
        self._position_engine: PositionEngine | None = None

        self._market_service: MarketService | None = None
        self._autonomous_paper_execution_service: (
            AutonomousPaperExecutionService | None
        ) = None
        self._autonomous_live_entry_execution_service: (
            AutonomousLiveEntryExecutionService | None
        ) = None
        self._autonomous_live_recovery_observability_service: (
            AutonomousLiveRecoveryObservabilityService | None
        ) = None
        self._live_entry_risk_evaluation_service: (
            LiveEntryRiskEvaluationService | None
        ) = None
        self._opportunity_discovery_service: OpportunityDiscoveryService | None = None
        self._market_type_switch_service: MarketTypeSwitchService | None = None
        self._strategy_service: StrategyService | None = None
        self._order_service: OrderService | None = None
        self._paper_trading_service: PaperTradingService | None = None
        self._position_service: PositionService | None = None
        self._account_service: AccountService | None = None
        self._trading_service: TradingService | None = None
        self._trading_cycle_executor: TradingCycleExecutor | None = None
        self._execution_authorization_service: ExecutionAuthorizationService | None = (
            None
        )
        self._human_confirmed_paper_execution_service: (
            HumanConfirmedPaperExecutionService | None
        ) = None
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

    @property
    def autonomous_live_entry_authorization(
        self,
    ) -> AutonomousLiveEntryAuthorization | None:
        """Return the TESTNET-only future autonomous LIVE entry capability."""
        return self._autonomous_live_entry_authorization

    @property
    def autonomous_live_entry_intent_service(
        self,
    ) -> AutonomousLiveEntryIntentService | None:
        """Return the pure TESTNET autonomous LIVE intent boundary, if enabled."""
        return self._autonomous_live_entry_intent_service

    @property
    def autonomous_live_entry_execution_service(
        self,
    ) -> AutonomousLiveEntryExecutionService | None:
        """Return the protected TESTNET intent execution adapter, if configured."""
        return self._autonomous_live_entry_execution_service

    @property
    def autonomous_live_recovery_observability_service(
        self,
    ) -> AutonomousLiveRecoveryObservabilityService:
        """Return read-only durable autonomous recovery observability."""
        return self._require(self._autonomous_live_recovery_observability_service)

    @property
    def live_entry_risk_evaluation_service(self) -> LiveEntryRiskEvaluationService:
        """Return fresh authoritative risk evaluation for autonomous LIVE entry."""
        return self._require(self._live_entry_risk_evaluation_service)

    @property
    def runtime_control(self) -> TradingRuntimeControl:
        """Return the process-wide cooperative trading runtime controller."""
        return self._runtime_control

    @property
    def restart_coordinator(self) -> RuntimeRestartCoordinator:
        """Return the process-level connector restart coordinator."""
        return self._restart_coordinator

    async def initialize(self) -> None:
        """Initialize repositories, exchange clients, engines, and services."""
        if self._initialized:
            _LOGGER.debug("Dependency provider is already initialized")
            return

        if self._autonomous_live_entry_authorization is None:
            self._autonomous_live_entry_authorization = (
                self._build_autonomous_live_entry_authorization()
            )
        if self._autonomous_live_entry_intent_service is None:
            self._autonomous_live_entry_intent_service = (
                self._build_autonomous_live_entry_intent_service()
            )

        database = SQLiteDatabase(database_path=self._database_path)
        _LOGGER.info(
            "Dependency initialization starting: database=%s exchange=%s "
            "market_type=%s testnet=%s",
            self._database_path,
            self._settings.exchange.exchange.value,
            self._settings.exchange.market_type.value,
            self._settings.exchange.testnet,
        )

        try:
            await database.connect()
            self._database = database
            await SQLiteMigrationManager(database=database).initialize()
            await self._migrate_legacy_testnet_live_ledger(database=database)

            self._build_repositories(database=database)
            await self._build_exchange_dependencies()
            self._build_engines()
            self.runtime_control.bind_strategy_selector(
                self._select_runtime_strategy,
            )
            self._telegram_bot = TelegramBot(settings=self._settings.telegram)
            self._build_live_account_drawdown_service()
            await self._start_live_futures_user_data_service()
            self._build_services()
            self._health_service = HealthService(
                database=database,
                exchange=self.exchange_client,
            )
            self._runtime_reporter = RuntimeReporter(
                health_service=self.health_service,
                paper_trading_service=self.paper_trading_service,
                position_repository=self.position_repository,
                notification_publisher=self.telegram_bot,
                trade_mode=self._settings.app.trade_mode,
                symbol=self._settings.market.symbol,
            )
            self._live_protection_monitoring_service = LiveProtectionMonitoringService(
                manager_factory=self._create_position_protection_manager,
            )
            tick_listeners: tuple[MarketTickListener, ...] = (
                self.live_protection_monitoring_service,
            )

            if self._settings.app.trade_mode is TradeMode.PAPER:
                tick_listeners += (self.paper_trading_service,)

            self._live_market_stream_service = LiveMarketStreamService(
                market_service=self.market_service,
                runtime_control=self.runtime_control,
                tick_listeners=tick_listeners,
            )
            self._live_runtime_portfolio_reconciliation_service = (
                LiveRuntimePortfolioReconciliationService(
                    runtime_control=self.runtime_control,
                    live_portfolio_recovery_service=(
                        self.live_portfolio_recovery_service
                    ),
                    market_stream_service=self.live_market_stream_service,
                    protection_monitoring_service=(
                        self.live_protection_monitoring_service
                    ),
                    first_tick_timeout_seconds=15.0,
                    live_natural_exit_recovery_service=(
                        self.live_natural_exit_recovery_service
                    ),
                )
            )
            self._live_runtime_health_service = LiveRuntimeHealthService(
                runtime_control=self.runtime_control,
                market_stream_service=self.live_market_stream_service,
                protection_monitoring_service=(self.live_protection_monitoring_service),
            )
            self._trading_cycle_executor = self._build_trading_cycle_executor()

            query_service = TelegramQueryService(
                symbol=self._settings.market.symbol,
                market_service=self.market_service,
                paper_trading_service=self.paper_trading_service,
                position_repository=self.position_repository,
                trade_repository=self.trade_repository,
                order_repository=self.order_repository,
                market_stream_service=self.live_market_stream_service,
                quote_asset=self._settings.market.quote_asset,
                interval=self._settings.market.interval,
                strategy_type=self._settings.strategy.strategy_type,
                runtime_control=self.runtime_control,
                live_runtime_health_service=self.live_runtime_health_service,
                autonomous_live_recovery_observability_service=(
                    self.autonomous_live_recovery_observability_service
                ),
            )
            self._telegram_query_service = query_service
            self._runtime_recovery_service = RuntimeRecoveryService(
                trade_mode=self._settings.app.trade_mode,
                market_type=self._settings.exchange.market_type,
                runtime_control=self.runtime_control,
                stream_controller=query_service,
                market_stream_service=self.live_market_stream_service,
                protection_monitoring_service=self.live_protection_monitoring_service,
                position_repository=self.position_repository,
                signal_repository=self.signal_repository,
                candle_repository=self.candle_repository,
                live_portfolio_recovery_service=(self.live_portfolio_recovery_service),
                live_runtime_portfolio_reconciliation_service=(
                    self.live_runtime_portfolio_reconciliation_service
                ),
                submission_attempt_repository=self.submission_attempt_repository,
                live_submission_recovery_service=(
                    self.live_submission_recovery_service
                ),
                live_post_entry_recovery_service=(
                    self.live_post_entry_recovery_service
                ),
                live_natural_exit_recovery_service=(
                    self.live_natural_exit_recovery_service
                ),
                autonomous_live_entry_authorization=(
                    self._autonomous_live_entry_authorization
                    if self._settings.app.effective_execution_policy
                    is ExecutionPolicy.AUTONOMOUS_LIVE
                    else None
                ),
            )
            self._market_type_switch_service = MarketTypeSwitchService(
                trade_mode=self._settings.app.trade_mode,
                runtime_control=self.runtime_control,
                position_repository=self.position_repository,
                position_service=self.position_service,
                restart_coordinator=self.restart_coordinator,
            )
            await self.telegram_bot.sync_context(
                context=BotContext(
                    is_running=True,
                    trade_mode=self._settings.app.trade_mode.value,
                    symbol=self._settings.market.symbol,
                    strategy_name=self._settings.strategy.strategy_type.value,
                    exchange_type=self._settings.exchange.exchange.value,
                    query_provider=query_service,
                    runtime_control=self.runtime_control,
                    market_type_switcher=self.market_type_switch_service,
                    execution_authorization_service=(
                        self._execution_authorization_service
                    ),
                )
            )
            try:
                await self.telegram_bot.start()
            except Exception:
                _LOGGER.exception(
                    "Telegram startup failed; trading will continue without it"
                )
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
        telegram_bot = self._telegram_bot
        live_market_stream_service = self._live_market_stream_service
        live_futures_user_data_service = self._live_futures_user_data_service
        live_protection_monitoring_service = self._live_protection_monitoring_service
        database = self._database

        self._clear_dependencies()
        _LOGGER.debug("Dependency shutdown starting")

        try:
            if telegram_bot is not None:
                await telegram_bot.stop()
        finally:
            try:
                if live_futures_user_data_service is not None:
                    await live_futures_user_data_service.close()
            finally:
                try:
                    if live_protection_monitoring_service is not None:
                        live_protection_monitoring_service.stop_all()
                finally:
                    try:
                        if live_market_stream_service is not None:
                            await live_market_stream_service.stop_all()
                    finally:
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
    def closed_position_lifecycle_repository(
        self,
    ) -> ClosedPositionLifecycleRepository:
        """Return durable one-position-per-closed-trade storage."""
        return self._require(self._closed_position_lifecycle_repository)

    @property
    def autonomous_live_opportunity_claim_repository(
        self,
    ) -> AutonomousLiveOpportunityClaimRepository:
        """Return durable TESTNET autonomous closed-candle replay denial."""
        return self._require(self._autonomous_live_opportunity_claim_repository)

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

    @property
    def submission_attempt_repository(self) -> SubmissionAttemptRepository:
        """Return durable LIVE submission-attempt storage."""
        return self._require(self._submission_attempt_repository)

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
    def telegram_bot(self) -> TelegramBot:
        """Return the configured Telegram lifecycle and notification adapter."""
        return self._require(self._telegram_bot)

    @property
    def health_service(self) -> HealthService:
        """Return the configured dependency health service."""
        return self._require(self._health_service)

    @property
    def runtime_reporter(self) -> RuntimeReporter:
        """Return the configured runtime monitoring observer."""
        return self._require(self._runtime_reporter)

    @property
    def runtime_recovery_service(self) -> RuntimeRecoveryService:
        """Return the active-position startup recovery service."""
        return self._require(self._runtime_recovery_service)

    @property
    def live_runtime_health_service(self) -> LiveRuntimeHealthService:
        """Return read-only recovered LIVE runtime health aggregation."""
        return self._require(self._live_runtime_health_service)

    @property
    def live_trading_performance_service(self) -> LiveTradingPerformanceService:
        """Return cached read-only LIVE realized performance aggregation."""
        return self._require(self._live_trading_performance_service)

    @property
    def live_position_protection_service(self) -> LivePositionProtectionService:
        """Return the shared LIVE Futures protection reconciler."""
        return self._require(self._live_position_protection_service)

    @property
    def live_natural_exit_recovery_service(self) -> LiveNaturalExitRecoveryService:
        """Return the LIVE natural-exit and orphan-protection reconciler."""
        return self._require(self._live_natural_exit_recovery_service)

    @property
    def live_portfolio_recovery_service(self) -> LivePortfolioRecoveryService:
        """Return the LIVE portfolio safety recovery service."""
        return self._require(self._live_portfolio_recovery_service)

    @property
    def live_runtime_portfolio_reconciliation_service(
        self,
    ) -> LiveRuntimePortfolioReconciliationService:
        """Return the canonical LIVE portfolio management reconciler."""
        return self._require(self._live_runtime_portfolio_reconciliation_service)

    @property
    def live_submission_recovery_service(self) -> LiveSubmissionRecoveryService:
        """Return the GET-only durable LIVE submission recovery service."""
        return self._require(self._live_submission_recovery_service)

    @property
    def live_post_entry_recovery_service(self) -> LivePostEntryRecoveryService:
        """Return the durable acknowledged-entry recovery service."""
        return self._require(self._live_post_entry_recovery_service)

    @property
    def live_futures_user_data_service(self) -> LiveFuturesUserDataService:
        """Return the live Futures private-stream cache service."""
        return self._require(self._live_futures_user_data_service)

    @property
    def live_futures_entry_service(self) -> LiveFuturesEntryService:
        """Return the protected LIVE Futures entry workflow."""
        return self._require(self._live_futures_entry_service)

    @property
    def live_market_stream_service(self) -> LiveMarketStreamService:
        """Return the sole production owner of live market stream tasks."""
        return self._require(self._live_market_stream_service)

    @property
    def live_protection_monitoring_service(self) -> LiveProtectionMonitoringService:
        """Return the sole production owner of live protection monitor contexts."""
        return self._require(self._live_protection_monitoring_service)

    @property
    def signal_engine(self) -> SignalEngine:
        """Return the configured signal engine."""
        return self._require(self._signal_engine)

    @property
    def risk_engine(self) -> RiskEngine:
        """Return the configured risk engine."""
        return self._require(self._risk_engine)

    @property
    def pnl_engine(self) -> PnLEngine:
        """Return the configured profit-and-loss engine."""
        return self._require(self._pnl_engine)

    @property
    def portfolio_engine(self) -> PortfolioEngine:
        """Return the configured portfolio calculation engine."""
        return self._require(self._portfolio_engine)

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
    def opportunity_discovery_service(self) -> OpportunityDiscoveryService:
        """Return the bounded market opportunity discovery service."""
        return self._require(self._opportunity_discovery_service)

    @property
    def autonomous_paper_execution_service(self) -> AutonomousPaperExecutionService:
        """Return the configured autonomous PAPER execution service."""
        return self._require(self._autonomous_paper_execution_service)

    @property
    def execution_authorization_service(self) -> ExecutionAuthorizationService:
        """Return the PAPER human execution authorization boundary."""
        return self._require(self._execution_authorization_service)

    @property
    def human_confirmed_paper_execution_service(
        self,
    ) -> HumanConfirmedPaperExecutionService:
        """Return the bounded human-confirmation discovery orchestration."""
        return self._require(self._human_confirmed_paper_execution_service)

    @property
    def market_type_switch_service(self) -> MarketTypeSwitchService:
        """Return the guarded Telegram product-switch service."""
        return self._require(self._market_type_switch_service)

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
    def paper_trading_service(self) -> PaperTradingService:
        """Return the configured paper-trading simulation service."""
        return self._require(self._paper_trading_service)

    @property
    def account_service(self) -> AccountService:
        """Return the configured account service."""
        return self._require(self._account_service)

    @property
    def trading_service(self) -> TradingService:
        """Return the configured trading service."""
        return self._require(self._trading_service)

    @property
    def trading_cycle_executor(self) -> TradingCycleExecutor:
        """Return the runtime-selected trading cycle executor."""
        return self._require(self._trading_cycle_executor)

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
        self._closed_position_lifecycle_repository = (
            SQLiteClosedPositionLifecycleRepository(database=database)
        )
        self._signal_repository = SQLiteSignalRepository(database=database)
        self._autonomous_live_opportunity_claim_repository = (
            SQLiteAutonomousLiveOpportunityClaimRepository(database=database)
        )
        self._submission_attempt_repository = SQLiteSubmissionAttemptRepository(
            database=database
        )
        self._order_repository = SQLiteOrderRepository(database=database)
        self._trade_repository = SQLiteTradeRepository(database=database)
        self._position_repository = SQLitePositionRepository(database=database)

    async def _migrate_legacy_testnet_live_ledger(
        self,
        *,
        database: SQLiteDatabase,
    ) -> None:
        """Import only the compatible legacy Binance Futures TESTNET ledger."""
        exchange = self._settings.exchange
        if (
            self._settings.app.trade_mode is not TradeMode.LIVE
            or exchange.exchange is not ExchangeType.BINANCE
            or exchange.market_type is not MarketType.FUTURES
            or exchange.environment is not ExchangeEnvironment.TESTNET
        ):
            return

        scope_suffix = "-".join(
            (
                exchange.exchange.value,
                exchange.market_type.value,
                exchange.environment.value,
            )
        )
        scoped_suffix = f"-{scope_suffix}"
        scoped_stem = self._database_path.stem
        if not scoped_stem.endswith(scoped_suffix):
            return

        legacy_stem = scoped_stem.removesuffix(scoped_suffix)
        if not legacy_stem:
            return

        legacy_path = self._database_path.with_stem(legacy_stem)
        migration = SQLiteTestnetLegacyLiveLedgerMigration(
            target_database=database,
            source_database_path=legacy_path,
        )
        if await migration.migrate_if_required():
            _LOGGER.warning(
                "Imported legacy Botragram LIVE ledger into isolated TESTNET "
                "database: source=%s target=%s",
                legacy_path,
                self._database_path,
            )

    async def _build_exchange_dependencies(self) -> None:
        """Construct and connect the configured exchange dependencies."""
        exchange = self._settings.exchange

        if exchange.exchange is not ExchangeType.BINANCE:
            raise ValueError(
                "DependencyProvider currently supports the Binance exchange"
            )

        rest_base_url, websocket_base_url = self._get_binance_urls(
            testnet=exchange.testnet,
            market_type=exchange.market_type,
        )
        exchange_client, stream_client = ExchangeFactory.create(
            exchange_type=exchange.exchange,
            rest_base_url=rest_base_url,
            websocket_base_url=websocket_base_url,
            api_key=exchange.api_key,
            api_secret=exchange.api_secret,
            market_type=exchange.market_type,
        )
        self._exchange_client = exchange_client
        self._stream_client = stream_client

        _LOGGER.info(
            "Exchange connection starting: exchange=%s market_type=%s",
            exchange.exchange.value,
            exchange.market_type.value,
        )
        await exchange_client.connect()
        if (
            self._settings.app.trade_mode is TradeMode.LIVE
            and exchange.market_type is MarketType.FUTURES
            and exchange.environment is ExchangeEnvironment.MAINNET
        ):
            if not isinstance(exchange_client, BinanceFuturesExchangeClient):
                raise TypeError("MAINNET Futures readiness requires Binance Futures")
            await exchange_client.verify_mainnet_readiness()
        await stream_client.connect()
        _LOGGER.info("Exchange REST and WebSocket transports are ready")

    async def _start_live_futures_user_data_service(self) -> None:
        """Start private cache for credentialed LIVE Binance Futures networks."""
        if (
            self._settings.app.trade_mode is not TradeMode.LIVE
            or self._settings.exchange.market_type is not MarketType.FUTURES
        ):
            return

        exchange_client = self.exchange_client
        if not isinstance(exchange_client, BinanceFuturesExchangeClient):
            raise TypeError("LIVE Futures User Data Stream requires Binance Futures")

        _, websocket_base_url = self._get_binance_urls(
            testnet=self._settings.exchange.testnet,
            market_type=MarketType.FUTURES,
        )
        service = LiveFuturesUserDataService(
            snapshot_provider=exchange_client,
            event_stream=BinanceFuturesUserDataStream(
                rest=exchange_client.rest_transport,
                websocket_base_url=websocket_base_url,
            ),
            equity_asset=self._settings.market.quote_asset,
            equity_observer=self._live_account_drawdown_service,
        )
        await service.start()
        self._live_futures_user_data_service = service

    def _build_live_account_drawdown_service(self) -> None:
        """Construct durable drawdown state only for LIVE Futures execution."""
        if (
            self._settings.app.trade_mode is not TradeMode.LIVE
            or self._settings.exchange.market_type is not MarketType.FUTURES
        ):
            return
        database = self._require(self._database)
        self._live_account_drawdown_service = LiveAccountDrawdownService(
            repository=SQLiteLiveEquityHighWaterRepository(database=database),
            asset=self._settings.market.quote_asset,
        )

    def _build_engines(self) -> None:
        """Construct engines from configured strategies and exchange clients."""
        exchange_client = self.exchange_client
        self._signal_engine = SignalEngine(
            strategy_resolver=StrategyFactory.create_resolver(
                settings=self._settings.strategy,
            ),
            default_strategy_type=self._settings.strategy.strategy_type,
        )
        self._risk_engine = RiskEngine(settings=self._settings.risk)
        self._pnl_engine = PnLEngine()
        self._portfolio_engine = PortfolioEngine()
        self._trading_engine = TradingEngine(
            risk_engine=self.risk_engine,
            portfolio_engine=self.portfolio_engine,
        )
        self._order_engine = OrderEngine(exchange_client=exchange_client)
        self._position_engine = PositionEngine(exchange_client=exchange_client)

    def _select_runtime_strategy(self, strategy_type: StrategyType) -> None:
        """Validate a singular runtime strategy without mutating global state."""
        self.signal_engine.get_minimum_candles(strategy_type=strategy_type)
        _LOGGER.info(
            "Runtime strategy selected: strategy=%s",
            strategy_type.value,
        )

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
        self._opportunity_discovery_service = OpportunityDiscoveryService(
            market_service=self.market_service,
            strategy_service=self.strategy_service,
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
        self._closed_position_lifecycle_service = (
            ClosedPositionLifecycleService(
                repository=self.closed_position_lifecycle_repository,
                trade_history=exchange_client,
                pnl_asset=self._settings.market.quote_asset,
            )
            if isinstance(exchange_client, BinanceFuturesExchangeClient)
            else None
        )
        self._live_natural_exit_recovery_service = LiveNaturalExitRecoveryService(
            exchange_client=exchange_client,
            position_repository=self.position_repository,
            submission_attempt_repository=self.submission_attempt_repository,
            closed_lifecycle_service=self._closed_position_lifecycle_service,
            lifecycle_coordinator=self._live_position_lifecycle_coordinator,
        )
        live_user_data_service = self._live_futures_user_data_service
        self._live_entry_risk_evaluation_service = LiveEntryRiskEvaluationService(
            account_service=(
                live_user_data_service
                if live_user_data_service is not None
                else self.account_service
            ),
            position_service=self.position_service,
            trading_engine=self.trading_engine,
            balance_asset=self._settings.market.quote_asset,
            equity_provider=live_user_data_service,
            drawdown_service=self._live_account_drawdown_service,
            natural_exit_recovery_service=self.live_natural_exit_recovery_service,
        )
        self._live_position_protection_service = LivePositionProtectionService(
            exchange_client=exchange_client,
            position_repository=self.position_repository,
            risk_engine=self.risk_engine,
        )
        self._live_portfolio_recovery_service = LivePortfolioRecoveryService(
            position_service=self.position_service,
            protection_service=self.live_position_protection_service,
            runtime_control=self.runtime_control,
            signal_repository=self.signal_repository,
            candle_repository=self.candle_repository,
        )

        self._live_submission_recovery_service = LiveSubmissionRecoveryService(
            submission_attempt_repository=self.submission_attempt_repository,
            order_service=self.order_service,
        )
        self._autonomous_live_recovery_observability_service = (
            AutonomousLiveRecoveryObservabilityService(
                submission_attempt_repository=self.submission_attempt_repository,
                authorization=self._autonomous_live_entry_authorization,
            )
        )
        # Wire a storage-appropriate LiveRecoveryRepository for atomic
        # resolve_no_exposure semantics. Prefer a SQLite adapter when the
        # configured submission_attempt_repository is SQLite-backed.
        if isinstance(
            self.submission_attempt_repository, SQLiteSubmissionAttemptRepository
        ):
            live_recovery_repo: LiveRecoveryRepository = SQLiteLiveRecoveryRepository(
                subrepo=self.submission_attempt_repository
            )
        else:
            # Import the in-memory adapter lazily to avoid importing test-only
            # memory classes in production contexts.
            from botragram.storage.memory.live_recovery_repository import (
                MemoryLiveRecoveryRepository,
            )

            live_recovery_repo = MemoryLiveRecoveryRepository(
                attempt_repo=self.submission_attempt_repository,  # type: ignore[arg-type]
                position_repo=self.position_repository,  # type: ignore[arg-type]
            )

        self._live_post_entry_recovery_service = LivePostEntryRecoveryService(
            submission_attempt_repository=self.submission_attempt_repository,
            live_recovery_repository=live_recovery_repo,
            position_service=self.position_service,
            protection_service=self.live_position_protection_service,
            runtime_control=self.runtime_control,
            order_service=self.order_service,
            protection_reconciler=self.live_position_protection_service,
            protection_cleanup_service=self.live_position_protection_service,
            emergency_exit_exchange=exchange_client,
            closed_lifecycle_service=self._closed_position_lifecycle_service,
        )
        self._live_futures_entry_service = LiveFuturesEntryService(
            market_type=self._settings.exchange.market_type,
            order_service=self.order_service,
            position_service=self.position_service,
            protection_service=self.live_position_protection_service,
            runtime_control=self.runtime_control,
            submission_attempt_repository=self.submission_attempt_repository,
            portfolio_engine=self.trading_engine.portfolio_engine,
            max_open_positions=self._settings.risk.max_open_positions,
            venue_entry_readiness=(
                exchange_client
                if isinstance(exchange_client, BinanceFuturesExchangeClient)
                and self._settings.app.trade_mode is TradeMode.LIVE
                and self._settings.exchange.market_type is MarketType.FUTURES
                and self._settings.exchange.environment is ExchangeEnvironment.MAINNET
                else None
            ),
            maximum_leverage=self._settings.risk.leverage,
        )
        self._live_trading_performance_service = LiveTradingPerformanceService(
            lifecycle_repository=self.closed_position_lifecycle_repository,
        )
        self._paper_trading_service = PaperTradingService(
            order_repository=self.order_repository,
            trade_repository=self.trade_repository,
            position_repository=self.position_repository,
            trading_engine=self.trading_engine,
            pnl_engine=self.pnl_engine,
            notification_publisher=self.telegram_bot,
            quote_asset=self._settings.market.quote_asset,
        )
        self._trading_service = TradingService(
            market_service=self.market_service,
            strategy_service=self.strategy_service,
            account_service=self.account_service,
            position_service=self.position_service,
            order_service=self.order_service,
            trading_engine=self.trading_engine,
            paper_trading_service=self.paper_trading_service,
            live_futures_entry_service=self.live_futures_entry_service,
            live_entry_risk_evaluation_service=(
                self.live_entry_risk_evaluation_service
            ),
            live_executable_quote_provider=self.market_service,
            balance_asset=self._settings.market.quote_asset,
            trade_mode=self._settings.app.trade_mode,
            max_executable_quote_age_ms=(
                self._settings.risk.max_executable_quote_age_ms
            ),
            max_spread_bps=self._settings.risk.max_spread_bps,
        )
        self._autonomous_paper_execution_service = AutonomousPaperExecutionService(
            discovery_service=self.opportunity_discovery_service,
            paper_trading_service=self.paper_trading_service,
        )
        self._autonomous_live_entry_execution_service = (
            self._build_autonomous_live_entry_execution_service()
        )
        if self._settings.app.trade_mode is TradeMode.PAPER:
            self._execution_authorization_repository = (
                MemoryExecutionAuthorizationRepository()
            )
            self._execution_authorization_service = ExecutionAuthorizationService(
                authorization_repository=self._execution_authorization_repository,
                paper_trading_service=self.paper_trading_service,
                trade_mode=self._settings.app.trade_mode,
                authorization_publisher=self.telegram_bot,
            )
            self._human_confirmed_paper_execution_service = (
                HumanConfirmedPaperExecutionService(
                    discovery_service=self.opportunity_discovery_service,
                    authorization_service=self.execution_authorization_service,
                )
            )

    def _build_trading_cycle_executor(self) -> TradingCycleExecutor:
        """Select a validated runtime executor without embedding trading rules."""
        policy = self._settings.app.effective_execution_policy

        if policy is ExecutionPolicy.SINGLE_SYMBOL:
            return SingleSymbolTradingCycleExecutor(
                trading_service=self.trading_service,
            )

        if policy is ExecutionPolicy.AUTONOMOUS_LIVE:
            if self._settings.exchange.market_type is not MarketType.FUTURES:
                raise ValueError("Autonomous LIVE execution requires FUTURES")
            exchange_client = self.exchange_client
            if not isinstance(exchange_client, BinanceFuturesExchangeClient):
                raise TypeError("Autonomous LIVE requires Binance Futures")
            authorization = self._autonomous_live_entry_authorization
            intent_service = self._autonomous_live_entry_intent_service
            execution_service = self._autonomous_live_entry_execution_service
            if (
                authorization is None
                or intent_service is None
                or execution_service is None
            ):
                raise ValueError(
                    "Autonomous LIVE execution requires complete TESTNET composition"
                )
            market = self._settings.market
            return AutonomousLiveTradingCycleExecutor(
                discovery_service=self.opportunity_discovery_service,
                discovery_universe_service=VolumeRankedDiscoveryUniverseService(
                    market_service=self.market_service,
                    quote_asset=market.quote_asset,
                    universe_limit=market.discovery_universe_limit,
                    batch_size=market.discovery_batch_size,
                ),
                risk_evaluation_service=self.live_entry_risk_evaluation_service,
                intent_service=intent_service,
                execution_service=execution_service,
                opportunity_claim_repository=(
                    self.autonomous_live_opportunity_claim_repository
                ),
                authorization=authorization,
                quote_asset=market.quote_asset,
                max_symbols=market.discovery_max_symbols,
                top_n=market.discovery_top_n,
                max_open_positions=self._settings.risk.max_open_positions,
                strategy_type=self._settings.strategy.strategy_type,
                live_runtime_portfolio_reconciler=(
                    self.live_runtime_portfolio_reconciliation_service
                ),
                discovery_rate_limit_governor=(
                    exchange_client.rest_transport.rate_limit_governor
                ),
            )

        if self._settings.app.trade_mode is not TradeMode.PAPER:
            raise ValueError("Market-wide execution is supported only in paper mode")

        market = self._settings.market

        if policy is ExecutionPolicy.AUTONOMOUS_PAPER:
            return AutonomousPaperTradingCycleExecutor(
                autonomous_execution_service=self.autonomous_paper_execution_service,
                quote_asset=market.quote_asset,
                max_symbols=market.discovery_max_symbols,
                top_n=market.discovery_top_n,
            )

        if policy is ExecutionPolicy.HUMAN_CONFIRMED_PAPER:
            return HumanConfirmedPaperTradingCycleExecutor(
                human_confirmation_service=self.human_confirmed_paper_execution_service,
                quote_asset=market.quote_asset,
                max_symbols=market.discovery_max_symbols,
                top_n=market.discovery_top_n,
            )

        raise ValueError(f"Unsupported execution policy: {policy.value!r}")

    def _build_autonomous_live_entry_authorization(
        self,
    ) -> AutonomousLiveEntryAuthorization | None:
        """Build only the explicit TESTNET future-entry capability.

        The capability is deliberately not injected into any execution path in
        Phase 5C.1.
        """
        app_settings = self._settings.app

        if not app_settings.autonomous_live_entry_enabled:
            return None

        if app_settings.trade_mode is not TradeMode.LIVE:
            raise ValueError("Autonomous LIVE entry authorization requires LIVE mode")

        return AutonomousLiveEntryAuthorization(
            environment=self._settings.exchange.environment,
            explicit_opt_in=app_settings.autonomous_live_entry_enabled,
        )

    def _build_autonomous_live_entry_intent_service(
        self,
    ) -> AutonomousLiveEntryIntentService | None:
        """Build only the pure TESTNET autonomous intent boundary.

        Phase 5C.2A intentionally does not attach this service to a runner or
        protected LIVE entry service. The future mutation boundary remains
        absent even when this workflow is composition-valid.
        """
        if (
            self._settings.app.effective_execution_policy
            is not ExecutionPolicy.AUTONOMOUS_LIVE
        ):
            return None

        authorization = self._autonomous_live_entry_authorization
        if authorization is None:
            raise ValueError("Autonomous LIVE execution requires explicit opt-in")

        if self._settings.app.trade_mode is not TradeMode.LIVE:
            raise ValueError("Autonomous LIVE execution requires LIVE mode")

        return AutonomousLiveEntryIntentService(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            environment=authorization.environment,
        )

    def _build_autonomous_live_entry_execution_service(
        self,
    ) -> AutonomousLiveEntryExecutionService | None:
        """Build the isolated TESTNET protected-entry adapter without runtime wiring."""
        if (
            self._settings.app.effective_execution_policy
            is not ExecutionPolicy.AUTONOMOUS_LIVE
        ):
            return None

        authorization = self._autonomous_live_entry_authorization
        if authorization is None:
            raise ValueError("Autonomous LIVE execution requires explicit opt-in")

        return AutonomousLiveEntryExecutionService(
            risk_evaluation_service=self.live_entry_risk_evaluation_service,
            market_service=self.market_service,
            live_futures_entry_service=self.live_futures_entry_service,
            environment=authorization.environment,
            max_executable_quote_age_ms=(
                self._settings.risk.max_executable_quote_age_ms
            ),
            max_spread_bps=self._settings.risk.max_spread_bps,
        )

    def _create_position_protection_manager(
        self,
        context: LiveRuntimePositionContext,
    ) -> PositionProtectionManager:
        """Construct one independent protection manager for a runtime context."""
        del context
        return PositionProtectionManager(
            trade_mode=self._settings.app.trade_mode,
            position_repository=self.position_repository,
            exchange_client=self.exchange_client,
            lifecycle_coordinator=self._live_position_lifecycle_coordinator,
        )

    @staticmethod
    def _get_binance_urls(
        *,
        testnet: bool,
        market_type: MarketType,
    ) -> tuple[str, str]:
        """Return REST and WebSocket URLs for the selected Binance network."""
        if market_type is MarketType.FUTURES:
            if testnet:
                return (
                    BINANCE_FUTURES_TESTNET_REST_BASE_URL,
                    BINANCE_FUTURES_TESTNET_WEBSOCKET_BASE_URL,
                )

            return (
                BINANCE_FUTURES_REST_BASE_URL,
                BINANCE_FUTURES_WEBSOCKET_BASE_URL,
            )

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
        self.runtime_control.pause()
        self.runtime_control.set_position_protection_ready(False)
        self.runtime_control.clear_runtime_contexts()
        self._candle_repository = None
        self._closed_position_lifecycle_repository = None
        self._closed_position_lifecycle_service = None
        self._execution_authorization_repository = None
        self._execution_authorization_service = None
        self._human_confirmed_paper_execution_service = None
        self._signal_repository = None
        self._autonomous_live_opportunity_claim_repository = None
        self._submission_attempt_repository = None
        self._order_repository = None
        self._trade_repository = None
        self._position_repository = None
        self._exchange_client = None
        self._stream_client = None
        self._telegram_bot = None
        self._telegram_query_service = None
        self._health_service = None
        self._live_futures_entry_service = None
        self._live_futures_user_data_service = None
        self._live_market_stream_service = None
        self._live_account_drawdown_service = None
        self._live_natural_exit_recovery_service = None
        self._live_position_lifecycle_coordinator = LivePositionLifecycleCoordinator()
        self._live_post_entry_recovery_service = None
        self._live_position_protection_service = None
        self._live_protection_monitoring_service = None
        self._live_portfolio_recovery_service = None
        self._live_runtime_health_service = None
        self._live_runtime_portfolio_reconciliation_service = None
        self._live_trading_performance_service = None
        self._live_submission_recovery_service = None
        self._runtime_reporter = None
        self._runtime_recovery_service = None
        self._signal_engine = None
        self._risk_engine = None
        self._pnl_engine = None
        self._portfolio_engine = None
        self._trading_engine = None
        self._order_engine = None
        self._position_engine = None
        self._market_service = None
        self._autonomous_paper_execution_service = None
        self._opportunity_discovery_service = None
        self._market_type_switch_service = None
        self._strategy_service = None
        self._order_service = None
        self._position_service = None
        self._account_service = None
        self._autonomous_live_entry_authorization = None
        self._autonomous_live_entry_execution_service = None
        self._autonomous_live_entry_intent_service = None
        self._autonomous_live_recovery_observability_service = None
        self._live_entry_risk_evaluation_service = None
        self._paper_trading_service = None
        self._trading_service = None
        self._trading_cycle_executor = None
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
