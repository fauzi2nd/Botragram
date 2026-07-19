# Trading Bot Project Blueprint

Version : 1.0
Status  : FROZEN
Python  : 3.14

---

# Vision

Membangun trading bot profesional yang:

- Modular
- Async First
- Multi Exchange
- Multi Timeframe
- Rule-Based
- Mudah di-maintain
- Production Ready

Machine Learning bukan bagian dari v1.

---

# Project Principles

- Keep It Simple
- Modular Architecture
- Async First
- Explicit over Implicit
- Strong Typing
- Composition over Inheritance
- Single Responsibility Principle

---

# Tech Stack

## Core

- Python 3.14

## Exchange

- CCXT
- CCXT Pro

## Data

- Pandas
- NumPy
- PyArrow

## Indicator

- TA-Lib

## Logging

- Loguru

## Telegram

- Aiogram

## Configuration

- Pydantic
- python-dotenv

## JSON

- orjson

## Visualization

- matplotlib
- mplfinance

## Development

- pytest
- pytest-asyncio
- black
- isort
- ruff
- tqdm

---

# Not Used

Project ini tidak menggunakan:

- Machine Learning
- TensorFlow
- XGBoost
- SQLAlchemy
- FastAPI
- Redis
- APScheduler
- aiofiles
- Dependency Injection Framework
- Event Bus

---

# Project Structure

trading_bot/

    analysis/

    backtest/

    config/

    core/

    exchange/

        bybit/

        binance/

        bitget/

        okx/

    indicators/

    models/

    services/

    storage/

        cache/

        database/

        files/

    strategy/

    tests/

    utils/

Semua package wajib memiliki __init__.py

---

# Folder Responsibilities

analysis
    Market Analysis

backtest
    Backtesting Engine

config
    Project Configuration

core
    Core Runtime Components

exchange
    Exchange Wrapper

indicators
    Technical Indicators

models
    Shared Models

services
    Module Orchestration

storage
    Database, Cache, File

strategy
    Trading Decision

tests
    Unit & Integration Test

utils
    General Helper

---

# Architecture Flow

Exchange

↓

Indicators

↓

Analysis

↓

Strategy

↓

Execution

↓

Exchange

Backtest menggunakan pipeline yang sama.

---

# Coding Standards

- Async First
- Python 3.14
- Pylance Strict
- Type Hint 100%
- dataclass(slots=True)
- Decimal untuk data finansial
- UTC Only
- pathlib.Path
- Constructor Injection
- Wrapper Loguru
- Wrapper CCXT

---

# Naming

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

---

# Logging

Seluruh logging menggunakan wrapper internal.

Tidak boleh menggunakan print().

---

# Configuration

Semua konfigurasi berasal dari:

.env

↓

Pydantic

↓

Config Object

Tidak boleh memanggil os.getenv() di luar config.

---

# Telegram

Telegram digunakan untuk:

- Monitoring
- Notification
- Manual Command
- Emergency Control

---

# Freeze Rules

Mulai versi 1.0:

- Struktur folder utama tidak berubah.
- Library tidak berubah.
- Coding Style tidak berubah.
- Architecture tidak berubah.

Perubahan hanya dilakukan apabila terdapat bug desain.

---

# Development Roadmap

Phase 1
Exchange

Phase 2
Indicators

Phase 3
Analysis

Phase 4
Strategy

Phase 5
Services

Phase 6
Telegram

Phase 7
Backtest

Phase 8
Live Trading