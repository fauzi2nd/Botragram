"""
Botragram

Description:
    Environment variable key constants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

__all__ = [
    "ENV_OPENAI_API_KEY",
    "ENV_GEMINI_API_KEY",
    "ENV_OPENROUTER_API_KEY",
    "ENV_AI_PROVIDER",
    "ENV_AI_MODEL",
    "ENV_TELEGRAM_TOKEN",
    "ENV_TELEGRAM_TOKEN_LEGACY",
    "ENV_TELEGRAM_CHAT_ID",
    "ENV_TRADE_MODE",
    "ENV_AUTONOMOUS_EXECUTION_ENABLED",
    "ENV_AUTONOMOUS_LIVE_ENTRY_ENABLED",
    "ENV_AUTONOMOUS_MAINNET_ENTRY_ENABLED",
    "ENV_EXECUTION_POLICY",
    "ENV_STRATEGY_TYPE",
    "ENV_INVERT_SIGNALS",
    "ENV_MIN_SIGNAL_CONFIDENCE",
    "ENV_LOG_LEVEL",
    "ENV_SCALPING_STOP_LOSS_PCT",
    "ENV_SCALPING_TAKE_PROFIT_PCT",
    "ENV_TREND_STOP_LOSS_PCT",
    "ENV_TREND_TAKE_PROFIT_PCT",
    "ENV_SWING_STOP_LOSS_PCT",
    "ENV_SWING_TAKE_PROFIT_PCT",
    "ENV_STOP_LOSS_PCT",
    "ENV_TAKE_PROFIT_PCT",
    "ENV_EMA_CROSS_STOP_LOSS_PCT",
    "ENV_EMA_CROSS_TAKE_PROFIT_PCT",
    "ENV_EMA_SCALPING_STOP_LOSS_PCT",
    "ENV_EMA_SCALPING_TAKE_PROFIT_PCT",
    "ENV_MAX_OPEN_POSITIONS",
    "ENV_MAX_POSITION_SIZE_USDT",
    "ENV_RISK_PER_TRADE_PCT",
    "ENV_MAX_DRAWDOWN_PCT",
    "ENV_LEVERAGE",
    "ENV_MAX_EXECUTABLE_QUOTE_AGE_MS",
    "ENV_MAX_SPREAD_BPS",
    "ENV_MARKET_INTERVAL",
    "ENV_DISCOVERY_UNIVERSE_LIMIT",
    "ENV_DISCOVERY_BATCH_SIZE",
    "ENV_DISCOVERY_CADENCE_SECONDS",
    "ENV_BOTRAGRAM_PROFILE",
    "ENV_BOTRAGRAM_ENV_FILE",
    "ENV_ACTIVE_EXCHANGE",
    "ENV_BINANCE_API_KEY",
    "ENV_BINANCE_API_SECRET",
    "ENV_BINANCE_MARKET_TYPE",
    "ENV_BINANCE_TESTNET",
    "ENV_BITGET_API_KEY",
    "ENV_BITGET_API_SECRET",
    "ENV_BITGET_PASSPHRASE",
    "ENV_BITGET_TESTNET",
    "ENV_BYBIT_API_KEY",
    "ENV_BYBIT_API_SECRET",
    "ENV_BYBIT_TESTNET",
    "ENV_OKX_API_KEY",
    "ENV_OKX_API_SECRET",
    "ENV_OKX_PASSPHRASE",
    "ENV_OKX_TESTNET",
    "ENV_EXCHANGE_API_KEY_LEGACY",
    "ENV_EXCHANGE_API_SECRET_LEGACY",
    "ENV_TRADE_MODE_LEGACY",
    "ENV_LOG_LEVEL_LEGACY",
]

# =============================================================================
# Constants — AI
# =============================================================================
ENV_OPENAI_API_KEY: str = "OPENAI_API_KEY"
ENV_GEMINI_API_KEY: str = "GEMINI_API_KEY"
ENV_OPENROUTER_API_KEY: str = "OPENROUTER_API_KEY"
ENV_AI_PROVIDER: str = "AI_PROVIDER"
ENV_AI_MODEL: str = "AI_MODEL"

# =============================================================================
# Constants — Telegram
# =============================================================================
ENV_TELEGRAM_TOKEN: str = "TELEGRAM_TOKEN"
ENV_TELEGRAM_TOKEN_LEGACY: str = "BOTRAGRAM_TELEGRAM_TOKEN"
ENV_TELEGRAM_CHAT_ID: str = "TELEGRAM_CHAT_ID"

# =============================================================================
# Constants — Application Settings
# =============================================================================
ENV_TRADE_MODE: str = "TRADE_MODE"
ENV_AUTONOMOUS_EXECUTION_ENABLED: str = "AUTONOMOUS_EXECUTION_ENABLED"
ENV_AUTONOMOUS_LIVE_ENTRY_ENABLED: str = "AUTONOMOUS_LIVE_ENTRY_ENABLED"
ENV_AUTONOMOUS_MAINNET_ENTRY_ENABLED: str = "AUTONOMOUS_MAINNET_ENTRY_ENABLED"
ENV_EXECUTION_POLICY: str = "EXECUTION_POLICY"
ENV_STRATEGY_TYPE: str = "STRATEGY_TYPE"
ENV_INVERT_SIGNALS: str = "INVERT_SIGNALS"
ENV_MIN_SIGNAL_CONFIDENCE: str = "MIN_SIGNAL_CONFIDENCE"
ENV_LOG_LEVEL: str = "LOG_LEVEL"
ENV_BOTRAGRAM_PROFILE: str = "BOTRAGRAM_PROFILE"
ENV_BOTRAGRAM_ENV_FILE: str = "BOTRAGRAM_ENV_FILE"

# =============================================================================
# Constants — Risk
# =============================================================================
ENV_SCALPING_STOP_LOSS_PCT: str = "SCALPING_STOP_LOSS_PCT"
ENV_SCALPING_TAKE_PROFIT_PCT: str = "SCALPING_TAKE_PROFIT_PCT"
ENV_TREND_STOP_LOSS_PCT: str = "TREND_STOP_LOSS_PCT"
ENV_TREND_TAKE_PROFIT_PCT: str = "TREND_TAKE_PROFIT_PCT"
ENV_SWING_STOP_LOSS_PCT: str = "SWING_STOP_LOSS_PCT"
ENV_SWING_TAKE_PROFIT_PCT: str = "SWING_TAKE_PROFIT_PCT"
ENV_STOP_LOSS_PCT: str = "STOP_LOSS_PCT"
ENV_TAKE_PROFIT_PCT: str = "TAKE_PROFIT_PCT"
ENV_EMA_CROSS_STOP_LOSS_PCT: str = "EMA_CROSS_STOP_LOSS_PCT"
ENV_EMA_CROSS_TAKE_PROFIT_PCT: str = "EMA_CROSS_TAKE_PROFIT_PCT"
ENV_EMA_SCALPING_STOP_LOSS_PCT: str = "EMA_SCALPING_STOP_LOSS_PCT"
ENV_EMA_SCALPING_TAKE_PROFIT_PCT: str = "EMA_SCALPING_TAKE_PROFIT_PCT"
ENV_MAX_OPEN_POSITIONS: str = "MAX_OPEN_POSITIONS"
ENV_MAX_POSITION_SIZE_USDT: str = "MAX_POSITION_SIZE_USDT"
ENV_RISK_PER_TRADE_PCT: str = "RISK_PER_TRADE_PCT"
ENV_MAX_DRAWDOWN_PCT: str = "MAX_DRAWDOWN_PCT"
ENV_LEVERAGE: str = "LEVERAGE"
ENV_MAX_EXECUTABLE_QUOTE_AGE_MS: str = "MAX_EXECUTABLE_QUOTE_AGE_MS"
ENV_MAX_SPREAD_BPS: str = "MAX_SPREAD_BPS"
ENV_MARKET_INTERVAL: str = "MARKET_INTERVAL"
ENV_DISCOVERY_UNIVERSE_LIMIT: str = "DISCOVERY_UNIVERSE_LIMIT"
ENV_DISCOVERY_BATCH_SIZE: str = "DISCOVERY_BATCH_SIZE"
ENV_DISCOVERY_CADENCE_SECONDS: str = "DISCOVERY_CADENCE_SECONDS"

# =============================================================================
# Constants — Exchange
# =============================================================================
ENV_ACTIVE_EXCHANGE: str = "ACTIVE_EXCHANGE"

# =============================================================================
# Constants — Binance
# =============================================================================
ENV_BINANCE_API_KEY: str = "BINANCE_API_KEY"
ENV_BINANCE_API_SECRET: str = "BINANCE_API_SECRET"
ENV_BINANCE_MARKET_TYPE: str = "BINANCE_MARKET_TYPE"
ENV_BINANCE_TESTNET: str = "BINANCE_TESTNET"

# =============================================================================
# Constants — Bitget
# =============================================================================
ENV_BITGET_API_KEY: str = "BITGET_API_KEY"
ENV_BITGET_API_SECRET: str = "BITGET_API_SECRET"
ENV_BITGET_PASSPHRASE: str = "BITGET_PASSPHRASE"
ENV_BITGET_TESTNET: str = "BITGET_TESTNET"

# =============================================================================
# Constants — Bybit
# =============================================================================
ENV_BYBIT_API_KEY: str = "BYBIT_API_KEY"
ENV_BYBIT_API_SECRET: str = "BYBIT_API_SECRET"
ENV_BYBIT_TESTNET: str = "BYBIT_TESTNET"

# =============================================================================
# Constants — OKX
# =============================================================================
ENV_OKX_API_KEY: str = "OKX_API_KEY"
ENV_OKX_API_SECRET: str = "OKX_API_SECRET"
ENV_OKX_PASSPHRASE: str = "OKX_PASSPHRASE"
ENV_OKX_TESTNET: str = "OKX_TESTNET"

# =============================================================================
# Legacy fallback keys (kept for backward compatibility)
# =============================================================================
ENV_EXCHANGE_API_KEY_LEGACY: str = "BOTRAGRAM_EXCHANGE_API_KEY"
ENV_EXCHANGE_API_SECRET_LEGACY: str = "BOTRAGRAM_EXCHANGE_API_SECRET"
ENV_TRADE_MODE_LEGACY: str = "BOTRAGRAM_TRADE_MODE"
ENV_LOG_LEVEL_LEGACY: str = "BOTRAGRAM_LOG_LEVEL"
