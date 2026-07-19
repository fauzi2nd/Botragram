Trading Bot

Professional Async Multi-Exchange Trading Bot built with Python 3.14.

---

Overview

Trading Bot adalah bot trading modular yang dirancang untuk:

- Multi Exchange
- Multi Timeframe
- Rule-Based Analysis
- Live Trading
- Backtesting
- Telegram Monitoring
- High Performance

Project ini menggunakan arsitektur modular sehingga mudah dikembangkan dan dipelihara.

Machine Learning bukan bagian dari versi 1 dan akan ditambahkan setelah tersedia dataset yang memadai.

---

Features

- Multi Exchange (CCXT)
- WebSocket (CCXT Pro)
- Rule-Based Strategy
- Technical Indicators
- Market Analysis
- Telegram Monitoring
- Telegram Control
- Backtesting
- Structured Logging
- Strong Typing
- Async Architecture

---

Tech Stack

Core

- Python 3.14

Exchange

- CCXT
- CCXT Pro

Data

- Pandas
- NumPy
- PyArrow

Technical Analysis

- TA-Lib

Logging

- Loguru

Telegram

- Aiogram

Configuration

- Pydantic
- python-dotenv

JSON

- orjson

Visualization

- matplotlib
- mplfinance

---

Project Structure

trading_bot/

├── analysis/
├── backtest/
├── config/
├── core/
├── exchange/
├── indicators/
├── models/
├── services/
├── storage/
├── strategy/
├── tests/
├── utils/
│
├── .env
├── main.py
├── requirements.txt
└── README.md

---

Architecture

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

Backtesting menggunakan pipeline yang sama dengan Live Trading.

---

Installation

Clone repository

git clone <repository_url>

Masuk ke folder project

cd trading_bot

Buat virtual environment

python -m venv .venv

Aktifkan virtual environment

Windows

.venv\Scripts\activate

Linux / macOS

source .venv/bin/activate

Install dependency

pip install -r requirements.txt

---

Configuration

Salin file contoh konfigurasi

.env.example

menjadi

.env

Kemudian isi:

- Exchange API Key
- Secret Key
- Telegram Token
- Telegram Chat ID

---

Development

Format code

black .

Sort import

isort .

Lint

ruff check .

Run tests

pytest

---

Project Documents

- PROJECT_BLUEPRINT.md
- CONTRIBUTING.md
- CHANGELOG.md
- TODO.md

---

Development Roadmap

Phase 1

Exchange

↓

Phase 2

Indicators

↓

Phase 3

Analysis

↓

Phase 4

Strategy

↓

Phase 5

Services

↓

Phase 6

Telegram

↓

Phase 7

Backtest

↓

Phase 8

Live Trading

---

License

Private Project.