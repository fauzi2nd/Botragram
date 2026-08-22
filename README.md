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
while an approval remains pending. Both PAPER market-wide policies are rejected in
`TRADE_MODE=LIVE`.

## TESTNET autonomous LIVE entry

AUTONOMOUS LIVE = TESTNET ONLY. The explicit `autonomous_live` execution policy
is operational only with `TRADE_MODE=LIVE`,
`AUTONOMOUS_LIVE_ENTRY_ENABLED=true`, and an exchange TESTNET connection.
The existing deterministic discovery/ranking pipeline processes candidates
sequentially. Each candidate receives a current portfolio/balance/risk decision
before intent authorization and a fresh mutation-time validation at the protected
entry boundary. Successful entries remain PREPARED-before-POST, exactly-one-POST
reconciled, and must finish with verified STOP/TP protection. Unsafe mutation
outcomes stop later candidates; recovered positions participate in capacity and
risk. MAINNET autonomous LIVE remains rejected.

After the existing discovery, ranking, position, and risk gates have approved a
candidate, the pure authorization boundary may create a transient typed entry
intent. An explicit TESTNET-only adapter can consume that intent only after a
fresh authoritative account/portfolio risk evaluation, then delegates to the
existing protected-entry lifecycle. The decision-time quantity is never reused
as mutation-time authority. PREPARED-before-POST, one-POST reconciliation, and
verified protection remain mandatory. MAINNET remains rejected, PAPER remains
separate, and recovered-position management authorization cannot grant
permission for new LIVE exposure.

Protected Futures MARKET entries convert risk sizing into a venue-valid quantity
before durable `PREPARED` and before the first POST. Botragram reads
authoritative MARKET rules, rounds quantity **down** to the step grid, and
validates min/max quantity plus applicable minimum notional against a fresh
market reference price. Invalid venue quantity creates zero PREPARED records and
zero mutations; it never increases approved exposure. Phase 5C real TESTNET
acceptance completed in `v0.5.0`.

Futures STOP/TAKE_PROFIT triggers use the same authoritative PRICE_FILTER grid
for initial protection and stepped STOP replacement. Durable position trigger
prices are final venue values, and restart reconciliation requires exact trigger
matches through each durable client identity. A stepped candidate that rounds to
the existing trigger creates no identity, POST, or cancellation; invalid stepped
candidates leave the existing verified STOP untouched. Phase 5C recovery-state
and fresh TESTNET acceptance completed in `v0.5.0`.

### Autonomous TESTNET recovery policy

Recovery remains restart/operator-driven by default. Phase 5C.3C adds one
strictly bounded in-process recovery opportunity for TESTNET autonomous LIVE:
after a typed `SUBMISSION_BLOCKED` or `EXECUTION_UNSAFE` result, the runner pauses,
marks protection readiness false, and may invoke the existing
`RuntimeRecoveryService` once per runner lifecycle. The failed candidate is never
replayed. Recovery uses the same durable submission/protection identities and
existing read-first reconciliation boundaries; there is no generic entry,
protection, or delete mutation retry. Only a complete recovery that actively
resumes runtime readiness may continue only after the normal global cadence,
so the failed cycle is not immediately rediscovered. A failed recovery or any
later unsafe result exhausts the in-process budget and requires restart/operator
recovery.

Startup always runs in this order before autonomous discovery is eligible:

```text
STARTING -> RECOVERING -> submission reconciliation -> acknowledged-entry recovery
         -> authoritative portfolio/protection recovery -> runtime readiness
         -> READY -> AUTONOMOUS_RUNNING

any unsafe/incomplete result -> UNSAFE_PAUSED -> restart/operator recovery
```

`AutonomousLiveEntryAuthorization` authorizes only creation of new TESTNET
exposure. It is not required to reconcile an existing submission or protect an
existing exchange position. Therefore, if an operator disables autonomous entry
after a crash, LIVE recovery still runs, but no new autonomous discovery cycle
is activated. MAINNET autonomous entry remains rejected.

| Durable state or condition | Authoritative recovery action | New POST allowed? | Autonomous entry / runner |
| --- | --- | --- | --- |
| No positions, no incomplete attempt | Full portfolio read is clean | Yes, only with current TESTNET capability | Global cycle may start |
| `PREPARED` or `UNRESOLVED` | GET by durable `client_order_id` only | No | Blocked until ACKNOWLEDGED or terminal rejection |
| `ACKNOWLEDGED` | Authoritative position read, persistence, protection verification, then `COMPLETED` | No | Blocked until complete |
| `REJECTED` | Terminal; no exposure recovery is required | A later, newly discovered candidate only | Normal fresh discovery may continue |
| `COMPLETED` with verified protection | Authoritative portfolio recovery confirms state | A later, newly discovered candidate only | Eligible only after all recovery/readiness gates pass |
| Multiple incomplete attempts | Do not guess or select one | No | Paused; operator/recovery intervention required |
| Unknown portfolio metadata or failed protection | Fail closed | No | Paused |
| Failed/missing stream or unhealthy/missing monitor | Fresh entry is blocked; existing exact runtime recovery may run once | No generic retry | One shared bounded in-process recovery pass, then fail closed |
| Reconciliation marker or authorization mismatch | Do not infer or repair from health text | No | Paused; restart/operator recovery required |

Crash-window policy is likewise read-first and fail-closed:

| Crash boundary | Durable/exchange source after restart | Safe operation |
| --- | --- | --- |
| Before `PREPARED` | No durable attempt | Fresh discovery only; no replay |
| After `PREPARED`, before POST | SubmissionAttempt + GET by client identity | Never POST again solely because it is not found |
| During POST / unknown transport outcome | `UNRESOLVED` + authoritative GET | Adopt FILLED, reject terminal state, otherwise remain blocked |
| FILLED before `ACKNOWLEDGED` persistence | Durable attempt + authoritative GET | Mark the same attempt ACKNOWLEDGED, then post-entry recovery |
| `ACKNOWLEDGED` before Position persistence | Authoritative position | Persist factual position and verify protection |
| Position persistence before protection | Position plus durable protection identities | Reconcile/verify STOP and TP before completion |
| STOP before TP | Distinct durable leg identities + GET | Reconcile sequentially; never blind-repost a missing identity |
| Protection exists before `COMPLETED` | Position/protection verification | Persist `COMPLETED` only after verification |
| `COMPLETED` | Durable attempt plus authoritative portfolio | Normal recovery; no duplicate entry/protection mutation |

Autonomous intents and candidate batches are transient process-local values. They
are neither persisted nor replayed after a crash, unsafe result, or restart.
After safe recovery the system performs a fresh discovery pass rather than
replaying process-local values.

For autonomous LIVE only, every ranked actionable closed-candle candidate is
atomically claimed in durable SQLite state before its first risk evaluation.
The claim identity is `(symbol, interval, strategy_name, signal_generated_at)`;
direction, price, and confidence are deliberately not part of the identity.
Rediscovery of an existing claim produces a safe no-entry result before risk,
intent, or exchange execution. A later candle or a different interval remains a
new opportunity. The claim is a replay-denial record only: it grants no entry
authorization, does not weaken fresh portfolio/risk checks, and is not used by
PAPER workflows. This boundary intentionally prefers losing an opportunity after
a crash over submitting a second entry attempt from the same closed candle.

Autonomous LIVE discovery additionally binds each candidate to the executor's
explicit strategy context before the durable claim. Every strategy candle must
match the scanned symbol and requested interval, keep `open_time` strictly before
`close_time`, and preserve strictly increasing `open_time` and `close_time`
identities across the closed-candle sequence. Its OHLC prices must be finite and
positive, `low_price` must not exceed `high_price`, and both `open_price` and
`close_price` must remain within that low/high range. The generated signal must
keep the scanned symbol, use the exact explicit strategy name, set `price` to the
latest closed candle's `close_price`, and set `generated_at` to that candle's
`close_time` after UTC normalization. Explicit-strategy discovery generates the
signal first, validates all provenance, and only then persists it; a provenance
mismatch leaves no invalid signal record behind and still fails before durable
claim, risk evaluation, intent authorization, or exchange execution. Existing
non-LIVE discovery continues to use the legacy generate-and-persist path.

Current health views describe recovered runtime/stream/monitor state and the
read-only typed autonomous-recovery lifecycle. Health text is never an
authorization source. For TESTNET autonomous LIVE, a DEGRADED recovered runtime
with the exact current management authorization may only deny a fresh cycle and
trigger the existing bounded recovery boundary; it never grants entry
permission. Missing or mismatched authorization cannot be masked by a concurrent
stream/monitor degradation. BLOCKED reconciliation or authorization state
remains restart/operator-only and cannot consume an automatic recovery pass.

Operator status now additionally exposes a read-only durable autonomous recovery
snapshot. `PREPARED`, `UNRESOLVED`, `ACKNOWLEDGED`, and multiple incomplete
attempts are distinct; recovery remains visible when autonomous entry is
disabled. Rendering status performs no reconciliation, exchange I/O, mutation,
or authorization change. Recovery remains restart/operator-driven.

### TESTNET failure-injection and soak readiness

Phase 5C.4A adds deterministic automated coverage for the protected-entry
failure boundaries alongside the existing submission, post-entry, protection,
runtime-recovery, runner, configuration, and PAPER regressions. It does not add
automatic recovery. The operational policy remains fail closed, inspect the
typed status, then use restart/operator-driven recovery followed by fresh
discovery. Transient intents and candidate batches remain process-local and are
never replayed after a crash.

Before any extended TESTNET soak, an operator must verify all of the following:

- TESTNET credentials, `BINANCE_TESTNET=true`, and small TESTNET sizing are in use.
- Autonomous cycles do not overlap and entry mutation concurrency remains one.
- Each filled entry has exchange-verified STOP and TAKE_PROFIT protection with
  distinct durable client identities.
- Incomplete attempts visibly block new entries; a restart reconciles them
  without a duplicate entry POST or identity.
- Portfolio capacity reflects each recovered or newly filled position, and
  Telegram/terminal recovery status remains truthful.
- A graceful shutdown leaves verified exchange protection intact and no
  process-local stream, monitor, or runner task remains active.
- MAINNET autonomous configuration is rejected before mutation.

Bounded in-process autonomous recovery is enabled only for the TESTNET
autonomous-LIVE runner and is limited to one existing runtime-recovery pass per
runner lifecycle. The single budget is shared by typed unsafe entry outcomes and
DEGRADED stream/monitor health. Runtime health is checked before a fresh global
cycle and while waiting for the next cadence, so degraded ownership cannot start
another cycle first. A failed protection-monitor owner is quarantined locally
until runtime recovery replaces it; subsequent ticks cannot re-enter that
manager. It does not replay transient intents or candidate batches,
and it does not introduce generic mutation retries. BLOCKED reconciliation or
authorization health never self-heals. If safe runtime readiness cannot be
re-established, the runner remains fail closed for operator/restart recovery.

### Dedicated autonomous TESTNET soak profile

The normal `.env` remains the safe default. To prepare a real TESTNET soak,
copy `.env.autonomous_testnet_soak.example` to
`.env.autonomous_testnet_soak`, and copy
`.env.autonomous_testnet_soak.testnet.example` to
`.env.autonomous_testnet_soak.testnet`. Fill only the latter with Binance
**TESTNET** credentials; empty credentials intentionally make LIVE validation
fail. Never substitute MAINNET credentials.

Select the dedicated base file explicitly before starting a preflight or the
later soak:

```powershell
$env:BOTRAGRAM_ENV_FILE = '.env.autonomous_testnet_soak'
python -c "from botragram.app.settings_manager import SettingsManager; s = SettingsManager().load(); print(s.app.trade_mode.value, s.exchange.market_type.value, s.exchange.environment.value, s.app.effective_execution_policy.value, s.app.autonomous_live_entry_enabled)"
```

The expected output is `live futures testnet autonomous_live True`. The template
uses the existing conservative `MAX_POSITION_SIZE_USDT=10` and
`MAX_OPEN_POSITIONS=1` risk controls. Only after this preflight succeeds should
the separate Phase 5C acceptance soak start.

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

Pada mode `LIVE`, entry terlindungi saat ini hanya mendukung Binance Futures
`MARKET`. Entry baru tidak dianggap berhasil sampai posisi aktual tersinkron,
metadata tersimpan, dan order `STOP_MARKET` serta `TAKE_PROFIT_MARKET`
reduce-only terverifikasi dari exchange. `LIMIT` LIVE ditolak sampai lifecycle
fill asinkron dapat ditangani dengan aman. Saat startup, Botragram mengevaluasi
seluruh portofolio posisi LIVE yang authoritative dari exchange. Setiap posisi
dengan metadata lokal yang cukup disimpan kembali dan diverifikasi proteksinya
secara independen; metadata yang tidak dapat dipastikan membuat recovery gagal
tertutup. Portofolio dengan beberapa posisi dapat dikenali aman. Runtime hanya
mengaktifkan management multi-position setelah seluruh context, stream, monitor,
dan authorization exact dibangun kembali dari state authoritative/durable.
`LiveMarketStreamService` adalah pemilik lifecycle task/subscription stream
produksi; Telegram hanya mendelegasikan operasi kompatibilitas singular kepadanya.
Untuk `MULTIPLE_POSITIONS_SAFE`, startup membuka dan memverifikasi tick pertama
untuk setiap runtime context secara berurutan. Setelah seluruh stream siap,
`LiveProtectionMonitoringService` mendaftarkan satu
`PositionProtectionManager` independen per context dan merutekan tick berdasarkan
symbol. Kegagalan parsial membersihkan hanya monitor dan stream milik attempt,
tanpa membatalkan proteksi exchange yang durable. Recovery berikutnya lebih dahulu
membersihkan ownership process-local sebelumnya, lalu membangun ulang seluruh
portfolio; tidak ada fallback ke subset posisi yang masih sehat. Streaming bersamaan
untuk symbol yang sama dengan interval berbeda belum didukung karena API
`MarketService` masih dialamatkan berdasarkan symbol; autonomous LIVE hanya
diizinkan pada TESTNET dengan opt-in eksplisit.
`TradingRuntimeControl` dapat menyimpan nol, satu, atau beberapa runtime context
LIVE yang immutable. Penggantian seluruh context portfolio bersifat atomik dan
memvalidasi duplicate symbol terlebih dahulu; urutan dipertahankan untuk
reproducibility, bukan prioritas. Accessor singular `symbol`, `interval`, dan
`strategy_type` hanya valid untuk tepat satu context dan gagal eksplisit untuk
beberapa context. `NO_POSITIONS`, `UNSAFE`, perubahan bentuk portfolio, atau
degradasi stream/monitor menghapus state runtime serta authorization dan
mem-pause runtime.
`TradingRunner` memiliki satu lifecycle global yang dapat mengambil snapshot
context immutable dan menjalankan batch secara sequential. Setiap context memakai
cadence intervalnya sendiri; perubahan context diterapkan pada batas batch
berikutnya. Prasyarat aktivasi multi-context (portfolio, stream, monitor,
management authorization, dan lifecycle) dievaluasi eksplisit tanpa memilih
primary symbol. Management authorization hanya mengizinkan evaluasi context
posisi yang sudah dipulihkan; ia tidak pernah mengizinkan pembuatan exposure LIVE
baru. Jika posisi recovered menghilang, entry baru ditolak dan rekonsiliasi
portfolio diperlukan. Portfolio/risk tetap terserialisasi. Untuk portofolio LIVE
yang dipulihkan dengan
beberapa posisi, management cycle produksi sekarang aktif hanya setelah context,
stream, monitor, dan authorization exact diverifikasi; satu `TradingRunner`
menjalankan context secara sequential. Authorization dihapus dan runtime dipause
jika portfolio, stream, atau monitor menjadi stale. Ini tetap tidak mengizinkan
entry LIVE baru selain workflow autonomous TESTNET yang eksplisit.
`LiveRuntimeHealthService` menyediakan snapshot operational immutable dan read-only
yang merangkum context, authorization, stream, serta monitor. Kegagalan stream,
monitor, atau kebutuhan rekonsiliasi menyebut context yang terdampak dan menilai
seluruh portfolio secara atomik; snapshot ini tidak pernah mengotorisasi eksekusi.
Cycle context dapat memilih strategi secara eksplisit dari `strategy_type` melalui
registry strategy immutable; tidak ada lagi pergantian mutable satu strategy global
antar context. Default konfigurasi tetap hanya untuk workflow non-context.
Shutdown application menghentikan runner sebelum menghapus authorization/runtime
state, lalu menghapus ownership monitor dan menghentikan stream; proteksi exchange
yang durable tidak dibatalkan. Reset runtime menghapus seluruh context dan
telemetry stream singular.
Telegram dan terminal hanya menampilkan health portfolio LIVE secara read-only;
Telegram tidak menyediakan kontrol interaktif multi-symbol. Autonomous LIVE
entry hanya tersedia pada FUTURES TESTNET dengan capability eksplisit; MAINNET
tetap ditolak.
Jika sinkronisasi, pemasangan proteksi, verifikasi, atau tick pertama gagal, bot
tetap paused dan terminal mencatat penyebabnya. Perilaku ini bukan pengganti
pemantauan account dan order secara independen pada exchange.

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
