# Botragram Coding Style

## 1. General

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

## 2. Project Rules

- Make it work.
- Test it.
- Lock it.
- Refactor later.

Jangan melakukan refactor sebelum fitur selesai dan berjalan.

---

## 3. Design Principles

- SOLID
- DRY (Don't Repeat Yourself)
- KISS (Keep It Simple)
- YAGNI (You Aren't Gonna Need It)
- Composition over Inheritance
- Single Responsibility Principle

---

## 4. Architecture Rules

Dependency Direction:

main
↓
Application
↓
Engine
↓
Strategy
↓
Exchange
↓
Utils

Tidak boleh terjadi circular import.

Module level dependency harus satu arah.

---

## 5. Async Rules

Gunakan:

- asyncio
- TaskGroup
- asyncio.timeout()

Tidak boleh:

- time.sleep()
- requests
- blocking I/O

Gunakan:

- await
- async with
- async for

---

## 6. Error Handling

Semua exception harus:

- memiliki pesan jelas
- menggunakan exception spesifik
- dicatat melalui logger

Tidak boleh:

except Exception:
    pass

---

## 7. Testing Standard

Minimal:

- Unit Test
- Integration Test

Target:

Coverage ≥ 90%

Semua bug yang diperbaiki harus memiliki test baru.

---

## 8. Git Rules

Branch

feature/*
bugfix/*
hotfix/*
release/*

Commit

Gunakan Conventional Commits

feat:
fix:
refactor:
test:
docs:
style:
perf:
build:
ci:
chore:

---

## 9. Security

Tidak boleh commit:

- .env
- API Key
- Secret
- Token
- Private Key

Semua credential berasal dari Environment Variable.

---

## 10. Performance

Hindari:

- nested loop yang tidak perlu
- object allocation berlebihan
- blocking operation

Gunakan:

- cache bila diperlukan
- lazy loading
- generator

---

## 11. Code Review Checklist

Sebelum merge:

✓ Test lulus
✓ Pylance Strict = 0 Error
✓ Formatter bersih
✓ Import benar
✓ Tidak ada dead code
✓ Tidak ada TODO yang terlupakan
✓ Tidak ada credential
✓ Docstring lengkap

---

## 12. Naming Convention

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

## 13. Folder Responsibility

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

## 14. File Header

Semua file wajib memiliki header.

"""
Botragram

Description:
    ...

Python:
    3.14+
"""

---

## 15. Section Header

Gunakan format berikut.

    # =============================================================================
    # Constants
    # =============================================================================

---

## 16. Import Order

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

## 17. Type Hint

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

## 18. Pylance

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

## 19. Constructor

Constructor diletakkan setelah class variable.

---

## 20. Class Layout

Urutan:

    1. Docstring
    2. Class Variable
    3. Constructor
    4. Property
    5. Public Method
    6. Private Method

---

## 21. Function Layout

Gunakan trailing comma.

Contoh:

def create_order(
    self,
    symbol: str,
    quantity: float,
) -> None:
    ...

---

## 22. Constants

Semua konstanta wajib berada di folder:

constants/

Tidak boleh hardcode.

---

## 23. Enum

Semua pilihan menggunakan Enum.

---

## 24. Config

Semua konfigurasi berada di folder:

config/

---

## 25. Exception

Tidak boleh:

except:

Gunakan exception yang spesifik.

---

## 26. Logging

Tidak boleh:

print()

Gunakan logging.

---

## 27. Async

Semua operasi:

- Network
- WebSocket
- Telegram
- Exchange

menggunakan Async.

---

## 28. Dependency Injection

Tidak boleh menggunakan Global Singleton.

Gunakan Dependency Injection.

---

## 29. Comment

Comment hanya menjelaskan:

WHY

Bukan:

WHAT

---

## 30. TODO

Gunakan:

- TODO:
- FIXME:
- NOTE:

---

## 31. Line Length

Maksimal:

88 karakter.

---

## 32. Docstring

Semua Public:

- Class
- Function
- Method

wajib memiliki Docstring.

Gunakan Google Style.

---

## 33. Testing

Semua fitur baru harus dapat diuji.

---

## 34. Lint

Kode dianggap selesai jika:

- Pylance Strict = 0 Error
- Formatter = Bersih
- Tidak ada warning
- Import Order benar

---

## 35. Refactor

Refactor hanya dilakukan jika:

- Ada bug.
- Performa buruk.
- Kode terlalu besar.
- Fitur sudah selesai.

Tidak melakukan refactor saat fitur masih dalam proses.

## Botragram Project Structure

Proyek bot trading Multi-CEX (Binance, Bybit, Bitget, OKX) dengan integrasi Telegram dan standar arsitektur modular yang ketat.

    botragram/
    ├── app/
    │   ├── __init__.py
    │   ├── application.py
    │   ├── startup.py
    │   ├── shutdown.py
    │   ├── lifecycle.py
    │   ├── dependency_provider.py
    │   ├── environment_provider.py
    │   └── settings_manager.py
    │
    ├── config/
    │   ├── __init__.py
    │   ├── app_settings.py
    │   ├── exchange_settings.py
    │   ├── telegram_settings.py
    │   ├── market_settings.py
    │   ├── strategy_settings.py
    │   ├── risk_settings.py
    │   ├── ai_settings.py
    │   └── logging_settings.py
    │
    ├── constants/
    │   ├── __init__.py
    │   ├── app.py
    │   ├── env.py
    │   ├── exchange.py
    │   ├── indicator.py
    │   ├── market.py
    │   ├── order.py
    │   ├── position.py
    │   ├── risk.py
    │   ├── status.py
    │   ├── strategy.py
    │   ├── telegram.py
    │   └── time.py
    │
    ├── enums/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── exchange_type.py
    │   ├── interval.py
    │   ├── order_side.py
    │   ├── order_type.py
    │   ├── order_status.py
    │   ├── position_side.py
    │   ├── margin_mode.py
    │   ├── trade_mode.py
    │   ├── signal_type.py
    │   ├── strategy_type.py
    │   ├── telegram_state.py
    │   ├── ai_model_type.py
    │   └── notification_type.py
    │
    ├── core/
    │   ├── __init__.py
    │   ├── events/
    │   ├── scheduler/
    │   ├── dependency_injection.py
    │   ├── event_bus.py
    │   ├── clock.py
    │   └── state_machine.py
    │
    ├── models/
    │   ├── __init__.py
    │   ├── candle.py
    │   ├── ticker.py
    │   ├── order.py
    │   ├── position.py
    │   ├── balance.py
    │   ├── trade.py
    │   ├── signal.py
    │   ├── account.py
    │   └── notification.py
    │
    ├── repositories/
    │   ├── __init__.py
    │   ├── trade_repository.py
    │   ├── order_repository.py
    │   ├── position_repository.py
    │   ├── candle_repository.py
    │   └── signal_repository.py
    │
    ├── storage/
    │   ├── __init__.py
    │   ├── file/
    │   ├── sqlite/
    │   ├── cache/
    │   └── memory/
    │
    ├── services/
    │   ├── __init__.py
    │   ├── account_service.py
    │   ├── market_service.py
    │   ├── notification_service.py
    │   ├── strategy_service.py
    │   ├── exchange_service.py
    │   └── telegram_service.py
    │
    ├── exchanges/
    │   ├── __init__.py
    │   ├── base/
    │   ├── binance/
    │   ├── bybit/
    │   ├── bitget/
    │   ├── okx/
    │   └── factory.py
    │
    ├── indicators/
    │   ├── __init__.py
    │   ├── trend/
    │   ├── momentum/
    │   ├── volatility/
    │   ├── volume/
    │   └── overlap/
    │
    ├── strategies/
    │   ├── __init__.py
    │   ├── base/
    │   ├── trend/
    │   ├── breakout/
    │   ├── scalping/
    │   ├── swing/
    │   ├── ai/
    │   └── factory.py
    │
    ├── ai/
    │   ├── __init__.py
    │   ├── datasets/
    │   ├── features/
    │   ├── preprocessing/
    │   ├── labels/
    │   ├── trainers/
    │   ├── predictors/
    │   ├── models/
    │   ├── evaluation/
    │   - optimization/
    │   └── backtesting/
    │
    ├── engine/
    │   ├── __init__.py
    │   ├── trading_engine.py
    │   ├── signal_engine.py
    │   ├── order_engine.py
    │   ├── position_engine.py
    │   ├── risk_engine.py
    │   ├── pnl_engine.py
    │   └── portfolio_engine.py
    │
    ├── telegram/
    │   ├── __init__.py
    │   ├── bot.py
    │   ├── commands/
    │   ├── callbacks/
    │   ├── handlers/
    │   ├── middlewares/
    │   ├── keyboards/
    │   ├── conversations/
    │   └── messages/
    │
    ├── tasks/
    │   ├── __init__.py
    │   ├── market_scan.py
    │   ├── sync_balance.py
    │   ├── clean_cache.py
    │   └── health_check.py
    │
    ├── utils/
    │   ├── __init__.py
    │   ├── datetime.py
    │   ├── decimal.py
    │   ├── formatter.py
    │   ├── validator.py
    │   ├── retry.py
    │   ├── logger.py
    │   ├── json.py
    │   └── crypto.py
    │
    ├── exceptions/
    │   ├── __init__.py
    │   ├── exchange.py
    │   ├── strategy.py
    │   ├── telegram.py
    │   ├── validation.py
    │   └── storage.py
    │
    ├── docs/
    │   ├── architecture.md
    │   ├── api.md
    │   ├── exchanges.md
    │   ├── strategy.md
    │   ├── ai.md
    │   └── deployment.md
    │
    ├── scripts/
    ├── tests/
    ├── logs/
    ├── .github/
    ├── main.py
    ├── pyproject.toml
    ├── requirements.txt
    ├── README.md
    └── DEVELOPMENT_GUIDE.md
