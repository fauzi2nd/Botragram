# Botragram

Botragram adalah sistem trading algoritmik otomatis berbasis Python (3.14+) dengan arsitektur async-first, dirancang khusus untuk pasar cryptocurrency (**Binance USD(S)-M Futures & Spot** serta **Bybit Linear Perpetual Futures & Spot**). Sistem ini menggabungkan *autonomous market-wide discovery*, multi-strategi (*Smart Money Concepts, Candlestick Price Action, Scalping, Trend Following, Swing*), *stepped profit protection (SL+)* dinamis, *fail-closed recovery* tahan crash, antarmuka terminal *Rich* responsif dengan kalkulasi ROI *real-time*, serta kendali jarak jauh melalui Telegram Bot yang interaktif dan aman.

---

## Daftar Isi
1. [Fitur Utama](#fitur-utama)
2. [Arsitektur & Dependency Direction](#arsitektur--dependency-direction)
3. [Daftar Strategi & Risk-Reward Ratio (RRR)](#daftar-strategi--risk-reward-ratio-rrr)
4. [Instalasi & Quick Start](#instalasi--quick-start)
5. [Konfigurasi Environment (.env)](#konfigurasi-environment-env)
6. [Mode Eksekusi (Execution Policies)](#mode-eksekusi-execution-policies)
7. [Persistent Runtime Settings & Crash Recovery](#persistent-runtime-settings--crash-recovery)
8. [Operator Exit & Pengendalian Posisi](#operator-exit--pengendalian-posisi)
9. [Terminal Monitor & Telegram Integration](#terminal-monitor--telegram-integration)
10. [Backtesting Engine](#backtesting-engine)
11. [Quality Gates & Standar Kode](#quality-gates--standar-kode)

---

## Fitur Utama

- 🛡️ **Capital Safety & Risk First**: Manajemen risiko berbasis stop-loss distance, validasi ukuran lot exchange, batasan drawdown akun, dan pencegahan submission ganda (idempotency).
- 🌐 **Multi-Exchange Support**: Mendukung **Binance** (Spot & USD(S)-M Futures) dan **Bybit** (Spot, Linear USDT Perpetual Futures, Demo Trading `api-demo.bybit.com`, Testnet, dan Mainnet).
- 🧠 **Smart Money Concepts & 16 Multi-Strategy Engine**: Dilengkapi 16 strategi bawaan mulai dari Smart Money Concepts (CHoCH + FVG), Candlestick Price Action (Pinbar & Engulfing + EMA/RSI), Confluence Multi-Indikator, Scalping, Trend Following, hingga Swing Trading.
- ⚡ **Autonomous Market-Wide Discovery**: Memindai dan meranking seluruh universe koin USDT perpetual aktif berdasarkan volume 24 jam dengan rotasi batch bertahap, filter likuiditas/ekstrem volatilitas, serta batas plafon (`DISCOVERY_MAX_UNIVERSE_SYMBOLS`).
- 🔄 **Stepped Trailing Profit Protection (SL+)**: Mengunci profit bertahap (30% → 90% progress target) secara otomatis via real-time WebSocket market stream.
- 📊 **Real-Time ROI & Responsive Terminal**: Dashboard terminal interaktif (Rich) dengan kalkulasi persentase ROI presisi terhadap margin, mendukung tampilan compact/portrait.
- 📱 **Telegram Control Plane**: Navigasi menu modern, notifikasi instan eksekusi & trailing SL, penggantian strategi dinamis, pengaturan risk limit, dan operator close position.
- 💾 **Persistent Runtime State**: Pilihan strategi dan konfigurasi runtime tersimpan permanen di SQLite sehingga tidak hilang saat restart atau crash.
- 🛑 **Instant Operator Exit**: Tutup posisi kapan saja secara langsung tanpa perlu jeda manual (*auto-pause gating*).

---

## Arsitektur & Dependency Direction

Botragram menerapkan pemisahan tanggung jawab yang ketat dan searah (*unidirectional dependency flow*):

```text
main.py (Composition Bootstrap)
  └── botragram.app (Composition Root & Lifecycle)
      ├── config / constants / enums / models (Domain Core - Immutable)
      ├── storage (SQLite / Memory) ──> repositories (Interfaces)
      ├── exchanges (Binance & Bybit REST/Stream) ──> exchange abstractions
      ├── indicators & strategies (Pure Math & Signal Generation)
      ├── engine (Decision & Calculation Logic)
      └── services (Use-case Orchestration & Async I/O)
```

- **Domain Core**: Menggunakan `@dataclass(slots=True, frozen=True)` dan `Decimal` untuk semua nilai finansial (uang, harga, lot, PnL, fee).
- **Services vs Engines**: Engine murni deterministik tanpa network I/O; Service mengorkestrasi I/O, database, dan exchange.
- **Fail-Closed Principle**: Tidak ada fallback atau state buatan saat terjadi ambiguitas jaringan.

---

## Daftar Strategi & Risk-Reward Ratio (RRR)

Botragram mendukung 16 strategi trading yang secara otomatis menerapkan Timeframe optimal dan profil *Risk-Reward Ratio* (SL/TP):

| Kategori | Strategi (`STRATEGY_TYPE`) | Auto Timeframe | Default SL / TP | Rasio RRR | Deskripsi & Indikator |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Price Action** | `choch_fvg` *(Rekomendasi)* | **15m** | **1.0% / 2.5%** | **1 : 2.5** | **Smart Money Concepts**: Change of Character (CHoCH), Liquidity Sweep, Displacement Candle, dan FVG Imbalance Retest. |
| **Price Action** | `pinbar_engulfing_ema_rsi` | **15m** | **1.0% / 2.5%** | **1 : 2.5** | **Price Action Confluence**: Pinbar (Hammer/Star) & Engulfing pada EMA 21 Pullback, EMA 200 Trend Filter, dan RSI Momentum. |
| **Price Action** | `choch_rsi_bb_hybrid` | **15m** | **1.0% / 2.5%** | **1 : 2.5** | **SMC + Mean Reversion**: CHoCH structural breakout terkonfirmasi RSI oversold/overbought dan Bollinger Bands boundary bounce. |
| **Price Action** | `liquidity_sweep_exhaustion` | **15m** | **1.0% / 2.5%** | **1 : 2.5** | **Liquidity Grab**: Sweep swing high/low palsu diikuti penolakan cepat (exhaustion wick), volume spike, dan ATR risk levels. |
| **Price Action** | `high_confluence_exhaustion` | **15m** | **1.0% / 2.5%** | **1 : 2.5** | **Exhaustion Mean Reversion**: Konvergensi ekstrem Bollinger Bands, RSI threshold, low ADX trendiness, dan volume spike. |
| **Scalping** | `rsi_bb_scalping` | **5m** | **0.5% / 1.0%** | **1 : 2.0** | Mean reversion oversold/overbought pada Bollinger Bands & RSI. |
| **Scalping** | `ema_scalping` | **5m** | **0.5% / 1.0%** | **1 : 2.0** | Fast EMA momentum scalping dengan konfirmasi body ratio candle dan dynamic ATR. |
| **Scalping** | `vwap_breakout` | **5m** | **0.5% / 1.0%** | **1 : 2.0** | Breakout intraday di atas/bawah Volume Weighted Average Price (VWAP). |
| **Trend Following** | `ema_cross` | **15m** | **1.5% / 3.0%** | **1 : 2.0** | Perpotongan garis Fast EMA dan Slow EMA (Trend Golden/Death Cross). |
| **Trend Following** | `ema_rsi` | **15m** | **1.5% / 3.0%** | **1 : 2.0** | Konfirmasi trend EMA dikombinasikan dengan momentum filter RSI. |
| **Trend Following** | `supertrend` | **15m** | **1.5% / 3.0%** | **1 : 2.0** | Indikator volatilitas Supertrend berbasis Average True Range (ATR). |
| **Trend Following** | `ichimoku_cloud` | **15m** | **1.5% / 3.0%** | **1 : 2.0** | Tenkan/Kijun cross terkonfirmasi Kumo Cloud & Chikou Span. |
| **Trend Following** | `adx_trend` | **15m** | **1.5% / 3.0%** | **1 : 2.0** | Filter kekuatan trend ADX dengan konfirmasi arah pergerakan DMI (+DI/-DI). |
| **Trend Following** | `bollinger_breakout`| **15m** | **1.5% / 3.0%** | **1 : 2.0** | Breakout volatilitas dari fase konsolidasi/squeeze Bollinger Bands. |
| **Trend Following** | `quad_confluence` | **15m** | **1.5% / 3.0%** | **1 : 2.0** | Konvergensi 4 indikator teknikal (Stochastic RSI, Bollinger Bands, Parabolic SAR, dan MACD). |
| **Swing Trading** | `macd_swing` | **1h** | **2.5% / 5.0%** | **1 : 2.0** | Swing trading multi-day berdasarkan MACD histogram & zero-line crossover. |

---

## Instalasi & Quick Start

### 1. Prasyarat Sistem
- **Python 3.14+** (atau 3.12+ dengan type hint modern).
- Akun Binance (Testnet atau Mainnet) dengan API Key & Secret (Futures Trading diaktifkan).
- Bot Telegram Token & Chat ID dari [@BotFather](https://t.me/botfather).

### 2. Setup Virtual Environment
```powershell
# Clone repositori
git clone https://github.com/fauzi2nd/Botragram.git
cd Botragram

# Buat virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependensi
pip install -r requirements.txt
```

### 3. Setup Konfigurasi
```powershell
# Buat file konfigurasi dari template
copy .env.example .env
copy .env.testnet.example .env.testnet
```

Edit file `.env` dan `.env.testnet` sesuai kredensial Anda.

### 4. Menjalankan Bot
```powershell
python main.py
```

---

## Konfigurasi Environment (.env)

Berikut contoh parameter utama pada `.env`:

```dotenv
# =============================================================================
# Botragram Environment Configuration
# =============================================================================

BOTRAGRAM_PROFILE=TESTNET         # Pilihan: TESTNET, MAINNET
ACTIVE_EXCHANGE=BINANCE           # Pilihan: BINANCE, BYBIT
BINANCE_MARKET_TYPE=FUTURES       # Pilihan: FUTURES, SPOT
BYBIT_MARKET_TYPE=FUTURES         # Pilihan: FUTURES (Linear USDT), SPOT
# BYBIT_DEMO=true                 # Aktifkan jika memakai Bybit Demo Trading (api-demo.bybit.com)

# Kredensial Telegram
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# Mode Eksekusi
TRADE_MODE=PAPER                  # Pilihan: PAPER, LIVE
EXECUTION_POLICY=autonomous_paper # Pilihan: single_symbol, autonomous_paper, human_confirmed_paper, autonomous_live
AUTONOMOUS_EXECUTION_ENABLED=true
AUTONOMOUS_LIVE_ENTRY_ENABLED=false
AUTONOMOUS_MAINNET_ENTRY_ENABLED=false

# Pilihan Strategi (Default: choch_fvg atau pinbar_engulfing_ema_rsi)
STRATEGY_TYPE=choch_fvg
LOG_LEVEL=INFO

# Parameter Risiko & Portofolio
MAX_OPEN_POSITIONS=1              # Jumlah maksimal posisi bersamaan
MAX_POSITION_SIZE_USDT=100        # Plafon maksimal ukuran posisi per trade
RISK_PER_TRADE_PCT=0.02           # Risiko saldo per trade (2%)
MAX_DRAWDOWN_PCT=0.10             # Batas toleransi drawdown akun (10%)
LEVERAGE=10                       # Leverage yang digunakan (Futures)

# Safeguard Kuotasi
MAX_EXECUTABLE_QUOTE_AGE_MS=1000  # Umur maksimal harga orderbook (1 detik)
MAX_SPREAD_BPS=20                 # Batas maksimal spread bid-ask (20 bps)

# Konfigurasi Autonomous Discovery
DISCOVERY_UNIVERSE_LIMIT=150      # Metrik batasan universe discovery
DISCOVERY_BATCH_SIZE=150          # Scanning batch per siklus candle
DISCOVERY_MAX_UNIVERSE_SYMBOLS=150 # Plafon maksimal universe (fokus koin top-volume)
DISCOVERY_CADENCE_SECONDS=        # Interval jeda scanning (opsional)
DISCOVERY_CANDLE_DELAY_SECONDS=0.05 # Pacing jeda antar fetch candle (rate limit safety)

# Parameter Khusus SMC / Price Action (choch_fvg)
# CHOCH_SWING_WINDOW=5            # Window bar swing high/low lookback (default: 5)
# CHOCH_FVG_LOOKBACK=20           # Window pencarian imbalance/FVG (default: 20)
# CHOCH_MIN_BODY_RATIO=0.50       # Minimal rasio body candle displacement (default: 0.50)
# CHOCH_VOLUME_MULTIPLIER=1.20    # Pengali volume candle displacement vs SMA (default: 1.20)
```

---

## Mode Eksekusi (Execution Policies)

Botragram menyediakan 4 kebijakan eksekusi:

1. **`single_symbol`**:
   - Fokus pada 1 aset tertentu (misal `BTCUSDT`).
   - Konfigurasi manual melalui Telegram menu (Exchange, Market, Strategy, Interval, Stream).
2. **`autonomous_paper`**:
   - Memindai seluruh pasar Futures USDT perpetual.
   - Sinyal terbaik dieksekusi secara otomatis dalam simulasi PAPER (tanpa risiko finansial).
3. **`human_confirmed_paper`**:
   - Memindai pasar, menemukan peluang, lalu mengirim tombol konfirmasi `[Approve]` / `[Reject]` ke Telegram.
4. **`autonomous_live`**:
   - Mode live trading riil di Binance Futures dengan proteksi ganda.
   - **Testnet**: Memerlukan `TRADE_MODE=LIVE` dan `AUTONOMOUS_LIVE_ENTRY_ENABLED=true`.
   - **Mainnet**: Memerlukan izin eksplisit tambahan `AUTONOMOUS_MAINNET_ENTRY_ENABLED=true` serta validasi kesiapan akun & simbol (*isolated margin, auto-add disabled, leverage limit*).

---

## Persistent Runtime Settings & Crash Recovery

Botragram dilengkapi arsitektur **Persistent Runtime Settings**:
- Ketika strategi diubah melalui Telegram (`/strategy` atau callback menu), pilihan baru disimpan ke tabel `runtime_settings` di database SQLite.
- Jika terjadi *unplanned shutdown*, mati lampu, atau crash PC, saat Botragram dinyalakan kembali:
  1. Strategi runtime yang terakhir dipilih akan dipulihkan secara otomatis.
  2. Posisi yang sedang terbuka (*legacy positions*) tetap diproteksi dengan SL/TP aslinya tanpa dipaksa tutup.
  3. Siklus pencarian entry baru akan langsung menggunakan strategi pilihan terbaru Anda.

---

## Operator Exit & Pengendalian Posisi

Anda dapat menutup posisi kapan saja secara instan melalui Telegram tanpa perlu mengklik Pause Bot manual:

1. **Melalui Menu Interaktif**:
   - Buka menu **`💼 Positions`** di Telegram (atau ketik `/positions`).
   - Klik tombol **`⚠️ Close <SYMBOL>`** atau **`⚠️ Close All Positions`**.
2. **Melalui Perintah Chat**:
   - `/closeposition BTCUSDT` — Menutup satu posisi tertentu.
   - `/closeall` — Menutup seluruh posisi aktif portofolio.
3. **Konfirmasi Instan**:
   - Bot otomatis menjeda trading cycle sementara (*auto-pause*).
   - Klik **`[ ✅ Confirm Exit ]`** (pada Paper/Testnet) atau ketik token konfirmasi (pada Mainnet).
   - Posisi langsung di-close di Binance dengan order `reduce_only=True` dan PnL riil dicatat ke ledger.

---

## Terminal Monitor & Telegram Integration

### Terminal Rich Monitor
Dashboard terminal interaktif menampilkan informasi:
- **Status Panel**: Runtime State, Execution Policy, Active Strategy, Timeframe, Account Balance, Total Equity, Drawdown %.
- **Managed LIVE Positions**: Simbol, Posisi (LONG/SHORT), Leverage, Quantity, Entry Price, Mark Price, SL/TP Level, UnPnL, dan **ROI %**.
- **Discovery Telemetry**: Window ranking aset, progress pemindaian batch, actionable candidate count.
- **Responsive Layout**: Menyesuaikan secara dinamis dengan ukuran jendela terminal (Landscape table vs Portrait compact).

### Telegram Bot Commands
- `/start` atau `/home` — Menampilkan menu kontrol utama.
- `/status` — Ringkasan status bot, koneksi exchange, saldo, dan posisi aktif.
- `/positions` — Menampilkan rincian posisi aktif lengkap dengan PnL & persentase ROI.
- `/strategy` — Mengganti strategi trading secara dinamis.
- `/limits` — Mengatur limit ukuran posisi dan kuota posisi (saat bot paused).
- `/mode` — Membuka menu pemilihan Trading Mode / Execution Policy.
- `/pause` & `/resume` — Menjeda atau melanjutkan trading runner.
- `/balance` & `/orders` & `/history` — Memeriksa saldo, order aktif, dan riwayat trade.

---

## Backtesting Engine

Engine backtesting berjalan terpisah dan memakai data candle historis publik Binance:

```powershell
# Contoh backtest strategi Price Action SMC (choch_fvg)
python main.py backtest --market-type futures --symbol BTCUSDT `
  --interval 5m --strategy choch_fvg `
  --start 2025-01-01 --end 2025-01-31 --balance 1000

# Contoh backtest strategi Scalping (rsi_bb_scalping)
python main.py backtest --market-type futures --symbol ETHUSDT `
  --interval 5m --strategy rsi_bb_scalping `
  --start 2025-01-01 --end 2025-01-14 --balance 500
```

Hasil laporan mencakup: Saldo Akhir, Total PnL, Win Rate %, Profit Factor, Max Drawdown %, Rasio Long/Short, Biaya Fee, dan daftar riwayat transaksi.

---

## Quality Gates & Standar Kode

Seluruh kode Botragram mematuhi standar keamanan trading dan *quality gate* ketat (1027+ test lulus 100%):

```powershell
# 1. Verifikasi bytecode kompilasi
python -m compileall -q botragram tests main.py

# 2. Verifikasi bootstrap import
python -c "import main"

# 3. Format & Linting (Ruff)
python -m ruff format --check .
python -m ruff check .

# 4. Strict Type Checking (Pyright & MyPy)
python -m pyright
python -m mypy botragram

# 5. Automated Unit & Integration Tests (Pytest)
python -m pytest
```

---

## Lisensi & Disclaimer

*Disclaimer*: Perdagangan aset kripto dan instrumen derivatif (Futures) mengandung risiko finansial tinggi. Botragram disediakan untuk tujuan riset, edukasi, dan otomatisasi berbasis aturan yang disiplin. Pengembang tidak bertanggung jawab atas keputusan finansial atau kerugian yang timbul akibat fluktuasi pasar. Gunakan selalu akun Testnet untuk pengujian sebelum mempertimbangkan penggunaan dana riil.
