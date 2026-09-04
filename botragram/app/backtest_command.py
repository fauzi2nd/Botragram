"""
Botragram

Description:
    Backtest command parsing, composition, and terminal reporting.

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
import argparse
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config import Settings
from botragram.config.risk_settings import RiskSettings
from botragram.constants import (
    BINANCE_FUTURES_REST_BASE_URL,
    BINANCE_REST_BASE_URL,
    BYBIT_REST_BASE_URL,
    BYBIT_TESTNET_REST_BASE_URL,
)
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import ExchangeType, Interval, MarketType, StrategyType
from botragram.exchanges import ExchangeFactory
from botragram.models import BacktestRequest, BacktestResult
from botragram.services.backtest_service import BacktestService
from botragram.services.stored_resampled_candle_provider import (
    StoredResampledCandleProvider,
)
from botragram.storage.sqlite import SQLiteCandleRepository, SQLiteDatabase
from botragram.strategies import StrategyFactory

__all__ = [
    "format_backtest_report",
    "is_backtest_command",
    "parse_backtest_request",
    "run_backtest_command",
]


# =============================================================================
# Constants
# =============================================================================
_BACKTEST_COMMAND: Final[str] = "backtest"
_DISPLAY_TRADE_LIMIT: Final[int] = 50


# =============================================================================
# Command Functions
# =============================================================================
def is_backtest_command(arguments: Sequence[str]) -> bool:
    """Return whether command-line arguments request a backtest."""
    return bool(arguments) and arguments[0].strip().lower() == _BACKTEST_COMMAND


def parse_backtest_request(
    *,
    arguments: Sequence[str],
) -> BacktestRequest:
    """Parse validated CLI arguments into an immutable request."""
    parser = argparse.ArgumentParser(
        prog="python main.py backtest",
        description="Replay a Botragram strategy on historical candles.",
    )
    parser.add_argument("--market-type", required=True, choices=("spot", "futures"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--interval",
        required=True,
        choices=tuple(interval.value for interval in Interval),
    )
    parser.add_argument(
        "--strategy",
        required=True,
        choices=tuple(
            strategy.value
            for strategy in StrategyType
            if strategy is not StrategyType.CUSTOM
        ),
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--balance", default="10000")
    parser.add_argument("--fee-rate", default="0.001")
    parser.add_argument("--slippage-rate", default="0.0005")
    parser.add_argument("--max-candles", default="100000")
    parser.add_argument(
        "--data-source",
        choices=("auto", "local", "exchange"),
        default="auto",
        help=(
            "Candle source: 'auto' (prefer local SQLite if available), "
            "'local', or 'exchange'"
        ),
    )
    parser.add_argument(
        "--database-path",
        default=None,
        help="Optional path to SQLite database containing historical candles",
    )

    namespace = parser.parse_args(tuple(arguments[1:]))

    raw_db_path = namespace.database_path
    database_path = (
        raw_db_path.strip()
        if isinstance(raw_db_path, str) and raw_db_path.strip()
        else None
    )

    return BacktestRequest(
        symbol=_required_string(namespace=namespace, name="symbol"),
        interval=Interval(_required_string(namespace=namespace, name="interval")),
        strategy_type=StrategyType(
            _required_string(namespace=namespace, name="strategy")
        ),
        market_type=MarketType(
            _required_string(namespace=namespace, name="market_type")
        ),
        start_time=_parse_datetime(
            _required_string(namespace=namespace, name="start"),
            end_of_day=False,
        ),
        end_time=_parse_datetime(
            _required_string(namespace=namespace, name="end"),
            end_of_day=True,
        ),
        initial_balance=_parse_decimal(namespace=namespace, name="balance"),
        fee_rate=_parse_decimal(namespace=namespace, name="fee_rate"),
        slippage_rate=_parse_decimal(namespace=namespace, name="slippage_rate"),
        max_candles=_parse_integer(namespace=namespace, name="max_candles"),
        data_source=_required_string(namespace=namespace, name="data_source"),
        database_path=database_path,
    )


async def run_backtest_command(
    *,
    settings: Settings,
    request: BacktestRequest,
) -> BacktestResult:
    """Compose dependencies and execute one isolated backtest."""
    strategy_settings = replace(
        settings.strategy,
        strategy_type=request.strategy_type,
    )
    engine = BacktestEngine(
        strategy=StrategyFactory.create(settings=strategy_settings),
        risk_settings=_build_backtest_risk_settings(
            settings=settings,
            request=request,
        ),
    )

    db_path = (
        Path(request.database_path)
        if request.database_path is not None
        else settings.app.database_path
    )

    # 1. Try local data if auto or local is requested
    if request.data_source in ("auto", "local") and db_path.exists():
        database = SQLiteDatabase(database_path=db_path)
        await database.connect()
        try:
            repo = SQLiteCandleRepository(database=database)
            count = await repo.count(symbol=request.symbol)
            if count > 0:
                provider = StoredResampledCandleProvider(
                    candle_repository=repo,
                    source_interval=Interval.M1,
                )
                service = BacktestService(
                    exchange_client=provider,
                    engine=engine,
                )
                result = await service.run(request=request)
                venue_title = settings.exchange.exchange.value.title()
                net_type = "Testnet" if settings.exchange.testnet else "Mainnet"
                source_desc = (
                    f"Local SQLite Resampled (1m -> {request.interval.value}) "
                    f"[{db_path.name}]"
                    if request.interval is not Interval.M1
                    else f"Local SQLite 1m [{db_path.name}]"
                )
                return replace(
                    result,
                    venue_name=f"{venue_title} {net_type}",
                    data_source_description=source_desc,
                )
        finally:
            await database.close()

    if request.data_source == "local":
        raise RuntimeError(
            f"No local candle records found for {request.symbol} in {db_path}. "
            "Backfill data first using tests/manual/backfill_1m_candles.py."
        )

    # 2. Query exchange REST
    exchange_type = settings.exchange.exchange
    if exchange_type is ExchangeType.BYBIT:
        rest_base_url = (
            BYBIT_TESTNET_REST_BASE_URL
            if settings.exchange.testnet
            else BYBIT_REST_BASE_URL
        )
    else:
        rest_base_url = (
            BINANCE_FUTURES_REST_BASE_URL
            if request.market_type is MarketType.FUTURES
            else BINANCE_REST_BASE_URL
        )

    rest_client = ExchangeFactory.create_rest_client(
        exchange_type=exchange_type,
        base_url=rest_base_url,
    )
    exchange_client = ExchangeFactory.create_exchange_client(
        exchange_type=exchange_type,
        rest_client=rest_client,
        market_type=request.market_type,
    )
    service = BacktestService(
        exchange_client=exchange_client,
        engine=engine,
    )

    await exchange_client.connect()
    try:
        result = await service.run(request=request)
        venue_title = exchange_type.value.title()
        net_type = "Testnet" if settings.exchange.testnet else "Mainnet"
        return replace(
            result,
            venue_name=f"{venue_title} {net_type}",
            data_source_description=f"{venue_title} REST API",
        )
    finally:
        await exchange_client.close()


def format_backtest_report(*, result: BacktestResult) -> str:
    """Render a compact terminal report with bounded trade details."""
    request = result.request
    metrics = result.metrics
    profit_factor = (
        "N/A" if metrics.profit_factor is None else f"{metrics.profit_factor:.2f}"
    )
    lines = [
        "",
        "BOTRAGRAM BACKTEST",
        "=" * 72,
        f"Market       : {result.venue_name} {request.market_type.value.upper()}",
        f"Data Source  : {result.data_source_description}",
        f"Symbol       : {request.symbol}",
        f"Interval     : {request.interval.value}",
        f"Strategy     : {request.strategy_type.value}",
        "Range (UTC)  : "
        f"{request.start_time.isoformat()} -> {request.end_time.isoformat()}",
        f"Candles      : {result.candle_count}",
        "-" * 72,
        f"Initial      : {metrics.initial_balance:.4f} USDT",
        f"Final        : {metrics.final_balance:.4f} USDT",
        f"Net PnL      : {metrics.net_pnl:+.4f} USDT ({metrics.return_pct:+.2f}%)",
        f"Max Drawdown : {metrics.max_drawdown_pct:.2f}%",
        f"Fees         : {metrics.total_fees:.4f} USDT",
        f"Trades       : {metrics.total_trades} "
        f"(long={metrics.long_trades}, short={metrics.short_trades})",
        f"Win Rate     : {metrics.win_rate_pct:.2f}% "
        f"({metrics.winning_trades}W/{metrics.losing_trades}L)",
        f"Profit Factor: {profit_factor}",
    ]
    for warning in result.warnings:
        lines.append(f"WARNING      : {warning}")

    displayed = result.trades[-_DISPLAY_TRADE_LIMIT:]
    if displayed:
        lines.extend(("-" * 72, "COMPLETED TRADES"))
        for index, trade in enumerate(displayed, start=1):
            lines.append(
                f"{index:>3}. {trade.side.value.upper():<5} "
                f"{trade.entry_time.isoformat()} -> {trade.exit_time.isoformat()} | "
                f"{trade.entry_price:.6f} -> {trade.exit_price:.6f} | "
                f"PnL {trade.realized_pnl:+.4f} | {trade.reason}"
            )
    if len(result.trades) > len(displayed):
        lines.append(
            f"Showing the latest {len(displayed)} of {len(result.trades)} trades."
        )
    lines.append("=" * 72)
    return "\n".join(lines)


# =============================================================================
# Parsing Helpers
# =============================================================================
def _required_string(*, namespace: argparse.Namespace, name: str) -> str:
    """Return one non-empty argparse string without propagating Any."""
    value: object = vars(namespace).get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Backtest argument {name!r} must not be empty")
    return value.strip()


def _parse_decimal(*, namespace: argparse.Namespace, name: str) -> Decimal:
    """Parse one finite decimal CLI argument."""
    raw_value = _required_string(namespace=namespace, name=name)
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise ValueError(f"Backtest argument {name!r} must be numeric") from error
    if not value.is_finite():
        raise ValueError(f"Backtest argument {name!r} must be finite")
    return value


def _parse_integer(*, namespace: argparse.Namespace, name: str) -> int:
    """Parse one integer CLI argument."""
    raw_value = _required_string(namespace=namespace, name=name)
    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError(f"Backtest argument {name!r} must be an integer") from error


def _parse_datetime(value: str, *, end_of_day: bool) -> datetime:
    """Parse an ISO date or datetime and normalize it to UTC."""
    normalized_value = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError as error:
        raise ValueError(f"Invalid ISO backtest datetime: {value!r}") from error

    if "T" not in normalized_value and " " not in normalized_value:
        parsed = datetime.combine(
            parsed.date(),
            time.max if end_of_day else time.min,
            tzinfo=timezone.utc,
        )
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_backtest_risk_settings(
    *,
    settings: Settings,
    request: BacktestRequest,
) -> RiskSettings:
    """Cap simulated notional to what the requested balance can fund."""
    leverage = Decimal(settings.risk.leverage)
    execution_multiplier = Decimal("1") + request.slippage_rate
    fee_multiplier = Decimal("1") + request.fee_rate * leverage
    affordable_notional = (
        request.initial_balance * leverage / (execution_multiplier * fee_multiplier)
    )
    return replace(
        settings.risk,
        max_position_size_usdt=min(
            settings.risk.max_position_size_usdt,
            affordable_notional,
        ),
    )
