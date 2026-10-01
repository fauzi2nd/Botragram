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
|   |-- backtest_session_factory.py # Isolated PAPER replay composition
|   |-- cli/
|   |   |-- backfill_command.py # Historical candle backfill CLI runner
|   |   `-- backtest_command.py # Isolated backtest CLI composition dan report
|   |-- dependency_provider.py # Composition root dan manual wiring container
|   |-- lifecycle.py
|   |-- runtime/
|   |   |-- autonomous_live_cycle_executor.py # Ranked LIVE protected entry
|   |   |-- context_cycle_scheduler.py # Per-context cycle cadence
|   |   |-- global_discovery_telemetry.py # Read-only ranked discovery snapshot
|   |   |-- live_futures_user_data_service.py # Private Futures cache lifecycle
|   |   |-- live_runtime_recovery_policy.py # Pure LIVE recovery health gates
|   |   |-- market_type_switch.py # Guarded market-type soft restart
|   |   |-- paper_cycle_executors.py # PAPER discovery cycle adapters
|   |   |-- runtime_control.py
|   |   |-- runtime_instance_lock.py # One runtime per database-scoped deployment
|   |   |-- runtime_limited_autonomous_live_executor.py # Durable capacity adapter
|   |   |-- single_symbol_cycle_executor.py # Single-symbol runtime adapter
|   |   `-- trading_runner.py # Single-symbol and global cycle orchestration
|   |-- settings/
|   |   |-- env_validator.py # Duplicate environment-key validation
|   |   |-- environment_provider.py
|   |   `-- settings_manager.py
|   |-- shutdown.py
|   |-- startup.py
|   `-- terminal/
|       |-- operator_terminal_monitor.py # Operator dashboard adapter
|       |-- responsive_terminal_monitor.py # Responsive layout
|       `-- terminal_monitor.py # Rich status/stream/log dashboard
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
|   `-- trading/
|       |-- signal_engine.py # Signal generation
|       `-- trading_engine.py # Trading execution decisions
|-- enums/                     # Closed domain choices; public exports remain at package root
|   |-- base.py
|   |-- log_level.py
|   |-- notification_type.py
|   |-- ai/
|   |-- account/
|   |-- cfd/
|   |-- discovery/
|   |-- execution/
|   |-- market/
|   |-- position/
|   |-- recovery/
|   |-- runtime/
|   `-- strategy/
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
|-- models/                    # Immutable domain/data models; package-root exports remain
|   |-- notification.py        # Cross-context notification fact
|   |-- account/               # Account, balance, private Futures updates
|   |-- backtest/              # Historical replay request and result
|   |-- cfd/                   # CFD contracts and financing
|   |-- discovery/             # Ranked universe and discovery reports
|   |-- execution/             # Orders, signals, trades, risk, entry authority
|   |-- market/                # Candles, ticker, venue rules, stream facts
|   |-- position/              # Position, protection, exit, lifecycle
|   |-- recovery/              # Recovered LIVE portfolio and contexts
|   |-- runtime/               # Runtime health and risk-limit snapshots
|   `-- strategy/              # Stalking setup facts
|-- repositories/              # Persistence interfaces; implementations remain in storage/
|   |-- discovery/             # Atomic opportunity-claim contract
|   |-- execution/             # Order, signal, trade, authorization contracts
|   |-- market/                # Candle and retention contracts
|   |-- position/              # Position, lifecycle, operator-exit contracts
|   `-- runtime/               # Runtime settings, recovery, equity, risk limits
|-- services/
|   |-- account/
|   |   |-- account_service.py
|   |   |-- live_account_drawdown_service.py # Account drawdown protection
|   |   |-- live_futures_user_data_cache.py # Cached private Futures account state
|   |   `-- live_trading_performance_service.py # Net lifecycle performance
|   |-- backtest/
|   |   `-- backtest_service.py # Paginated historical candle orchestration
|   |-- discovery/
|   |   |-- opportunity_discovery_service.py # Bounded actionable signal discovery
|   |   |-- setup_stalking_service.py # Pre-entry setup tracking and confirmation
|   |   `-- volume_ranked_discovery_universe_service.py # Ranked snapshot and bounded rotation
|   |-- execution/
|   |   |-- autonomous_live_entry_execution_service.py # Fresh-risk protected entry adapter
|   |   |-- autonomous_live_entry_intent_service.py # Network-scoped intent authorization
|   |   |-- execution_authorization_service.py # PAPER human-approval boundary
|   |   |-- live_entry_risk_evaluation_service.py # Portfolio/balance decision
|   |   |-- live_executable_quote_service.py # Fresh quote provenance gate
|   |   |-- live_futures_entry_service.py # Protected Futures MARKET entry workflow
|   |   |-- order_service.py # Order submission and persistence
|   |   `-- trading_service.py
|   |-- market/
|   |   |-- candle_retention_service.py # Stored candle retention
|   |   |-- candle_sync_service.py # Bounded candle gap synchronization
|   |   |-- live_market_stream_service.py # Production LIVE stream ownership
|   |   |-- market_service.py # Exchange and persisted market data access
|   |   `-- stored_resampled_candle_provider.py # Stored candle replay input
|   |-- notification_message_formatter.py # Transport-neutral notification formatting contract
|   |-- paper/
|   |   |-- autonomous_paper_execution_service.py # Ranked PAPER execution
|   |   |-- human_confirmed_paper_execution_service.py # Approval orchestration
|   |   `-- paper_trading_service.py
|   |-- position/
|   |   |-- closed_position_lifecycle_service.py # Exact-order gross/fee/net enrichment
|   |   |-- live_position_lifecycle_coordinator.py # Per-symbol lifecycle serialization
|   |   |-- operator_exit_service.py # Guarded close and flatten orchestration
|   |   |-- position_exit_service.py # In-flight position exit orchestration
|   |   `-- position_service.py # Position sync and persistence
|   |-- protection/
|   |   |-- live_position_protection_service.py # Shared LIVE SL/TP reconciliation
|   |   |-- live_protection_monitoring_service.py # Production 0/1/N protection monitor owner
|   |   `-- position_protection_manager.py # Stream-driven stepped SL+
|   |-- recovery/
|   |   |-- autonomous_live_recovery_observability_service.py # Read-only recovery view
|   |   |-- live_natural_exit_recovery_service.py # Natural SL/TP fill detection and ledgering
|   |   |-- live_portfolio_recovery_service.py # LIVE portfolio safety recovery
|   |   |-- live_post_entry_recovery_service.py # ACKNOWLEDGED entry recovery core
|   |   |-- live_submission_recovery_service.py # GET-only incomplete entry recovery
|   |   `-- runtime_recovery_service.py # Restart recovery dan live protection gate
|   |-- runtime/
|   |   |-- health_service.py
|   |   |-- live_runtime_health_service.py # Derived recovered LIVE health aggregation
|   |   |-- live_runtime_portfolio_reconciliation_service.py # Canonical 0/1/N management reconciliation
|   |   |-- multi_context_activation.py # Immutable LIVE activation preconditions
|   |   |-- runtime_control_contract.py # Service-facing runtime safety contract
|   |   |-- runtime_reporter.py # Runtime status and portfolio reporting
|   |   `-- runtime_risk_limit_service.py # Durable runtime canary-limit authority
|   `-- strategy_service.py
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
|   |-- base/
|   `-- price_action/          # PIER (Pinbar/Engulfing, EMA, RSI)
|-- telegram/
|   |-- access.py
|   |-- bot.py
|   |-- callback_routes/
|   |   |-- authorization.py # PAPER approval callback boundary
|   |   |-- callbacks.py # Callback routing and remaining configuration controls
|   |   |-- execution_policy.py # Guarded trading-mode switch callbacks
|   |   `-- operator_exit.py # Guarded portfolio-exit callbacks
|   |-- command_handlers/
|   |   |-- commands.py
|   |   |-- leverage_commands.py
|   |   |-- operator_exit_commands.py # Chat-bound portfolio exit controls
|   |   |-- risk_limit_commands.py # Runtime-limit controls
|   |   |-- strategy_flatten_switch.py # Flatten-and-strategy soft restart
|   |   `-- strategy_switch.py # Interactive strategy selection
|   |-- context.py
|   |-- handlers.py
|   |-- presentation/
|   |   |-- keyboards.py # Telegram reply and inline keyboard layouts
|   |   |-- messages.py # Telegram HTML message templates
|   |   |-- notification_message_formatter.py # Telegram HTML adapter
|   |   |-- operator_exit_progress.py # Real-time operator exit progress
|   |   `-- runtime_menu_refresh.py # Mode-aware home menu synchronization
|   `-- query_service.py
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

Modul hasil pengelompokan pada `app/cli`, `app/runtime`, `app/settings`,
`app/terminal`, subpackage `engine`, `services`, `models`, `enums`, dan
`repositories`, serta
`telegram/callback_routes`, `telegram/command_handlers`, dan
`telegram/presentation` adalah lokasi import kanonis. Modul penerus import
pada path datar lama telah dihapus, termasuk alias `app.connectivity` pada
v7.0.0;
pemanggil yang memakai import langsung
v4.x harus memperbarui path modulnya pada v5.0.0; pemanggil import langsung
model, enum, atau repository pada path datar v5.x harus memakai subpackage
domain kanonis pada v6.0.0. Ekspor simbol melalui `botragram.models`,
`botragram.enums`, dan `botragram.repositories` tetap tersedia.

`config`, `constants`, `exceptions`, dan `utils` sengaja tetap datar: ukuran
paket kecil, nama modul sudah menunjukkan domain, dan subfolder tambahan
tidak memperjelas batas dependensi. Versi yang ditampilkan runtime memakai
`APP_VERSION` dan diverifikasi terhadap `pyproject.toml` oleh tes.

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

`BacktestEngine` menerima `BacktestSessionFactory` abstrak dan tidak membangun
repository atau PAPER service secara langsung. `DependencyProvider` menyediakan
`create_backtest_engine(...)` untuk CLI, tes, dan script manual. Constructor
langsung `BacktestEngine(...)` sekarang mewajibkan `session_factory`; ini
perubahan API major dari v3.x.

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
