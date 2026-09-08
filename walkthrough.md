# Walkthrough: Opsi 1 (Automated Candle Retention) & Opsi 4 (Telegram Performance Card)

Implementasi dan verifikasi menyeluruh untuk **Opsi 1** (*Automated Database Candle Retention & Pruning*) dan **Opsi 4** (*Telegram Performance Card & Enhanced Trade Summary*).

---

## 1. Opsi 1: Automated Candle Retention & Database Pruning

### Tujuan
Mencegah SQLite database membengkak hingga jutaan candlestick akibat migrasi coin-coin dan discovery universe, dengan membersihkan candle lama secara berkala di background dan mengoptimasi storage SQLite.

### Perubahan Kode
1. **Konfigurasi Lingkungan & Settings:**
   - [`botragram/constants/env.py`](file:///c:/Zero/Botragram/botragram/constants/env.py):
     - `ENV_CANDLE_RETENTION_DAYS = "CANDLE_RETENTION_DAYS"` (default: 7 hari)
     - `ENV_CANDLE_PRUNING_INTERVAL_HOURS = "CANDLE_PRUNING_INTERVAL_HOURS"` (default: 6 jam)
   - [`botragram/config/market_settings.py`](file:///c:/Zero/Botragram/botragram/config/market_settings.py):
     - Menambahkan field `candle_retention_days: int = 7` dan `candle_pruning_interval_hours: int = 6` beserta validasi integer positif.
   - [`botragram/app/environment_provider.py`](file:///c:/Zero/Botragram/botragram/app/environment_provider.py) & [`botragram/app/settings_manager.py`](file:///c:/Zero/Botragram/botragram/app/settings_manager.py):
     - Parsing and fallback handling saat memuat konfigurasi market.
   - [`.env.example`](file:///c:/Zero/Botragram/.env.example):
     - Dokumentasi lengkap untuk opsi pruning & retention database.

2. **Background Retention Service:**
   - [`botragram/services/candle_retention_service.py`](file:///c:/Zero/Botragram/botragram/services/candle_retention_service.py):
     - `CandleRetentionService`:
       - `prune_expired_candles()`: Menghitung timestamp cutoff UTC (`now - retention_days`), memanggil `candle_repository.delete_older_than(cutoff)` dan menjalankan `PRAGMA optimize` bila ada candle yang terhapus.
       - `is_running`: Property status liveness worker.
       - `start()` & `stop()`: Background worker cancellation-safe dengan initial delay 60s agar tidak bertabrakan dengan transaksi startup database.
   - [`botragram/app/dependency_provider.py`](file:///c:/Zero/Botragram/botragram/app/dependency_provider.py):
     - Injeksi `CandleRetentionService` ke lifecycle app (start di `initialize()`, clean shutdown di ladder `close()`).

---

## 2. Opsi 4: Telegram Performance Card & Enhanced Trade Summary

### Tujuan
Memberikan ringkasan performa trading real-time melalui bot Telegram:
- Notifikasi trade selesai yang menyertakan durasi trade (misal `1h 23m 45s`) dan ROI % (misal `+9.98%`).
- Command Telegram `/performance` dan `/daily` beserta inline button `📊 Performance` pada Dashboard Status & Activity Menu.

### Perubahan Kode
1. **Template & Formatter Pesan:**
   - [`botragram/telegram/messages.py`](file:///c:/Zero/Botragram/botragram/telegram/messages.py):
     - `get_trade_completed_message()`: Ditingkatkan untuk menghitung durasi posisi (`lifecycle.closed_at - entry_time`) dan kalkulasi Return on Investment (`lifecycle.net_pnl / entry_cost * 100`).
     - `get_performance_card_message()`: Template Telegram executive card menampilkan Net Realized PnL, Win Rate %, Total Closed Trades, Wins 🟢, Losses 🔴, dan Break-Even ⚪.

2. **Telegram Query & Context Protocol:**
   - [`botragram/telegram/context.py`](file:///c:/Zero/Botragram/botragram/telegram/context.py):
     - Menambahkan `get_trading_performance()` ke protocol `BotQueryProvider`.
   - [`botragram/telegram/query_service.py`](file:///c:/Zero/Botragram/botragram/telegram/query_service.py):
     - Menambahkan protocol `LiveTradingPerformanceProvider` dan menghubungkannya dengan `LiveTradingPerformanceService` dari composition root.
   - [`botragram/app/dependency_provider.py`](file:///c:/Zero/Botragram/botragram/app/dependency_provider.py):
     - Menyediakan `live_trading_performance_service` ke `TelegramQueryService`.

3. **Commands, Handlers, Callbacks, & Keyboards:**
   - [`botragram/telegram/commands.py`](file:///c:/Zero/Botragram/botragram/telegram/commands.py):
     - Menambahkan handler `performance_command()`.
     - Mendukung command `/performance` dan `/daily`.
     - Menangani tapping button `"📊 Performance"` pada persistent reply keyboard.
   - [`botragram/telegram/handlers.py`](file:///c:/Zero/Botragram/botragram/telegram/handlers.py):
     - Mendaftarkan `CommandHandler("performance", performance_command)` dan `CommandHandler("daily", performance_command)`.
   - [`botragram/telegram/callbacks.py`](file:///c:/Zero/Botragram/botragram/telegram/callbacks.py):
     - Menangani callback inline button `"cb_performance"`.
   - [`botragram/telegram/keyboards.py`](file:///c:/Zero/Botragram/botragram/telegram/keyboards.py):
     - Menambahkan tombol `📊 Performance` pada inline Status Dashboard (`row5`) dan Activity Menu.

---

## 3. Hasil Validasi (Quality Gates)

Semua quality gates dijalankan sesuai standar proyek tanpa error:

1. **Compile Check:**
   ```powershell
   python -m compileall -q botragram tests
   # Result: 0 errors
   ```

2. **Code Formatting (Ruff):**
   ```powershell
   python -m ruff format --check .
   # Result: 468 files already formatted
   ```

3. **Linting (Ruff):**
   ```powershell
   python -m ruff check .
   # Result: All checks passed!
   ```

4. **Strict Type Checking (Pyright):**
   ```powershell
   python -m pyright
   # Result: 0 errors, 0 warnings, 0 informations
   ```

5. **Unit & Integration Test Suite (Pytest):**
   ```powershell
   python -m pytest
   # Result: 1223 passed in 31.02s
   ```
