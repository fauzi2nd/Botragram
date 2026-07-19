Trading Bot Model Specification

Version : 1.0

Dokumen ini mendefinisikan seluruh model yang digunakan dalam project.

Model bersifat Frozen. Perubahan hanya dilakukan apabila terdapat kebutuhan desain yang benar-benar baru.

---

Model Categories

Seluruh model dibagi menjadi tiga kategori.

1. Reference Model

Data referensi yang jarang berubah.

Contoh:

- Symbol

---

2. Snapshot Model

Data pada satu titik waktu.

Contoh:

- Candle
- Ticker
- OrderBook
- Balance
- Position

---

3. Event Model

Representasi suatu kejadian.

Contoh:

- Order
- Trade
- Signal
- TradeSetup

---

Global Rules

Semua model harus:

- menggunakan "@dataclass(slots=True)"
- memiliki type hint lengkap
- menggunakan "Decimal" untuk seluruh nilai finansial
- menggunakan UTC ("datetime.UTC")
- immutable jika memungkinkan
- tidak memiliki business logic
- tidak mengakses Exchange
- tidak mengakses Database
- tidak melakukan I/O

Model hanya merepresentasikan data.

---

Symbol

Category

Reference Model

Purpose

Merepresentasikan instrumen trading.

Digunakan oleh hampir seluruh project.

---

Fields

Field| Type| Required
exchange| ExchangeType| Yes
category| MarketType| Yes
symbol| str| Yes
exchange_symbol| str| Yes
base_asset| str| Yes
quote_asset| str| Yes
settle_asset| str | None| No
price_precision| int| Yes
quantity_precision| int| Yes
tick_size| Decimal| Yes
lot_size| Decimal| Yes
min_quantity| Decimal| Yes
max_quantity| Decimal | None| No
min_notional| Decimal| Yes
contract_size| Decimal| Yes
active| bool| Yes

Identity

(exchange, category, symbol)

Properties

- display_name
- is_spot
- is_futures

Validation

- tick_size > 0
- lot_size > 0
- min_quantity > 0
- price_precision >= 0
- quantity_precision >= 0

---

Candle

Category

Snapshot Model

Purpose

Representasi satu candle OHLCV.

Immutable.

---

Fields

Field| Type| Required
symbol| Symbol| Yes
timeframe| Timeframe| Yes
open_time| datetime| Yes
close_time| datetime| Yes
open| Decimal| Yes
high| Decimal| Yes
low| Decimal| Yes
close| Decimal| Yes
volume| Decimal| Yes
quote_volume| Decimal | None| No
trade_count| int | None| No
taker_buy_base_volume| Decimal | None| No
taker_buy_quote_volume| Decimal | None| No
is_closed| bool| Yes

Identity

(symbol, timeframe, open_time)

Properties

- is_bullish
- is_bearish
- body_size
- upper_wick
- lower_wick
- range

Validation

- high >= open
- high >= close
- low <= open
- low <= close
- volume >= 0
- close_time > open_time

---

Ticker

Category

Snapshot Model

Purpose

Representasi kondisi market terkini.

Planned Fields

- symbol
- bid
- ask
- last
- mark_price
- index_price
- high
- low
- volume
- quote_volume
- funding_rate
- open_interest
- timestamp

---

OrderBook

Category

Snapshot Model

Purpose

Representasi order book.

Planned Fields

- symbol
- bids
- asks
- timestamp

---

AssetBalance

Category

Snapshot Model

Purpose

Representasi saldo satu aset.

Planned Fields

- asset
- free
- locked
- total

---

Balance

Category

Snapshot Model

Purpose

Representasi seluruh saldo akun.

Planned Fields

- exchange
- assets
- equity
- available_balance
- wallet_balance
- unrealized_pnl
- timestamp

---

Order

Category

Event Model

Purpose

Representasi order.

Planned Fields

- exchange_order_id
- client_order_id
- symbol
- side
- type
- quantity
- price
- status
- filled_quantity
- average_price
- fee
- created_at
- updated_at

---

Position

Category

Snapshot Model

Purpose

Representasi posisi futures.

Planned Fields

- symbol
- side
- quantity
- entry_price
- mark_price
- liquidation_price
- leverage
- margin_mode
- unrealized_pnl
- realized_pnl
- timestamp

---

Trade

Category

Event Model

Purpose

Representasi trade yang telah selesai.

Planned Fields

- trade_id
- order_id
- symbol
- side
- entry_price
- exit_price
- quantity
- pnl
- fee
- opened_at
- closed_at

---

Signal

Category

Event Model

Purpose

Representasi sinyal BUY / SELL / HOLD.

---

TradeSetup

Category

Event Model

Purpose

Representasi rencana trading.

Mencakup:

- Entry
- Stop Loss
- Take Profit
- Risk Reward
- Confidence

---

MarketState

Category

Reference Model

Purpose

Representasi kondisi market.

Contoh:

- Trending
- Sideways
- Volatile
- Ranging

---

Indicator

Category

Reference Model

Purpose

Base class seluruh hasil indikator.

Turunan:

- TrendIndicator
- MomentumIndicator
- VolatilityIndicator
- VolumeIndicator

---

Dependency Graph

Reference Model

↓

Snapshot Model

↓

Indicator

↓

Analysis

↓

Event Model

↓

Strategy

↓

Execution

Tidak boleh terjadi circular dependency antar model.