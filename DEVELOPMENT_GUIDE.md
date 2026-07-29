Botragram Coding Style

1. General

- Python 3.14+
- UTF-8 Encoding.
- Gunakan "from __future__ import annotations".
- PEP 8.
- Pylance Strict wajib.
- Type Hint wajib.
- Tidak boleh wildcard import ("*").
- Tidak boleh magic number.
- Tidak boleh magic string.
- Tidak boleh "print()".
- Dependency harus eksplisit.
- Kode harus bersih, konsisten, dan mudah dibaca.

---

2. Project Rules

- Make it work.
- Test it.
- Lock it.
- Refactor later.

Jangan melakukan refactor sebelum fitur selesai dan berjalan.

---

3. Naming Convention

Package

snake_case

Module

snake_case.py

Class

PascalCase

Enum

PascalCase

Function

snake_case

Method

snake_case

Variable

snake_case

Constant

UPPER_CASE

Private

_snake_case

---

4. Folder Responsibility

config/

- Semua konfigurasi.

constants/

- Semua konstanta.

enums/

- Semua enum.

exchanges/

- Semua implementasi exchange.

engine/

- Trading Engine.

telegram/

- Telegram Bot.

utils/

- Helper.

tests/

- Unit Test.

---

5. Import Order

1. Future
2. Standard Library
3. Third Party
4. Local Imports

Gunakan header section.

Contoh:

# =============================================================================
# Future
# =============================================================================

# =============================================================================
# Standard Library
# =============================================================================

# =============================================================================
# Third Party
# =============================================================================

# =============================================================================
# Local Imports
# =============================================================================

---

6. File Header

Semua file wajib memiliki header.

"""
Botragram

Description:
    ...

Python:
    3.14+
"""

---

7. Section Header

Gunakan format berikut.

# =============================================================================
# Constants
# =============================================================================

---

8. Type Hint

Semua:

- Parameter
- Return
- Attribute

wajib memiliki Type Hint.

Gunakan:

- Self
- Literal
- Final
- Protocol
- TypedDict
- TypeAlias
- Generic

jika diperlukan.

---

9. Pylance

Gunakan

Strict Mode

Target:

- 0 Error
- 0 Warning

Tidak boleh menggunakan:

- Any
- type: ignore

kecuali benar-benar diperlukan.

---

10. Constructor

Constructor diletakkan setelah class variable.

---

11. Class Layout

Urutan:

1. Docstring
2. Class Variable
3. Constructor
4. Property
5. Public Method
6. Private Method

---

12. Function Layout

Gunakan trailing comma.

Contoh:

def create_order(
    self,
    symbol: str,
    quantity: float,
) -> None:
    ...

---

13. Constants

Semua konstanta wajib berada di folder:

constants/

Tidak boleh hardcode.

---

14. Enum

Semua pilihan menggunakan Enum.

---

15. Config

Semua konfigurasi berada di folder:

config/

---

16. Exception

Tidak boleh:

except:

Gunakan exception yang spesifik.

---

17. Logging

Tidak boleh:

print()

Gunakan logging.

---

18. Async

Semua operasi:

- Network
- WebSocket
- Telegram
- Exchange

menggunakan Async.

---

19. Dependency Injection

Tidak boleh menggunakan Global Singleton.

Gunakan Dependency Injection.

---

20. Comment

Comment hanya menjelaskan:

WHY

Bukan:

WHAT

---

21. TODO

Gunakan:

- TODO:
- FIXME:
- NOTE:

---

22. Line Length

Maksimal:

88 karakter.

---

23. Docstring

Semua Public:

- Class
- Function
- Method

wajib memiliki Docstring.

Gunakan Google Style.

---

24. Testing

Semua fitur baru harus dapat diuji.

---

25. Lint

Kode dianggap selesai jika:

- Pylance Strict = 0 Error
- Formatter = Bersih
- Tidak ada warning
- Import Order benar

---

26. Refactor

Refactor hanya dilakukan jika:

- Ada bug.
- Performa buruk.
- Kode terlalu besar.
- Fitur sudah selesai.

Tidak melakukan refactor saat fitur masih dalam proses.


Botragram Project Structure

botragram/
│
├── app/
│   ├── __init__.py
│   ├── application.py
│   ├── environment_provider.py
│   ├── settings_manager.py
│   └── startup.py
│
├── config/
│   ├── __init__.py
│   ├── app_settings.py
│   ├── exchange_settings.py
│   ├── market_settings.py
│   ├── risk_settings.py
│   ├── strategy_settings.py
│   └── telegram_settings.py
│
├── constants/
│   ├── __init__.py
│   ├── app.py
│   ├── env.py
│   ├── exchange.py
│   ├── market.py
│   ├── telegram.py
│   └── time.py
│
├── enums/
│   ├── __init__.py
│   ├── exchange_type.py
│   ├── interval.py
│   ├── margin_mode.py
│   ├── order_side.py
│   ├── order_status.py
│   ├── order_type.py
│   ├── position_side.py
│   ├── signal_type.py
│   ├── strategy_type.py
│   ├── telegram_state.py
│   ├── time_in_force.py
│   └── trade_mode.py
│
├── exchanges/
│   ├── __init__.py
│   │
│   ├── base/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── rest.py
│   │   ├── stream.py
│   │   └── mapper.py
│   │
│   ├── bybit/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── rest.py
│   │   ├── stream.py
│   │   └── mapper.py
│   │
│   ├── binance/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── rest.py
│   │   ├── stream.py
│   │   └── mapper.py
│   │
│   ├── okx/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── rest.py
│   │   ├── stream.py
│   │   └── mapper.py
│   │
│   └── bitget/
│       ├── __init__.py
│       ├── client.py
│       ├── rest.py
│       ├── stream.py
│       └── mapper.py
│
├── engine/
│   ├── __init__.py
│   ├── trading_engine.py
│   ├── signal_engine.py
│   ├── order_engine.py
│   ├── position_engine.py
│   ├── risk_engine.py
│   └── pnl_engine.py
│
├── indicators/
│   ├── __init__.py
│   ├── ema.py
│   ├── sma.py
│   ├── rsi.py
│   ├── macd.py
│   ├── atr.py
│   └── supertrend.py
│
├── strategies/
│   ├── __init__.py
│   ├── base_strategy.py
│   ├── ema_cross.py
│   ├── ema_rsi.py
│   └── supertrend.py
│
├── telegram/
│   ├── __init__.py
│   ├── bot.py
│   ├── commands.py
│   ├── handlers.py
│   ├── callbacks.py
│   ├── keyboards.py
│   └── messages.py
│
├── utils/
│   ├── __init__.py
│   ├── datetime.py
│   ├── decimal.py
│   ├── formatter.py
│   ├── logger.py
│   └── validator.py
│
├── tests/
│   ├── __init__.py
│   ├── test_engine.py
│   ├── test_exchange.py
│   ├── test_indicator.py
│   ├── test_strategy.py
│   └── test_telegram.py
│
├── .env
├── .env.example
├── .gitignore
├── main.py
├── requirements.txt
├── README.md
└── DEVELOPMENT_GUIDE.md
