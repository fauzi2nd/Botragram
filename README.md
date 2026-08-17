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

## Market-wide PAPER discovery

Market-wide execution is disabled by default. The legacy
`AUTONOMOUS_EXECUTION_ENABLED=true` setting still enables autonomous PAPER
execution. New deployments should select an explicit `EXECUTION_POLICY`.

For autonomous PAPER execution, use Binance Futures for the perpetual market
universe:

```dotenv
TRADE_MODE=PAPER
EXECUTION_POLICY=autonomous_paper
BINANCE_MARKET_TYPE=FUTURES
```

The runtime discovers a bounded set of active USDT perpetual symbols, ranks
actionable strategy signals, then attempts candidates sequentially through the
PAPER simulation. It never submits an exchange order.

For human-confirmed PAPER opportunities, set:

```dotenv
TRADE_MODE=PAPER
EXECUTION_POLICY=human_confirmed_paper
BINANCE_MARKET_TYPE=FUTURES
```

This mode discovers and ranks candidates, creates bounded pending approvals,
and sends them to the Telegram allow-list. It performs no PAPER execution until
an allowed user presses Approve; final portfolio validation still occurs at
approval time. Equivalent symbol/direction/strategy candidates are suppressed
while an approval remains pending. Both market-wide policies are rejected in
`TRADE_MODE=LIVE`.

## Backtest

Backtest berjalan terpisah dari runtime Telegram dan memakai candle publik
Binance Mainnet. Perintah ini tidak membaca posisi runtime, tidak menyalakan
WebSocket, dan tidak mengirim order. Contoh:

```powershell
python main.py backtest --market-type futures --symbol BTCUSDT `
  --interval 1m --strategy ema_scalping `
  --start 2025-01-01 --end 2025-01-07 --balance 100
```

Tanggal tanpa jam ditafsirkan sebagai rentang hari inklusif dalam UTC. Candle
diproses satu per satu tanpa melihat candle berikutnya. Jika satu candle
menyentuh SL dan TP sekaligus, backtest memakai asumsi konservatif: SL diproses
lebih dahulu. Fee, slippage, sizing, leverage, serta baseline SL/TP memakai
konfigurasi PAPER yang sama; notional dibatasi oleh saldo backtest. Stepped SL+
belum disimulasikan dan ditampilkan sebagai warning pada report.

Report terminal menampilkan saldo awal/akhir, net PnL, return, drawdown, fee,
jumlah long/short, win rate, profit factor, dan maksimal 50 trade terakhir.
Gunakan `python main.py backtest --help` untuk daftar pilihan lengkap.

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
and Futures. Enable the required Binance API permissions for both products
before switching them during live operation.

Trading selalu dimulai dalam state `CONFIGURING`. Melalui Telegram, konfirmasikan
exchange aktif lalu pilih product Spot/Futures, market USDT, candle interval, dan
strategy. Nilai awal dari `.env` hanya menjadi default dan tidak ditandai sudah
dipilih. Setelah itu aktifkan Stream dan tunggu tick pertama sebelum menekan
`Start Bot`. Perubahan
runtime hanya diterima saat trading paused, stream berhenti, dan tidak ada posisi
terbuka. Exchange yang ditampilkan Telegram adalah connector yang sudah dimuat
oleh environment profile; menggantinya memerlukan profile lain dan restart.
Reply keyboard Telegram memakai navigasi bertingkat agar tidak memenuhi layar:
menu Home hanya berisi Dashboard, Trading, Configuration, dan Activity. Setiap
submenu memiliki maksimal empat baris serta tombol Home. Dashboard Status
merangkum runtime, exchange product, strategy, interval, stream, balance, posisi,
dan unrealized PnL dalam satu control center.
Sebelum konfigurasi lengkap, Status menampilkan progres setup ringkas dan
`WAITING`, bukan deretan nilai default internal dari `.env`.

Produk Binance Spot/Futures dapat dipilih dari menu Exchange tanpa mengubah
`.env`. Pergantian hanya diterima ketika trading paused, cycle tidak berjalan,
stream mati, dan tidak ada posisi aktif. Botragram kemudian menutup connector
lama dan melakukan soft restart internal menggunakan profile serta credential
yang sama. `BINANCE_MARKET_TYPE` tetap menjadi pilihan awal saat proses pertama
kali dijalankan.

Dashboard menyediakan `Market Overview` khusus monitoring tanpa tombol pemilihan.
Pemilihan symbol hanya tersedia melalui `Configuration -> Select Market`.
Selector tersebut mengambil simbol aktif langsung dari metadata exchange dan menyimpan
hasilnya selama lima menit. Binance Spot menampilkan pair berstatus `TRADING`
dengan quote asset runtime (default `USDT`); Binance Futures juga membatasi hasil
ke kontrak perpetual. Simbol ditampilkan 10 per halaman agar menu tetap ringkas.
Tombol Search pada menu Market menerima kode koin atau symbol seperti `BTC`,
`ETH`, atau `SOLUSDT`, lalu menampilkan maksimal 10 hasil exchange yang dapat
dipilih langsung.

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
dan log. Dashboard membaca balance, posisi, realized/unrealized PnL, serta
telemetry tick lokal tanpa menambahkan polling harga per refresh. Tick WebSocket
tetap diproses event-driven;
refresh tampilan 4 kali per detik hanya mengatur kecepatan visual. Rotating log
tetap menyimpan riwayat diagnostik lengkap secara terpisah.
