# Botragram Project Structure

Dokumen ini adalah referensi kanonik untuk struktur repository Botragram yang
benar-benar tersedia. Struktur aspiratif DILARANG ditambahkan sebelum module
dibuat dan tanggung jawabnya disetujui.

Aturan arsitektur, dependency direction, coding standard, dan quality gate tetap
berasal dari `DEVELOPMENT_GUIDE.md`.

## Root Repository

```text
Botragram/
|-- botragram/                 # Production package
|-- tests/                     # Automated dan manual tests
|-- data/                      # SQLite runtime data; ignored by Git
|-- logs/                      # Runtime logs; ignored by Git
|-- .env.example              # Public environment-variable template
|-- .env.mainnet.example      # Mainnet credential template
|-- .env.testnet.example      # Testnet credential template
|-- .gitignore
|-- DEVELOPMENT_GUIDE.md       # Normative development rules
|-- PROJECT_STRUCTURE.md       # Canonical repository structure
|-- README.md
|-- main.py                    # Process entry point dan composition bootstrap
|-- pyproject.toml             # Tooling dan package configuration
`-- requirements.txt
```

## Production Package

```text
botragram/
|-- __init__.py
|-- app/
|   |-- backtest_command.py  # Isolated backtest CLI composition dan report
|   |-- application.py
|   |-- dependency_provider.py
|   |-- environment_provider.py
|   |-- lifecycle.py
|   |-- market_type_switch.py # Guarded Spot/Futures soft-restart coordination
|   |-- runtime_control.py
|   |-- settings_manager.py
|   |-- shutdown.py
|   |-- startup.py
|   |-- terminal_monitor.py    # Rich status/stream/log dashboard
|   `-- trading_runner.py
|-- config/
|   |-- ai_settings.py
|   |-- app_settings.py
|   |-- exchange_settings.py
|   |-- logging_settings.py
|   |-- market_settings.py
|   |-- risk_settings.py
|   |-- settings.py
|   |-- strategy_settings.py
|   `-- telegram_settings.py
|-- constants/
|   |-- ai.py
|   |-- app.py
|   |-- env.py
|   |-- exchange.py
|   |-- indicator.py
|   |-- market.py
|   |-- order.py
|   |-- position.py
|   |-- risk.py
|   |-- strategy.py
|   |-- telegram.py
|   `-- time.py
|-- engine/
|   |-- backtest_engine.py   # Deterministic candle replay through PAPER path
|   |-- order_engine.py
|   |-- pnl_engine.py
|   |-- portfolio_engine.py
|   |-- position_engine.py
|   |-- risk_engine.py
|   |-- signal_engine.py
|   `-- trading_engine.py
|-- enums/                     # Closed domain choices
|-- exceptions/                # Project-specific exception hierarchy
|-- exchanges/
|   |-- factory.py
|   |-- base/
|   |   |-- client.py
|   |   |-- mapper.py
|   |   |-- rest.py
|   |   `-- stream.py
|   |-- binance/
|   |   |-- client.py          # Binance Spot high-level client
|   |   |-- futures_client.py  # Binance USD(S)-M Futures client
|   |   |-- mapper.py
|   |   |-- rest.py
|   |   `-- stream.py
|   |-- bitget/
|   |-- bybit/
|   `-- okx/
|-- indicators/
|   |-- momentum/
|   |-- overlap/
|   |-- trend/
|   |-- volatility/
|   `-- volume/
|-- models/                    # Immutable domain/data models
|   `-- backtest.py            # Backtest request, trade, metrics, dan result
|-- repositories/              # Persistence interfaces
|-- services/
|   |-- account_service.py
|   |-- backtest_service.py   # Paginated historical candle orchestration
|   |-- health_service.py
|   |-- market_service.py
|   |-- order_service.py
|   |-- paper_trading_service.py
|   |-- position_protection_manager.py # Stream-driven stepped SL+
|   |-- position_service.py
|   |-- runtime_recovery_service.py # Restart recovery dan live protection gate
|   |-- runtime_reporter.py
|   |-- strategy_service.py
|   `-- trading_service.py
|-- storage/
|   |-- base/
|   |-- memory/
|   `-- sqlite/
|       |-- database.py
|       |-- migrations.py
|       `-- *_repository.py
|-- strategies/
|   |-- factory.py
|   |-- ai/
|   |-- base/
|   |-- breakout/
|   |-- scalping/
|   |-- swing/
|   `-- trend/
|-- telegram/
|   |-- access.py
|   |-- bot.py
|   |-- callbacks.py
|   |-- commands.py
|   |-- context.py
|   |-- handlers.py
|   |-- keyboards.py
|   |-- messages.py
|   `-- query_service.py
`-- utils/
    |-- datetime.py
    |-- decimal.py
    |-- formatter.py
    |-- logger.py
    `-- validator.py
```

Setiap package Python memiliki `__init__.py` ketika diperlukan untuk public API;
file tersebut tidak ditampilkan berulang pada tree agar struktur tetap terbaca.

## Test Layout

```text
tests/
|-- __init__.py
|-- manual/                    # Explicit real-network/local smoke scripts
|   |-- __init__.py
|   `-- *.py
`-- test_*.py                 # Automated unit/integration/contract tests
    termasuk test_backtest.py untuk replay, ambiguity, pagination, dan CLI
```

Automated tests DILARANG menggunakan network atau credential nyata. Script
`tests/manual/` harus aman secara default, bounded, testnet-first, dan tidak
boleh mengirim order tanpa intent eksplisit.

## Dependency Direction

```text
main.py
  -> app (composition root)
      -> config
      -> storage implementations -> repository interfaces
      -> exchange implementations -> exchange abstractions
      -> strategies -> engines -> services

telegram adapter -> service/protocol boundaries
domain models/enums -> tidak bergantung pada application atau infrastructure
```

Concrete dependency hanya dibangun oleh `DependencyProvider`. Service dan engine
tidak boleh membuat HTTP client, database, repository, atau service konkret.

## Runtime-Owned Paths

- Database default: `data/botragram.db`.
- Rotating log default: `logs/botragram.log`.
- Credential runtime: `.env.testnet` dan `.env.mainnet`; keduanya ignored.
- Cache, coverage output, virtual environment, database, WAL, dan log tidak
  termasuk source structure dan tidak boleh di-commit.

## Maintenance Rule

Perubahan yang menambah, memindahkan, atau menghapus package/module utama WAJIB
memperbarui dokumen ini pada perubahan yang sama. Ringkasan struktur di
`DEVELOPMENT_GUIDE.md` harus tetap konsisten dengan dokumen ini.
