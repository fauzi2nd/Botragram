# Botragram

Botragram is a Python-based trading bot project scaffolded from the development guide.

## Getting started

1. Create a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` for shared settings.
4. Copy `.env.testnet.example` to `.env.testnet` and configure test credentials.
5. Keep `BOTRAGRAM_PROFILE=TESTNET` while developing.
6. Select the Binance product with `BINANCE_MARKET_TYPE=SPOT` or
   `BINANCE_MARKET_TYPE=FUTURES`.
7. Run the application: `python main.py`.

Credential profiles are isolated:

- `BOTRAGRAM_PROFILE=TESTNET` loads `.env.testnet` and requires
  `BINANCE_TESTNET=true`.
- `BOTRAGRAM_PROFILE=MAINNET` loads `.env.mainnet` and requires
  `BINANCE_TESTNET=false`.
- Files `.env`, `.env.testnet`, and `.env.mainnet` are ignored by Git. Only the
  corresponding example templates may be committed.

When `.env` exists, its values take precedence over inherited terminal
variables. The selected profile file then overrides only its profile values.
This prevents stale PowerShell variables from silently changing the network or
Binance product. Without `.env`, regular process environment variables remain
available for deployment.

Copy `.env.mainnet.example` to `.env.mainnet` only when mainnet access is
needed. Selecting a profile whose file is missing or whose network flag does
not match fails during startup. A legacy `.env` without `BOTRAGRAM_PROFILE`
continues to work for backward compatibility.

Binance Futures means USD(S)-M perpetual Futures. Testnet is enabled by default;
keep `BINANCE_TESTNET=true` until the integration has been verified with your
strategy and account configuration. The Futures position-closing workflow
currently requires Binance one-way position mode.

The same `BINANCE_API_KEY` and `BINANCE_API_SECRET` pair is used for both Spot
and Futures. Enable the required Binance API permissions for the selected
product before using live trading.

Trading selalu dimulai dalam state `CONFIGURING`. Melalui Telegram, konfirmasikan
exchange aktif lalu pilih market USDT, candle interval, dan strategy. Setelah itu
aktifkan Stream dan tunggu tick pertama sebelum menekan `Start Bot`. Perubahan
runtime hanya diterima saat trading paused, stream berhenti, dan tidak ada posisi
terbuka. Exchange yang ditampilkan Telegram adalah connector yang sudah dimuat
oleh environment profile; menggantinya memerlukan profile lain dan restart.
Reply keyboard Telegram memakai navigasi bertingkat agar tidak memenuhi layar:
menu Home hanya berisi Dashboard, Trading, Configuration, dan Activity. Setiap
submenu memiliki maksimal empat baris serta tombol Home. Dashboard Status
merangkum runtime, exchange product, strategy, interval, stream, balance, posisi,
dan unrealized PnL dalam satu control center.
Cadence trading cycle mengikuti interval runtime terbaru: interval `1m` menunggu
60 detik setelah satu cycle selesai sebelum menjalankan cycle berikutnya.

Pengecualian berlaku ketika database menyimpan tepat satu posisi aktif. Pada
mode `PAPER`, startup memulihkan symbol, interval, dan strategy posisi, menyalakan
stream, menunggu tick pertama, lalu melanjutkan bot tanpa setup Telegram. Untuk
posisi lama dari schema sebelumnya, interval dan strategy direkonstruksi hanya
jika satu sinyal entry dan satu interval candle cocok secara pasti dengan waktu
posisi dibuka. Hasilnya disimpan untuk restart berikutnya; hasil yang ambigu
membuat bot tetap paused dan tidak memakai default profile secara diam-diam.

Pada mode `LIVE`, posisi selalu dibaca ulang dari exchange. Auto-resume hanya
berlaku untuk satu posisi Binance Futures dan tetap terkunci sampai order
`STOP_MARKET` serta `TAKE_PROFIT_MARKET` reduce-only terverifikasi. Proteksi yang
sudah ada dipakai kembali; leg yang hilang saja yang dibuat. Jika sinkronisasi,
pemasangan proteksi, atau tick pertama gagal, bot tetap paused dan terminal
mencatat penyebabnya. Perilaku ini bukan pengganti pemantauan account dan order
secara independen pada exchange.

Risk exit menggunakan profile strategy. Default global tetap SL `2%` dan TP
`4%`, sedangkan `ema_scalping` memakai baseline paper SL `0.5%` dan TP `1%`.
Nilai scalping dapat disetel melalui `EMA_SCALPING_STOP_LOSS_PCT` dan
`EMA_SCALPING_TAKE_PROFIT_PCT` di `.env`. Untuk paper fill, level dihitung dari
harga eksekusi setelah slippage agar angka risk, SL, dan TP konsisten.

Posisi dengan TP aktif memakai stepped profit protection dari market stream.
Progress dihitung dari pergerakan harga Entry→TP, bukan persentase UPnL yang
dipengaruhi leverage. Pada progress `50/60/70/80/90%`, SL mengunci masing-masing
`30/40/50/60/70%` dari jarak Entry→TP. Step disimpan di SQLite, SL tidak pernah
boleh bergerak mundur, dan update hanya dilakukan ketika threshold baru dilewati.
Pada PAPER, tick stream juga mengeksekusi SL/TP agar exit tidak menunggu trading
cycle candle berikutnya.
Pada LIVE Futures, stop pengganti harus terverifikasi aktif sebelum stop lama
yang cocok dibatalkan.

Terminal menggunakan dashboard Rich dengan panel status/portfolio, market stream,
dan log. Dashboard membaca balance, posisi, PnL, serta telemetry tick lokal tanpa
menambahkan polling harga per refresh. Tick WebSocket tetap diproses event-driven;
refresh tampilan 4 kali per detik hanya mengatur kecepatan visual. Rotating log
tetap menyimpan riwayat diagnostik lengkap secara terpisah.
