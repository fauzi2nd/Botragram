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
from pathlib import Path

# =============================================================================
# Local Imports
# =============================================================================
from botragram.repositories import (
    CandleRepository,
    OrderRepository,
    PositionRepository,
    SignalRepository,
    TradeRepository,
)
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
    SQLiteOrderRepository,
    SQLitePositionRepository,
    SQLiteSignalRepository,
    SQLiteTradeRepository,
)

__all__ = [
    "DependencyProvider",
]


# =============================================================================
# Constants
# =============================================================================
_DATABASE_PATH_ERROR = "Database path must not be empty"
_PROVIDER_NOT_INITIALIZED_ERROR = "Dependency provider has not been initialized"


# =============================================================================
# Dependency Provider
# =============================================================================
class DependencyProvider:
    """Construct and own application-level dependencies."""

    __slots__ = (
        "_candle_repository",
        "_database",
        "_database_path",
        "_initialized",
        "_order_repository",
        "_position_repository",
        "_signal_repository",
        "_trade_repository",
    )

    def __init__(
        self,
        *,
        database_path: str | Path,
    ) -> None:
        """Initialize the application dependency provider.

        Args:
            database_path: SQLite database file path.

        Raises:
            ValueError: If the database path is empty.
        """
        normalized_database_path = str(database_path).strip()

        if not normalized_database_path:
            raise ValueError(_DATABASE_PATH_ERROR)

        self._database_path = Path(normalized_database_path)
        self._database: SQLiteDatabase | None = None

        self._candle_repository: CandleRepository | None = None
        self._signal_repository: SignalRepository | None = None
        self._order_repository: OrderRepository | None = None
        self._trade_repository: TradeRepository | None = None
        self._position_repository: PositionRepository | None = None

        self._initialized = False

    # =========================================================================
    # Lifecycle
    # =========================================================================

    @property
    def is_initialized(self) -> bool:
        """Return whether dependencies have been initialized."""
        return self._initialized

    async def initialize(self) -> None:
        """Initialize database and repository dependencies."""
        if self._initialized:
            return

        database = SQLiteDatabase(
            database_path=self._database_path,
        )

        try:
            await database.connect()

            migration_manager = SQLiteMigrationManager(
                database=database,
            )
            await migration_manager.initialize()

            self._database = database

            self._candle_repository = SQLiteCandleRepository(
                database=database,
            )
            self._signal_repository = SQLiteSignalRepository(
                database=database,
            )
            self._order_repository = SQLiteOrderRepository(
                database=database,
            )
            self._trade_repository = SQLiteTradeRepository(
                database=database,
            )
            self._position_repository = SQLitePositionRepository(
                database=database,
            )

            self._initialized = True
        except BaseException:
            await database.close()
            self._clear_dependencies()
            raise

    async def close(self) -> None:
        """Close owned resources and clear dependencies."""
        database = self._database

        self._clear_dependencies()

        if database is not None:
            await database.close()

    # =========================================================================
    # Repository Dependencies
    # =========================================================================

    @property
    def candle_repository(self) -> CandleRepository:
        """Return the configured candle repository."""
        repository = self._candle_repository

        if repository is None:
            raise RuntimeError(_PROVIDER_NOT_INITIALIZED_ERROR)

        return repository

    @property
    def signal_repository(self) -> SignalRepository:
        """Return the configured signal repository."""
        repository = self._signal_repository

        if repository is None:
            raise RuntimeError(_PROVIDER_NOT_INITIALIZED_ERROR)

        return repository

    @property
    def order_repository(self) -> OrderRepository:
        """Return the configured order repository."""
        repository = self._order_repository

        if repository is None:
            raise RuntimeError(_PROVIDER_NOT_INITIALIZED_ERROR)

        return repository

    @property
    def trade_repository(self) -> TradeRepository:
        """Return the configured trade repository."""
        repository = self._trade_repository

        if repository is None:
            raise RuntimeError(_PROVIDER_NOT_INITIALIZED_ERROR)

        return repository

    @property
    def position_repository(self) -> PositionRepository:
        """Return the configured position repository."""
        repository = self._position_repository

        if repository is None:
            raise RuntimeError(_PROVIDER_NOT_INITIALIZED_ERROR)

        return repository

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _clear_dependencies(self) -> None:
        """Clear initialized dependencies."""
        self._candle_repository = None
        self._signal_repository = None
        self._order_repository = None
        self._trade_repository = None
        self._position_repository = None

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
