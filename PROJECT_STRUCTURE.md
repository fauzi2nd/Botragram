# Botragram Project Structure

Dokumen ini adalah referensi kanonik untuk struktur repository Botragram yang
benar-benar tersedia. Struktur aspiratif DILARANG ditambahkan sebelum module
dibuat dan tanggung jawabnya disetujui.

Aturan arsitektur, dependency direction, coding standard, dan quality gate tetap
berasal dari `DEVELOPMENT_GUIDE.md`.

## Root Repository

```text
Botragram/
|-- .github/
|   `-- workflows/
|       `-- quality.yml       # Supplemental non-blocking quality signal
|-- botragram/                 # Production package
|-- tests/                     # Automated dan manual tests
|-- data/                      # SQLite runtime data; ignored by Git
|-- logs/                      # Runtime logs; ignored by Git
|-- .env.example              # Public environment-variable template
|-- .env.autonomous_testnet_soak.example # Explicit autonomous TESTNET soak base
|-- .env.autonomous_testnet_soak.testnet.example # TESTNET credential template
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
|   |-- connectivity.py      # Backward-compatible classifier re-export
|   |-- application.py
|   |-- dependency_provider.py
|   |-- live_futures_user_data_service.py # Owned REST-seeded private Futures cache lifecycle
|   |-- environment_provider.py
|   |-- global_discovery_telemetry.py # Read-only ranked discovery phase/outcome snapshot
|   |-- lifecycle.py
|   |-- market_type_switch.py # Guarded MarketType/ExecutionPolicy in-process reconfiguration/soft restart
|   |-- runtime_control.py
|   |-- runtime_instance_lock.py # One runtime per database-scoped deployment
|   |-- runtime_limited_autonomous_live_executor.py # Dynamic durable capacity adapter
|   |-- settings_manager.py
|   |-- shutdown.py
|   |-- startup.py
|   |-- terminal_monitor.py    # Rich status/stream/log dashboard
|   `-- trading_runner.py        # Single-symbol and global cycle orchestration
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
|-- enums/                     # Closed domain choices, including exchange_environment.py
|   |-- autonomous_live_entry_execution_status.py # Typed protected-entry outcome
|   |-- autonomous_live_entry_intent_status.py # Typed autonomous intent outcome
|   `-- global_discovery_cycle_outcome.py # Last completed discovery outcome
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
|   |   |-- futures_client.py # Binance USD(S)-M Futures client
|   |   |-- futures_user_data_stream.py # Binance private account User Data Stream
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
|   |-- autonomous_live_entry_authorization.py # Network-scoped future-entry capability
|   |-- autonomous_live_entry_execution.py # Typed protected-entry execution result
|   |-- autonomous_live_entry_intent.py # Transient authorized LIVE entry intent
|   |-- autonomous_live_recovery_snapshot.py # Immutable durable recovery status
|   |-- closed_position_lifecycle.py # One authoritative closed LIVE position lifecycle
|   |-- discovery_universe_batch.py # Immutable contiguous ranked discovery window
|   |-- live_entry_risk_evaluation.py # Immutable fresh LIVE risk decision
|   |-- runtime_risk_limits.py # Durable autonomous LIVE runtime entry limits
|   `-- backtest.py            # Backtest request, trade, metrics, dan result
|   |-- live_market_stream_identity.py # LIVE ticker subscription identity
|   |-- live_market_stream_state.py # Immutable per-stream telemetry snapshot
|   |-- live_runtime_health_snapshot.py # Read-only recovered LIVE health snapshot
|   |-- live_runtime_position_context.py # One recovered LIVE runtime context
|   |-- live_runtime_portfolio_context.py # Immutable recovered LIVE portfolio
|   `-- market_universe_entry.py # Binance-independent ranked market fact
|-- repositories/              # Persistence interfaces, including lifecycle ledger
|   |-- closed_position_lifecycle_repository.py # Durable entry-identity ledger contract
|   `-- runtime_risk_limit_repository.py # Durable current-limit + audit boundary
|-- services/
|   |-- account_service.py
|   |-- autonomous_live_entry_execution_service.py # Fresh-risk protected network-scoped entry adapter
|   |-- autonomous_live_entry_intent_service.py # Pure network-scoped intent authorization
|   |-- autonomous_live_recovery_observability_service.py # Read-only recovery view
|   |-- live_entry_risk_evaluation_service.py # Authoritative portfolio/balance decision
|   |-- live_executable_quote_service.py # Shared fresh quote and signal provenance gate
|   |-- autonomous_paper_execution_service.py # Ranked PAPER candidate execution
|   |-- backtest_service.py   # Paginated historical candle orchestration
|   |-- execution_authorization_service.py # PAPER human-approval boundary
|   |-- health_service.py
|   |-- human_confirmed_paper_execution_service.py # Discovery-to-approval orchestration
|   |-- market_service.py
|   |-- live_market_stream_service.py # Production 0/1/N LIVE stream ownership
|   |-- live_futures_entry_service.py # Protected Futures MARKET entry workflow
|   |-- live_futures_user_data_cache.py # Thread-safe cached private Futures account state
|   |-- live_post_entry_recovery_service.py # ACKNOWLEDGED entry recovery core
|   |-- live_position_protection_service.py # Shared LIVE SL/TP reconciliation
|   |-- live_protection_monitoring_service.py # Production 0/1/N protection monitor owner
|   |-- live_portfolio_recovery_service.py # LIVE portfolio safety recovery
|   |-- live_runtime_portfolio_reconciliation_service.py # Canonical 0/1/N LIVE management reconciliation
|   |-- live_runtime_health_service.py # Derived recovered LIVE health aggregation
|   |-- live_submission_recovery_service.py # GET-only incomplete entry recovery
|   |-- closed_position_lifecycle_service.py # Exact-order gross/fee/net enrichment
|   |-- live_trading_performance_service.py # One net outcome per completed lifecycle
|   |-- opportunity_discovery_service.py # Bounded actionable signal discovery
|   |-- order_service.py
|   |-- paper_trading_service.py
|   |-- position_protection_manager.py # Stream-driven stepped SL+
|   |-- position_service.py
|   |-- runtime_recovery_service.py # Restart recovery dan live protection gate
|   |-- runtime_reporter.py
|   |-- runtime_risk_limit_service.py # Durable runtime canary-limit authority
|   |-- strategy_service.py
|   |-- volume_ranked_discovery_universe_service.py # Full ranked snapshot, bounded rotation
|   `-- trading_service.py
|-- storage/
|   |-- base/
|   |-- memory/
|   `-- sqlite/
|       |-- database.py
|       |-- closed_position_lifecycle_repository.py # SQLite lifecycle ledger
|       |-- legacy_live_ledger_migration.py # One-time legacy TESTNET LIVE ledger import
|       |-- migrations.py
|       |-- runtime_risk_limit_repository.py # Current singleton + append-only audit
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
|   |-- risk_limit_commands.py # Paused durable runtime-limit controls
|   `-- query_service.py
`-- utils/
    |-- connectivity.py       # Shared transient dependency-failure classification
    |-- datetime.py
    |-- decimal.py
    |-- formatter.py
    |-- logger.py
    |-- retry.py              # Capped exponential backoff with jitter
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
