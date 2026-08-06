# Botragram Development Guide

Dokumen ini adalah standar wajib untuk pengembangan Botragram. Tujuannya adalah
menjaga arsitektur, keamanan, konsistensi, dan kualitas proyek selama framework
berkembang menjadi sistem trading multi-exchange.

Kata **WAJIB**, **DILARANG**, dan **SEHARUSNYA** bersifat normatif:

- **WAJIB**: harus dipenuhi sebelum perubahan dianggap selesai.
- **DILARANG**: tidak boleh dilakukan tanpa pengecualian yang terdokumentasi.
- **SEHARUSNYA**: berlaku secara default; penyimpangan harus memiliki alasan teknis.

---

## 1. Prinsip Utama

Urutan prioritas pengembangan:

1. Correctness dan keselamatan dana.
2. Keamanan credential dan data.
3. Kejelasan kontrak serta type safety.
4. Kemudahan pengujian dan pemeliharaan.
5. Performa yang telah diukur.

Setiap perubahan WAJIB mengikuti prinsip berikut:

- SOLID, DRY, KISS, dan YAGNI.
- Composition over inheritance.
- Dependency injection, bukan global state.
- Small, focused classes dan functions.
- Immutable domain models.
- Async-first untuk seluruh I/O.
- Backward compatibility dipertahankan jika memungkinkan.
- Arsitektur tidak boleh diubah hanya untuk menyelesaikan masalah lokal.

Alur kerja standar:

1. Pahami kontrak dan dependency yang sudah ada.
2. Implementasikan perubahan terkecil yang benar.
3. Tambahkan atau perbarui pengujian.
4. Jalankan seluruh quality gate yang relevan.
5. Refactor hanya setelah perilaku benar dan terlindungi pengujian.

---

## 2. Runtime dan Tooling

- Python **3.14+**.
- Encoding UTF-8.
- Setiap module Python WAJIB menggunakan
  `from __future__ import annotations`.
- Panjang baris maksimum **88 karakter**.
- PEP 8 berlaku kecuali dikendalikan lebih ketat oleh konfigurasi proyek.
- Pylance/Pyright menggunakan mode `strict`.
- Ruff adalah sumber aturan formatting, import ordering, dan linting.
- MyPy dijalankan pada area yang telah dikonfigurasi untuk MyPy.
- Pytest digunakan untuk automated test.

Versi dan konfigurasi tool WAJIB berasal dari `pyproject.toml`. Developer tidak
boleh mengandalkan konfigurasi editor pribadi untuk meloloskan quality gate.

---

## 3. Batas Arsitektur

`botragram.app` adalah composition root. Hanya application layer yang boleh
menentukan implementasi konkret untuk repository, database, exchange client,
engine, dan service.

Dependency utama:

```text
main.py
  -> app
      -> config
      -> storage implementations -> repository interfaces
      -> exchange implementations -> exchange abstractions
      -> strategies
      -> engines
      -> services

services
  -> engines
  -> repository interfaces
  -> exchange abstractions
  -> models / enums

engines
  -> strategies or exchange abstractions, sesuai tanggung jawabnya
  -> config / models / enums

storage implementations
  -> repository interfaces
  -> models / enums

exchange implementations
  -> exchange abstractions
  -> models / enums
```

Aturan batas layer:

- Circular import DILARANG.
- Domain model DILARANG bergantung pada application, service, storage, atau
  implementasi exchange.
- Service DILARANG membuat database, HTTP client, repository, atau service lain
  di dalam method-nya.
- Engine berisi keputusan dan kalkulasi trading; service mengorkestrasi use case
  dan I/O.
- Repository interface berada di `botragram/repositories/`.
- Implementasi repository berada di `botragram/storage/`.
- Exchange abstraction berada di `botragram/exchanges/base/`.
- Implementasi exchange DILARANG bocor ke domain melalui payload mentah.
- Dependency konkret dibangun oleh `DependencyProvider`; manual wiring di luar
  composition root DILARANG.
- Global singleton, service locator, dan mutable module-level state DILARANG.

Perubahan lintas layer WAJIB menjelaskan alasan, kontrak yang berubah, dan semua
consumer yang terdampak.

---

## 4. Tanggung Jawab Package

| Package | Tanggung jawab | Tidak boleh berisi |
| --- | --- | --- |
| `app` | Composition root, settings, dan lifecycle | Trading rule atau SQL |
| `config` | Immutable configuration models | Pembacaan environment langsung |
| `constants` | Konstanta bersama dan nilai default | Mutable state |
| `enums` | Pilihan domain yang tertutup | I/O atau business workflow |
| `models` | Immutable domain/data models | Database atau network client |
| `repositories` | Abstract repository contracts | Implementasi SQLite/memory |
| `storage` | Implementasi persistence | Trading decision |
| `exchanges/base` | Kontrak dan tipe transport exchange | Detail vendor |
| `exchanges/<vendor>` | REST, stream, mapper, dan client vendor | Wiring application |
| `indicators` | Perhitungan indikator deterministik | Network atau persistence |
| `strategies` | Pembentukan signal dari market data | Order submission |
| `engine` | Keputusan/kalkulasi trading yang terfokus | Lifecycle aplikasi |
| `services` | Orkestrasi use case dan boundary I/O | Konstruksi dependency |
| `telegram` | Adapter dan interaksi Telegram | Trading logic inti |
| `utils` | Helper generik, kecil, dan stateless | Dumping ground business logic |
| `tests` | Unit, integration, regression, dan smoke tests | Production credential |

Jika sebuah module tidak cocok dengan satu tanggung jawab di atas, desainnya
WAJIB ditinjau sebelum file baru dibuat.

---

## 5. Configuration dan Environment

- Semua configuration model berada di `botragram/config/`.
- Configuration model WAJIB immutable dengan
  `@dataclass(slots=True, kw_only=True, frozen=True)`.
- Environment variable hanya dibaca melalui `EnvironmentProvider`.
- `SettingsManager` adalah satu-satunya tempat untuk membentuk dan memvalidasi
  aggregate `Settings` dari environment.
- Module selain application layer DILARANG memanggil `os.getenv()`.
- Environment value WAJIB dinormalisasi dan divalidasi secara eksplisit.
- Nilai enum yang tidak dikenal WAJIB menghasilkan error; fallback diam-diam ke
  pilihan lain DILARANG.
- Kombinasi konfigurasi lintas field, seperti live mode tanpa credential, WAJIB
  divalidasi sebelum resource dibuat.
- Default harus aman: paper trading dan testnet lebih diutamakan.
- `.env.example` hanya berisi placeholder dan WAJIB diperbarui saat environment
  variable publik bertambah atau berubah.

---

## 6. Domain Model dan Immutability

- Domain/data model SEHARUSNYA menggunakan
  `@dataclass(slots=True, kw_only=True, frozen=True)`.
- Mutable collection DILARANG menjadi default langsung; gunakan
  `default_factory` atau immutable collection.
- Nilai uang, harga, quantity, fee, PnL, dan persentase finansial WAJIB memakai
  `Decimal`, bukan `float`.
- Timestamp WAJIB timezone-aware dan dinormalisasi ke UTC pada boundary.
- Validation invariant dilakukan saat object dibentuk atau sebelum operasi
  domain dijalankan.
- Model DILARANG menyimpan response dictionary vendor secara langsung.

---

## 7. Type Safety

Semua parameter, return value, attribute, collection, dan callback WAJIB memiliki
type annotation eksplisit.

Gunakan sesuai kebutuhan:

- PEP 695 `type` aliases dan generics.
- `Protocol` untuk structural contracts.
- `TypedDict` untuk payload yang benar-benar berbentuk mapping.
- `Final` untuk konstanta yang tidak boleh diubah.
- `Self` untuk fluent atau context-manager return type.
- Union eksplisit dan narrowing dengan `isinstance`, `is None`, atau pattern
  matching.

Aturan ketat:

- `Any` DILARANG kecuali API pihak ketiga benar-benar tidak bertipe.
- `cast()`, `# type: ignore`, dan konfigurasi yang mematikan diagnostic
  DILARANG sebagai jalan pintas.
- Jika pengecualian typing tidak dapat dihindari, scope harus sekecil mungkin,
  disertai alasan, dan dilindungi test boundary.
- Unparameterized collection seperti `list`, `dict`, dan `tuple` DILARANG.
- Return type `object` lebih disukai daripada `Any` untuk data belum tervalidasi.
- Data eksternal WAJIB dinarrow dan divalidasi sebelum masuk domain.

Target wajib: **0 error dan 0 warning** pada strict type checking untuk source
yang termasuk dalam konfigurasi proyek.

---

## 8. Enum, Constants, dan Magic Values

- Gunakan `Enum` untuk himpunan pilihan yang tertutup dan bermakna secara domain.
- Jangan membuat enum untuk data bebas seperti symbol, order ID, atau pesan.
- Konstanta lintas module dan default konfigurasi berada di `constants/`.
- Konstanta khusus implementasi yang hanya dipakai satu module boleh menjadi
  private module constant dengan nama `UPPER_CASE`.
- Magic number/string yang memengaruhi perilaku DILARANG berada di tengah logic.
- Literal struktural sederhana seperti `0`, `1`, string kosong, dan nama field
  lokal tidak harus dipindahkan jika maknanya sudah jelas.
- Literal endpoint, timeout, retry count, status vendor, dan protocol key WAJIB
  diberi nama.
- Mutable constant DILARANG; gunakan tuple, `frozenset`, atau mapping immutable.

---

## 9. Naming dan API

| Elemen | Format |
| --- | --- |
| Package/module | `snake_case` |
| Class/protocol/enum | `PascalCase` |
| Function/method/variable | `snake_case` |
| Constant | `UPPER_CASE` |
| Private member | `_snake_case` |
| Type alias | `PascalCase` |

Ketentuan tambahan:

- Nama WAJIB menjelaskan domain intent, bukan detail sementara.
- Boolean memakai awalan seperti `is_`, `has_`, `can_`, atau `should_`.
- Method async tidak perlu suffix `_async`.
- Singkatan yang tidak umum DILARANG.
- Public API module WAJIB didefinisikan melalui `__all__`.
- Wildcard import DILARANG.
- Perubahan public API WAJIB memperbarui export, caller, test, dan dokumentasi.

---

## 10. Struktur File dan Import

Setiap source module WAJIB memiliki header:

```python
"""
Botragram

Description:
    Deskripsi singkat tanggung jawab module.

Python:
    3.14+
"""
```

Urutan section standar:

1. Future imports.
2. Standard library imports.
3. Third-party imports.
4. Local imports.
5. `__all__`.
6. Type aliases.
7. Constants.
8. Classes/functions.

Gunakan separator berikut secara konsisten:

```python
# =============================================================================
# Local Imports
# =============================================================================
```

Aturan import:

- Absolute import `from botragram...` digunakan untuk internal package.
- Import WAJIB berada di level module kecuali lazy import dibutuhkan untuk
  memutus optional dependency yang sah.
- Unused import dan re-export tidak disengaja DILARANG.
- `__init__.py` hanya mengekspor public API yang stabil; jangan masukkan business
  logic ke dalamnya.

---

## 11. Layout Class dan Function

Urutan anggota class:

1. Docstring.
2. Class variables.
3. Constructor atau `__post_init__`.
4. Properties.
5. Public methods.
6. Protected/private methods.
7. Dunder lifecycle/context-manager methods jika relevan.

Aturan implementasi:

- Satu class atau function memiliki satu tanggung jawab utama.
- Public function, class, method, dan property WAJIB memiliki Google-style
  docstring.
- Docstring WAJIB menjelaskan `Args`, `Returns`, `Raises`, dan `Yields` jika ada.
- Signature multiline WAJIB memakai trailing comma.
- Keyword-only argument digunakan ketika meningkatkan kejelasan atau mencegah
  tertukarnya parameter sejenis.
- Side effect harus terlihat dari kontrak dan nama method.
- Nested condition yang dalam SEHARUSNYA dipecah dengan early return atau helper.
- Boolean flag yang mengubah tanggung jawab besar sebuah function SEHARUSNYA
  diganti dengan object atau method terpisah.

---

## 12. Async dan Resource Lifecycle

Semua network, database, WebSocket, Telegram, dan exchange I/O WAJIB async.

Gunakan:

- `await`, `async with`, dan `async for`.
- `asyncio.TaskGroup` untuk task yang merupakan satu unit kegagalan.
- `asyncio.timeout()` untuk boundary yang dapat menggantung.
- Cancellation-safe cleanup dengan `try/finally`.

Dilarang di event loop:

- `time.sleep()`.
- Library HTTP sinkron seperti `requests`.
- File atau database I/O blocking dalam hot path.
- Fire-and-forget task tanpa owner, nama, error handling, dan shutdown path.

Setiap resource yang memiliki `connect`, `start`, atau `initialize` WAJIB memiliki
pasangan `close`, `stop`, atau `shutdown` yang idempotent. Resource ditutup dalam
urutan terbalik dari proses pembuatannya. `CancelledError` DILARANG ditelan.

---

## 13. Error Handling dan Logging

- Gunakan exception paling spesifik yang tersedia.
- Bare `except:` DILARANG.
- `except Exception: pass` dan kegagalan diam-diam DILARANG.
- Menangkap `BaseException` hanya di lifecycle boundary untuk cleanup, kemudian
  WAJIB di-raise kembali.
- Pesan error WAJIB menyebut operasi dan nilai/konteks aman yang menyebabkan
  kegagalan.
- Error vendor diterjemahkan pada exchange/storage boundary; domain tidak boleh
  bergantung pada exception mentah transport jika ada abstraksi yang sesuai.
- Retry hanya untuk kegagalan transient, harus bounded, memakai backoff, dan
  tidak boleh mengulang operasi non-idempotent tanpa perlindungan.

Gunakan `logging`, bukan `print()`, pada production package. `print()` hanya boleh
digunakan oleh entry point CLI atau manual smoke script untuk ringkasan hasil.

Log DILARANG memuat:

- API key, secret, token, passphrase, signature, atau authorization header.
- Full request/response yang mungkin mengandung credential atau data sensitif.
- Informasi akun yang tidak diperlukan untuk diagnosis.

Gunakan structured context melalui `extra` dan jangan membentuk pesan log dari
data yang belum dinormalisasi tanpa batas ukuran.

---

## 14. Exchange Boundary

- Semua exchange client WAJIB mengimplementasikan kontrak di `exchanges/base/`.
- REST transport, stream transport, mapper, dan high-level client dipisahkan.
- Mapper bertanggung jawab mengubah payload vendor menjadi domain model.
- Service dan engine hanya menerima abstraction atau domain model.
- Symbol, interval, decimal, timestamp, order side/type/status, dan optional field
  dinormalisasi secara eksplisit.
- Unknown vendor status DILARANG dipetakan diam-diam ke status lain.
- Authenticated request WAJIB gagal sebelum network call jika credential tidak
  lengkap.
- Request non-idempotent WAJIB mempertimbangkan duplicate submission saat retry.
- Testnet dan live endpoint harus ditentukan dari validated settings.
- Fitur yang belum didukung WAJIB menghasilkan `NotImplementedError` atau error
  konfigurasi yang jelas, bukan hasil palsu.

Penambahan exchange baru belum selesai sampai factory/provider, mapping,
lifecycle, error handling, dan contract test ikut diperbarui.

---

## 15. Repository dan Storage

- Repository contract berupa ABC dan tidak mengekspos detail SQL.
- Nama dan signature method antarimplementasi memory/SQLite harus konsisten.
- Operasi repository async dan memiliki typing penuh.
- Query WAJIB menggunakan parameter binding; string interpolation SQL DILARANG.
- Migration harus berurutan, idempotent, dan aman dijalankan pada database baru.
- Transaction digunakan untuk operasi atomik multi-step.
- Timestamp, enum, boolean, dan `Decimal` diserialisasi secara konsisten.
- Repository test WAJIB mencakup empty state, save/update, filter, ordering,
  duplicate behavior, dan deletion jika didukung.
- Perubahan schema WAJIB disertai migration dan regression test.

---

## 16. Security

DILARANG commit atau menaruh di source/test fixture:

- `.env` nyata.
- API key, secret, token, passphrase, private key, atau session cookie.
- Credential yang sudah tidak aktif sekalipun.

Ketentuan wajib:

- Credential berasal dari environment dan hanya hidup di boundary yang perlu.
- `.gitignore` dan `.env.example` diperiksa ketika configuration berubah.
- Input eksternal divalidasi sebelum digunakan untuk URL, query, path, atau log.
- TLS verification DILARANG dimatikan.
- Dependency baru harus memiliki kebutuhan dan risiko yang jelas.
- Secret yang terlanjur terekspos WAJIB dirotasi; menghapusnya dari commit terbaru
  saja tidak cukup.
- Order live, cancel-all, close-all, migration destruktif, dan operasi berisiko
  tinggi harus memiliki guard serta intent yang eksplisit.

---

## 17. Performance

- Correctness didahulukan daripada micro-optimization.
- Optimization WAJIB berdasarkan profiling atau bukti bottleneck.
- Hindari nested loop yang tidak perlu dan repeated network/database query.
- Gunakan generator/iterator untuk data besar bila ownership tidak memerlukan
  materialization.
- Cache hanya digunakan jika invalidation dan lifecycle-nya jelas.
- Bounded queue WAJIB untuk stream producer/consumer agar memory tidak tumbuh
  tanpa batas.
- Timeout, retry, batch size, dan queue size tidak boleh menjadi magic value.
- Hindari object allocation atau konversi `Decimal` berulang dalam hot path jika
  dapat dihitung satu kali tanpa mengurangi kejelasan.

---

## 18. Testing Standard

Setiap fitur baru WAJIB memiliki test. Setiap bug fix WAJIB memiliki regression
test yang gagal sebelum perbaikan dan lulus setelahnya.

Jenis test:

- **Unit test**: logic deterministik tanpa network/database eksternal.
- **Integration test**: kerja sama provider, service, repository, database, atau
  boundary lain.
- **Contract test**: kesesuaian implementation dengan ABC/protocol.
- **Manual smoke test**: validasi koneksi nyata; bukan pengganti automated test.

Aturan test:

- Test deterministik dan tidak bergantung pada urutan eksekusi.
- Automated test DILARANG memakai network live atau credential nyata.
- Gunakan temporary directory/database untuk persistence test.
- Mock/fake ditempatkan pada boundary; jangan mock private method atau logic yang
  sedang diuji.
- Test harus mencakup success, empty state, boundary value, invalid input,
  failure, cancellation, dan cleanup sesuai risiko.
- Nama test menjelaskan behavior, bukan implementasi.
- Warning yang berasal dari kode proyek diperlakukan sebagai kegagalan.
- Target coverage minimum **90%**, tetapi coverage tidak menggantikan assertion
  yang bermakna.

Manual script di `tests/manual/` WAJIB aman secara default, menggunakan testnet,
dan tidak boleh melakukan trade live tanpa konfirmasi eksplisit.

---

## 19. Quality Gates

Sebelum perubahan dinyatakan selesai, jalankan dari root repository:

```powershell
python -m compileall -q botragram tests
python -m ruff format --check .
python -m ruff check .
python -m pyright
python -m pytest
```

Jalankan MyPy strict pada seluruh scope yang dikonfigurasi:

```powershell
python -m mypy
```

Kriteria lulus:

- Tidak ada syntax/compile error.
- Ruff format dan lint bersih.
- Pyright strict: 0 error dan 0 warning.
- Pylance workspace diagnostics: 0 error dan 0 warning, termasuk `tests/`.
- MyPy: 0 issue pada production code, automated test, dan manual test.
- Semua automated test lulus.
- Tidak ada warning baru dari source proyek.
- Coverage tidak turun tanpa alasan yang disetujui.
- Tidak ada credential, debug output, dead code, atau TODO tanpa konteks.

Tool yang belum terpasang bukan alasan untuk mengklaim gate tersebut lulus.
Laporkan gate yang tidak dapat dijalankan secara eksplisit.

---

## 20. Git dan Change Discipline

Nama branch:

- `feature/<nama-singkat>`
- `bugfix/<nama-singkat>`
- `hotfix/<nama-singkat>`
- `release/<versi>`

Commit mengikuti Conventional Commits:

- `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `style:`, `perf:`
- `build:`, `ci:`, `chore:`

Aturan perubahan:

- Satu commit SEHARUSNYA memiliki satu tujuan yang kohesif.
- Unrelated cleanup tidak dicampur dengan feature atau bug fix.
- Generated file, cache, virtual environment, database lokal, log, dan secret
  DILARANG masuk commit.
- Public contract yang berubah WAJIB memperbarui semua caller dan test dalam
  perubahan yang sama.
- Breaking change WAJIB memiliki alasan, migration path, dan dokumentasi.
- Komentar `TODO`, `FIXME`, atau `NOTE` WAJIB menyertakan alasan atau kondisi
  penyelesaian; placeholder tanpa konteks DILARANG.

---

## 21. Definition of Done

Perubahan dianggap selesai hanya jika semua item yang relevan terpenuhi:

- [ ] Scope dan behavior sesuai kebutuhan.
- [ ] Batas layer dan dependency direction tetap benar.
- [ ] Public API dan backward compatibility telah diperiksa.
- [ ] Type annotation lengkap; tidak ada suppression baru tanpa justifikasi.
- [ ] Error path, cancellation, dan cleanup resource telah diuji.
- [ ] Unit/integration/regression test telah ditambahkan atau diperbarui.
- [ ] Semua quality gate yang tersedia lulus.
- [ ] Tidak ada secret, debug output, dead code, atau duplicate logic.
- [ ] Dokumentasi, `.env.example`, export, dan migration diperbarui jika perlu.
- [ ] Perubahan minimal, mudah ditinjau, dan tidak membawa refactor tak terkait.

---

## 22. Struktur Proyek Saat Ini

Bagian ini mendokumentasikan struktur nyata repository, bukan rencana folder
masa depan. Perbarui bagian ini pada perubahan yang menambah, memindahkan, atau
menghapus package/module utama.

```text
Botragram/
|-- botragram/
|   |-- __init__.py
|   |-- app/
|   |   |-- __init__.py
|   |   |-- application.py
|   |   |-- dependency_provider.py
|   |   |-- environment_provider.py
|   |   |-- lifecycle.py
|   |   |-- runtime_control.py
|   |   |-- settings_manager.py
|   |   |-- shutdown.py
|   |   |-- startup.py
|   |   `-- trading_runner.py
|   |-- config/
|   |   |-- __init__.py
|   |   |-- ai_settings.py
|   |   |-- app_settings.py
|   |   |-- exchange_settings.py
|   |   |-- logging_settings.py
|   |   |-- market_settings.py
|   |   |-- risk_settings.py
|   |   |-- settings.py
|   |   |-- strategy_settings.py
|   |   `-- telegram_settings.py
|   |-- constants/
|   |   |-- __init__.py
|   |   |-- ai.py
|   |   |-- app.py
|   |   |-- env.py
|   |   |-- exchange.py
|   |   |-- indicator.py
|   |   |-- market.py
|   |   |-- order.py
|   |   |-- position.py
|   |   |-- risk.py
|   |   |-- strategy.py
|   |   |-- telegram.py
|   |   `-- time.py
|   |-- engine/
|   |   |-- __init__.py
|   |   |-- order_engine.py
|   |   |-- pnl_engine.py
|   |   |-- portfolio_engine.py
|   |   |-- position_engine.py
|   |   |-- risk_engine.py
|   |   |-- signal_engine.py
|   |   `-- trading_engine.py
|   |-- enums/
|   |   |-- __init__.py
|   |   |-- base.py
|   |   |-- environment.py
|   |   `-- <domain_enum>.py
|   |-- exceptions/
|   |   |-- __init__.py
|   |   |-- base.py
|   |   `-- <domain_exception>.py
|   |-- exchanges/
|   |   |-- __init__.py
|   |   |-- factory.py
|   |   |-- base/
|   |   |   |-- __init__.py
|   |   |   |-- client.py
|   |   |   |-- mapper.py
|   |   |   |-- rest.py
|   |   |   `-- stream.py
|   |   |-- binance/
|   |   |-- bitget/
|   |   |-- bybit/
|   |   `-- okx/
|   |       |-- __init__.py
|   |       |-- client.py
|   |       |-- mapper.py
|   |       |-- rest.py
|   |       `-- stream.py
|   |-- indicators/
|   |   |-- __init__.py
|   |   |-- momentum/
|   |   |   |-- __init__.py
|   |   |   |-- macd.py
|   |   |   `-- rsi.py
|   |   |-- overlap/
|   |   |   |-- __init__.py
|   |   |   |-- ichimoku.py
|   |   |   `-- psar.py
|   |   |-- trend/
|   |   |   |-- __init__.py
|   |   |   |-- adx.py
|   |   |   |-- ema.py
|   |   |   |-- sma.py
|   |   |   `-- supertrend.py
|   |   |-- volatility/
|   |   |   |-- __init__.py
|   |   |   |-- atr.py
|   |   |   `-- bollinger_bands.py
|   |   `-- volume/
|   |       |-- __init__.py
|   |       |-- obv.py
|   |       `-- vwap.py
|   |-- models/
|   |   |-- __init__.py
|   |   |-- account.py
|   |   |-- balance.py
|   |   |-- candle.py
|   |   |-- notification.py
|   |   |-- order.py
|   |   |-- position.py
|   |   |-- risk.py
|   |   |-- signal.py
|   |   |-- ticker.py
|   |   |-- trade.py
|   |   `-- trading.py
|   |-- repositories/
|   |   |-- __init__.py
|   |   |-- candle_repository.py
|   |   |-- order_repository.py
|   |   |-- position_repository.py
|   |   |-- signal_repository.py
|   |   `-- trade_repository.py
|   |-- services/
|   |   |-- __init__.py
|   |   |-- account_service.py
|   |   |-- health_service.py
|   |   |-- market_service.py
|   |   |-- order_service.py
|   |   |-- paper_trading_service.py
|   |   |-- position_service.py
|   |   |-- runtime_reporter.py
|   |   |-- strategy_service.py
|   |   `-- trading_service.py
|   |-- storage/
|   |   |-- __init__.py
|   |   |-- base/
|   |   |   |-- __init__.py
|   |   |   `-- memory_repository.py
|   |   |-- memory/
|   |   |   |-- __init__.py
|   |   |   `-- <entity_repository>.py
|   |   `-- sqlite/
|   |       |-- __init__.py
|   |       |-- database.py
|   |       |-- migrations.py
|   |       `-- <entity_repository>.py
|   |-- strategies/
|   |   |-- __init__.py
|   |   |-- factory.py
|   |   |-- ai/
|   |   |-- base/
|   |   |-- breakout/
|   |   |-- scalping/
|   |   |-- swing/
|   |   `-- trend/
|   |-- telegram/
|   |   |-- __init__.py
|   |   |-- access.py
|   |   |-- bot.py
|   |   |-- callbacks.py
|   |   |-- commands.py
|   |   |-- context.py
|   |   |-- handlers.py
|   |   |-- keyboards.py
|   |   |-- messages.py
|   |   `-- query_service.py
|   `-- utils/
|       |-- __init__.py
|       |-- datetime.py
|       |-- decimal.py
|       |-- formatter.py
|       |-- logger.py
|       `-- validator.py
|-- tests/
|   |-- __init__.py
|   |-- manual/
|   |   |-- __init__.py
|   |   `-- test_*.py
|   `-- test_*.py
|-- data/                         # SQLite runtime; isi diabaikan Git
|-- logs/                         # Log runtime; isi diabaikan Git
|-- .env.example
|-- .gitignore
|-- DEVELOPMENT_GUIDE.md
|-- README.md
|-- main.py
|-- pyproject.toml
`-- requirements.txt
```

Catatan struktur:

- Folder vendor exchange memiliki pola file yang sama: `client.py`, `mapper.py`,
  `rest.py`, dan `stream.py`.
- `<domain_enum>.py`, `<domain_exception>.py`, dan `<entity_repository>.py` adalah
  singkatan dokumentasi untuk kumpulan module sejenis yang sudah ada; bukan nama
  file literal.
- `data/` dan `logs/` adalah direktori runtime, bukan package Python. Database
  SQLite default WAJIB berada di `data/botragram.db`; file database, WAL, dan log
  tidak boleh di-commit.
- Folder cache, virtual environment, dan `__pycache__` tidak termasuk struktur
  source dan tidak boleh didokumentasikan sebagai package.
- Folder aspiratif tidak boleh dimasukkan ke struktur ini sebelum benar-benar
  dibuat dan memiliki tanggung jawab yang disetujui.
