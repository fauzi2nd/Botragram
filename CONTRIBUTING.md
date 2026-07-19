Contributing Guide

Dokumen ini berisi standar pengembangan Trading Bot.

Semua kode yang ditambahkan ke project harus mengikuti aturan di bawah ini.

---

Development Philosophy

Selalu utamakan:

- Readability
- Maintainability
- Simplicity
- Consistency

Jangan menulis kode yang "terlihat pintar" tetapi sulit dipahami.

---

General Rules

- Python 3.14
- Async First
- Pylance Strict
- Type Hint 100%
- Tidak menggunakan "Any" kecuali benar-benar diperlukan.
- Tidak menggunakan "print()".
- Seluruh logging menggunakan wrapper internal.
- Seluruh komunikasi Exchange melalui wrapper CCXT.
- Seluruh konfigurasi melalui Config.
- Seluruh data finansial menggunakan "Decimal".

---

File Rules

Satu file memiliki satu tanggung jawab.

Jika file mulai terlalu besar (±500–700 baris), pertimbangkan untuk memecahnya menjadi beberapa file.

---

Function Rules

Function harus:

- Memiliki satu tanggung jawab.
- Nama jelas.
- Mudah diuji.
- Tidak terlalu panjang.

Sebisa mungkin maksimal sekitar 50 baris. Jika lebih, evaluasi apakah perlu dipecah.

---

Class Rules

Class harus mengikuti Single Responsibility Principle.

Hindari membuat "God Class" yang menangani terlalu banyak hal.

---

Model Rules

Semua model menggunakan:

- @dataclass(slots=True)
- Type Hint lengkap
- Immutable jika memungkinkan

Model tidak boleh memiliki business logic yang kompleks.

---

Service Rules

Service hanya bertugas mengorkestrasi modul.

Service tidak boleh:

- Menghitung indikator.
- Membuat analisis.
- Menentukan BUY/SELL.

---

Strategy Rules

Seluruh keputusan trading berada di folder strategy.

Contoh:

- Entry
- Exit
- Stop Loss
- Take Profit
- Risk Management
- Position Sizing

Tidak boleh ada keputusan trading di folder lain.

---

Analysis Rules

Analysis hanya mengolah data indikator menjadi informasi market.

Tidak boleh mengirim order.

---

Indicator Rules

Indicator hanya menghitung nilai indikator.

Tidak boleh mengetahui Strategy.

---

Exchange Rules

Exchange hanya berkomunikasi dengan Exchange melalui CCXT.

Tidak boleh mengetahui Strategy.

---

Storage Rules

Storage hanya bertugas:

- Database
- Cache
- File

Storage tidak boleh memiliki business logic.

---

Logging Rules

Gunakan logger internal.

Contoh:

logger.info(...)

logger.warning(...)

logger.error(...)

logger.exception(...)

Jangan pernah menggunakan print().

---

Error Handling

Tangkap exception spesifik.

Hindari:

except Exception:

kecuali di level aplikasi paling atas untuk logging dan graceful shutdown.

---

Import Order

1. Standard Library
2. Third Party
3. Internal Module

Gunakan isort untuk menjaga konsistensi.

---

Naming Convention

File

snake_case.py

Class

PascalCase

Function

snake_case

Variable

snake_case

Constant

UPPER_CASE

Private

_leading_underscore

---

Comments

Komentar hanya digunakan untuk menjelaskan alasan (why), bukan menjelaskan kode yang sudah jelas (what).

Kode yang baik seharusnya mudah dipahami tanpa banyak komentar.

---

Testing

Semua modul penting harus memiliki unit test.

Gunakan:

- pytest
- pytest-asyncio

---

Pull Checklist

Sebelum sebuah modul dianggap selesai:

- Kode berjalan tanpa error.
- Lulus Pylance Strict.
- Type Hint lengkap.
- Tidak ada warning Ruff.
- Sudah diformat Black.
- Import sudah dirapikan Isort.
- Tidak ada print().
- Tidak ada TODO yang terlupakan.
- Logging sudah sesuai standar.
- Dokumentasi diperbarui jika diperlukan.

---

Architecture Freeze

Struktur folder utama tidak boleh diubah tanpa alasan yang sangat kuat.

Perubahan struktur hanya diperbolehkan apabila terdapat bug desain yang menghambat implementasi.

---

Golden Rule

Jika ragu, pilih solusi yang:

- lebih sederhana,
- lebih mudah dipahami,
- lebih mudah diuji,
- lebih mudah dipelihara.