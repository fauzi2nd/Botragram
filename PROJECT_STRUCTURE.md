# Botragram Project Structure

Dokumen ini adalah referensi kanonik untuk struktur repository Botragram yang
benar-benar tersedia. Struktur aspiratif DILARANG ditambahkan sebelum module
dibuat dan tanggung jawabnya disetujui.

Aturan arsitektur, dependency direction, coding standard, dan quality gate tetap
berasal dari `DEVELOPMENT_GUIDE.md`.

Tree menampilkan package dan module utama. Rincian `enums`, `models`,
`repositories`, serta package tanpa daftar anak merupakan ringkasan, bukan daftar
seluruh file. Inventaris lengkap source dapat diperiksa dengan
`rg --files botragram tests`.

## Root Repository

```text
Botragram/
|-- .github/
|   `-- workflows/
|       `-- release-gate.yml  # Authoritative blocking release gate verification (sole CI gate)
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
|-- RELEASE_CERTIFICATION.md    # Authoritative Windows release certification report
|-- main.py                    # Process entry point dan composition bootstrap
|-- pyproject.toml             # Tooling dan package configuration
`-- requirements.txt
```

## Production Package

```text
botragram/
|-- __init__.py
|-- app/
|   |-- application.py
|   |-- autonomous_live_cycle_executor.py # Compatibility import for runtime/
|   |-- backfill_command.py  # Historical candle backfill CLI runner
|   |-- backtest_command.py  # Isolated backtest CLI composition dan report
|   |-- connectivity.py      # Backward-compatible classifier re-export
|   |-- context_cycle_scheduler.py # Compatibility import for runtime/
|   |-- dependency_provider.py # Composition root dan manual wiring container
|   |-- env_validator.py       # Startup validation for duplicate environment keys
|   |-- environment_provider.py
|   |-- global_discovery_telemetry.py # Read-only ranked discovery phase/outcome snapshot
|   |-- lifecycle.py
|   |-- live_futures_user_data_service.py # Owned REST-seeded private Futures cache lifecycle
|   |-- live_runtime_recovery_policy.py # Compatibility import for runtime/
|   |-- market_type_switch.py # Guarded MarketType/ExecutionPolicy in-process reconfiguration/soft restart
|   |-- multi_context_activation.py # Compatibility import for runtime/
|   |-- operator_terminal_monitor.py # Operator dashboard monitor adapter
|   |-- paper_cycle_executors.py # Compatibility import for runtime/
|   |-- responsive_terminal_monitor.py # Terminal monitor responsive layout
|   |-- runtime/
|   |   |-- autonomous_live_cycle_executor.py # Ranked LIVE protected entry
|   |   |-- context_cycle_scheduler.py # Per-context cycle cadence
|   |   |-- live_runtime_recovery_policy.py # Pure LIVE recovery health gates
|   |   |-- multi_context_activation.py # Immutable activation preconditions
|   |   |-- paper_cycle_executors.py # PAPER discovery cycle adapters
|   |   `-- single_symbol_cycle_executor.py # Single-symbol runtime adapter
|   |-- runtime_control.py
|   |-- runtime_instance_lock.py # One runtime per database-scoped deployment
|   |-- runtime_limited_autonomous_live_executor.py # Dynamic durable capacity adapter
|   |-- settings_manager.py
|   |-- single_symbol_cycle_executor.py # Compatibility import for runtime/
|   |-- shutdown.py
|   |-- startup.py
|   |-- terminal_monitor.py    # Rich status/stream/log dashboard
|   `-- trading_runner.py        # Single-symbol and global cycle orchestration
|-- config/
|   |-- ai_settings.py
|   |-- app_settings.py
|   |-- exchange_settings.py
|   |-- logging_settings.py
|   |-- market_settings.py     # Global market interval (canonical) and discovery configuration
|   |-- risk_settings.py
|   |-- settings.py            # Authoritative aggregate settings (effective_strategy_interval)
|   |-- strategy_settings.py   # Strategy parameters and active timeframe override
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
|   |-- accounting/
|   |   `-- pnl_engine.py # Profit/loss calculations
|   |-- backtest/
|   |   `-- backtest_engine.py # Deterministic PAPER-path candle replay
|   |-- cfd/
|   |   |-- cfd_financing_engine.py # CFD holding-cost calculations
|   |   |-- cfd_sizing_engine.py # CFD contract sizing
|   |   `-- market_calendar.py # TradFi market-session calendar
|   |-- order/
|   |   `-- order_engine.py # Order execution decisions
|   |-- portfolio/
|   |   `-- portfolio_engine.py # Portfolio calculations
|   |-- position/
|   |   |-- position_engine.py # Position management calculations
|   |   `-- position_exit_engine.py # Position exit decisions
|   |-- risk/
|   |   `-- risk_engine.py # Risk evaluation and sizing
|   |-- trading/
|   |   |-- signal_engine.py # Signal generation
|   |   `-- trading_engine.py # Trading execution decisions
|   |-- backtest_engine.py # Compatibility import for backtest/
|   |-- cfd_financing_engine.py # Compatibility import for cfd/
|   |-- cfd_sizing_engine.py # Compatibility import for cfd/
|   |-- market_calendar.py # Compatibility import for cfd/
|   |-- order_engine.py # Compatibility import for order/
|   |-- pnl_engine.py # Compatibility import for accounting/
|   |-- portfolio_engine.py # Compatibility import for portfolio/
|   |-- position_engine.py # Compatibility import for position/
|   |-- position_exit_engine.py # Compatibility import for position/
|   |-- risk_engine.py # Compatibility import for risk/
|   |-- signal_engine.py # Compatibility import for trading/
|   `-- trading_engine.py # Compatibility import for trading/
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
|   |   |-- authoritative_futures_client.py # Deterministic authoritative Futures state client
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
|   |-- derivatives/
|   |-- momentum/
|   |-- overlap/
|   |-- price_action/         # Deterministic price action & SMC calculations (CHoCH, FVG)
|   |-- trend/
|   |-- volatility/
|   `-- volume/
|-- models/                    # Immutable domain/data models
|   |-- autonomous_live_entry_authorization.py # Network-scoped future-entry capability
|   |-- autonomous_live_entry_execution.py # Typed protected-entry execution result
|   |-- autonomous_live_entry_intent.py # Transient authorized LIVE entry intent
|   |-- autonomous_live_recovery_snapshot.py # Immutable durable recovery status
|   |-- backtest.py            # Backtest request, trade, metrics, dan result
|   |-- closed_position_lifecycle.py # One authoritative closed LIVE position lifecycle
|   |-- discovery_universe_batch.py # Immutable contiguous ranked discovery window
|   |-- exchange_symbol_rules.py # Venue precision, lot size, min notional, price filter rules
|   |-- executable_quote.py    # Proven fresh executable quote snapshot
|   |-- execution_authorization.py # Human approval challenge/authorization
|   |-- futures_user_data.py   # Cached private balance and position account facts
|   |-- live_entry_risk_evaluation.py # Immutable fresh LIVE risk decision
|   |-- live_equity_high_water_mark.py # Durable high-water mark for live account drawdown
|   |-- live_market_stream_identity.py # LIVE ticker subscription identity
|   |-- live_market_stream_state.py # Immutable per-stream telemetry snapshot
|   |-- live_portfolio_recovery.py # Portfolio-level recovery observation and facts
|   |-- live_protection_monitor_state.py # Production protection health state
|   |-- live_recovered_position_management_authorization.py # Authorized management token
|   |-- live_runtime_health_snapshot.py # Read-only recovered LIVE health snapshot
|   |-- live_runtime_portfolio_context.py # Immutable recovered LIVE portfolio
|   |-- live_runtime_position_context.py # One recovered LIVE runtime context
|   |-- market_universe_entry.py # Binance-independent ranked market fact
|   |-- operator_exit.py       # Durable operator exit operation/attempt/confirmation snapshots
|   `-- runtime_risk_limits.py # Durable autonomous LIVE runtime entry limits
|-- repositories/              # Persistence interfaces, including lifecycle ledger
|   |-- autonomous_live_opportunity_claim_repository.py # Atomic single-claim candidate gate
|   |-- candle_storage_optimizer.py # Backend-neutral post-prune maintenance contract
|   |-- closed_position_lifecycle_repository.py # Durable entry-identity ledger contract
|   |-- execution_authorization_repository.py # Human paper approval contract
|   |-- live_equity_high_water_repository.py # Peak balance persistence contract
|   |-- live_recovery_repository.py # Durable live recovery state contract
|   |-- operator_exit_repository.py # Restart-safe operator exit ownership contract
|   |-- position_repository.py # Active position persistence contract
|   |-- runtime_risk_limit_repository.py # Durable current-limit + audit boundary
|   |-- runtime_settings_repository.py # Durable runtime configuration and strategy persistence
|   `-- submission_attempt_repository.py # Incomplete entry attempt contract
|-- services/
|   |-- account_service.py
|   |-- autonomous_live_entry_execution_service.py # Compatibility import for execution/
|   |-- autonomous_live_entry_intent_service.py # Compatibility import for execution/
|   |-- autonomous_live_recovery_observability_service.py # Read-only recovery view
|   |-- autonomous_paper_execution_service.py # Ranked PAPER candidate execution
|   |-- backtest_service.py   # Paginated historical candle orchestration
|   |-- candle_retention_service.py # Compatibility import for market/candle_retention_service.py
|   |-- candle_sync_service.py # Compatibility import for market/candle_sync_service.py
|   |-- closed_position_lifecycle_service.py # Compatibility import for position/
|   |-- discovery/
|   |   |-- opportunity_discovery_service.py # Bounded actionable signal discovery
|   |   |-- setup_stalking_service.py # Pre-entry setup tracking and confirmation
|   |   `-- volume_ranked_discovery_universe_service.py # Ranked snapshot and bounded rotation
|   |-- execution/
|   |   |-- autonomous_live_entry_execution_service.py # Fresh-risk protected entry adapter
|   |   |-- autonomous_live_entry_intent_service.py # Network-scoped intent authorization
|   |   |-- execution_authorization_service.py # PAPER human-approval boundary
|   |   |-- live_futures_entry_service.py # Protected Futures MARKET entry workflow
|   |   `-- order_service.py # Order submission and persistence
|   |-- execution_authorization_service.py # Compatibility import for execution/
|   |-- health_service.py
|   |-- human_confirmed_paper_execution_service.py # Discovery-to-approval orchestration
|   |-- live_account_drawdown_service.py # Account-level drawdown protection against peak equity
|   |-- live_entry_risk_evaluation_service.py # Authoritative portfolio/balance decision
|   |-- live_executable_quote_service.py # Shared fresh quote and signal provenance gate
|   |-- live_futures_entry_service.py # Compatibility import for execution/
|   |-- live_futures_user_data_cache.py # Thread-safe cached private Futures account state
|   |-- live_market_stream_service.py # Production 0/1/N LIVE stream ownership
|   |-- live_position_lifecycle_coordinator.py # Compatibility import for position/
|   |-- live_runtime_health_service.py # Compatibility import for runtime/
|   |-- live_runtime_portfolio_reconciliation_service.py # Compatibility import for runtime/
|   |-- live_trading_performance_service.py # One net outcome per completed lifecycle
|   |-- market/
|   |   |-- candle_retention_service.py # Stored candle retention
|   |   |-- candle_sync_service.py # Bounded candle gap synchronization
|   |   |-- market_service.py # Exchange and persisted market data access
|   |   `-- stored_resampled_candle_provider.py # Stored candle replay input
|   |-- market_service.py # Compatibility import for market/market_service.py
|   |-- notification_message_formatter.py # Transport-neutral notification formatting contract
|   |-- operator_exit_service.py # Guarded PAPER/LIVE close + flatten-and-switch orchestration
|   |-- order_service.py # Compatibility import for execution/
|   |-- paper_trading_service.py
|   |-- position/
|   |   |-- closed_position_lifecycle_service.py # Exact-order gross/fee/net enrichment
|   |   |-- live_position_lifecycle_coordinator.py # Per-symbol lifecycle serialization
|   |   |-- position_exit_service.py # In-flight position exit orchestration
|   |   `-- position_service.py # Position sync and persistence
|   |-- position_exit_service.py # Compatibility import for position/
|   |-- position_service.py # Compatibility import for position/
|   |-- protection/
|   |   |-- live_position_protection_service.py # Shared LIVE SL/TP reconciliation
|   |   |-- live_protection_monitoring_service.py # Production 0/1/N protection monitor owner
|   |   `-- position_protection_manager.py # Stream-driven stepped SL+
|   |-- recovery/
|   |   |-- live_natural_exit_recovery_service.py # Natural SL/TP fill detection and ledgering
|   |   |-- live_portfolio_recovery_service.py # LIVE portfolio safety recovery
|   |   |-- live_post_entry_recovery_service.py # ACKNOWLEDGED entry recovery core
|   |   |-- live_submission_recovery_service.py # GET-only incomplete entry recovery
|   |   `-- runtime_recovery_service.py # Restart recovery dan live protection gate
|   |-- runtime/
|   |   |-- live_runtime_health_service.py # Derived recovered LIVE health aggregation
|   |   |-- live_runtime_portfolio_reconciliation_service.py # Canonical 0/1/N management reconciliation
|   |   |-- runtime_reporter.py # Runtime status and portfolio reporting
|   |   `-- runtime_risk_limit_service.py # Durable runtime canary-limit authority
|   |-- runtime_reporter.py # Compatibility import for runtime/
|   |-- runtime_risk_limit_service.py # Compatibility import for runtime/
|   |-- stored_resampled_candle_provider.py # Compatibility import for market/
|   |-- strategy_service.py
|   `-- trading_service.py
|-- storage/
|   |-- base/
|   |-- memory/
|   `-- sqlite/
|       |-- autonomous_live_opportunity_claim_repository.py # Atomic claim persistence
|       |-- closed_position_lifecycle_repository.py # SQLite lifecycle ledger
|       |-- database.py
|       |-- legacy_live_ledger_migration.py # One-time legacy TESTNET LIVE ledger import
|       |-- live_equity_high_water_repository.py # SQLite high-water mark persistence
|       |-- live_recovery_repository.py # SQLite live recovery persistence
|       |-- migrations.py
|       |-- operator_exit_repository.py # Durable operator exit operations and attempts
|       |-- runtime_risk_limit_repository.py # Current singleton + append-only audit
|       |-- runtime_settings_repository.py # SQLite runtime settings persistence
|       `-- *_repository.py
|-- strategies/
|   |-- factory.py
|   |-- ai/
|   |-- base/
|   |-- breakout/
|   |-- price_action/          # Smart Money Concepts / Structure Shift (CHoCH, FVG)
|   |-- scalping/
|   |-- swing/
|   `-- trend/
|-- telegram/
|   |-- access.py
|   |-- bot.py
|   |-- callback_routes/
|   |   |-- authorization.py # PAPER approval callback boundary
|   |   |-- callbacks.py # Callback routing and remaining configuration controls
|   |   |-- execution_policy.py # Guarded trading-mode switch callbacks
|   |   `-- operator_exit.py # Guarded portfolio-exit callbacks
|   |-- callbacks.py # Compatibility import for callback_routes/
|   |-- commands.py
|   |-- context.py
|   |-- handlers.py
|   |-- keyboards.py # Compatibility import for presentation/
|   |-- leverage_commands.py
|   |-- messages.py # Compatibility import for presentation/
|   |-- operator_exit_commands.py # Explicit chat-bound portfolio exit controls
|   |-- operator_exit_progress.py # Real-time progress updates during operator exit
|   |-- presentation/
|   |   |-- keyboards.py # Telegram reply and inline keyboard layouts
|   |   |-- messages.py # Telegram HTML message templates
|   |   `-- notification_message_formatter.py # Domain-fact to Telegram HTML adapter
|   |-- query_service.py
|   |-- risk_limit_commands.py # Paused durable runtime-limit controls
|   |-- runtime_menu_refresh.py # Mode-aware home menu synchronization
|   |-- strategy_flatten_switch.py # Guarded flatten-and-strategy soft restart
|   `-- strategy_switch.py     # Interactive strategy selection and routing
`-- utils/
    |-- candle_aggregator.py
    |-- candle_resampler.py
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
|-- terminal_helpers.py        # Explicit Rich console dimensions for portable tests
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
Notifikasi service memakai kontrak formatter; implementasi HTML Telegram hanya
dibangun dan disuntikkan oleh `DependencyProvider`. Retensi candle memakai
kontrak optimasi storage tanpa SQL atau tipe SQLite di service.

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
