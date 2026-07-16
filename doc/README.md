# Antos: Project Overview

Antos is an **event-driven quantitative backtesting platform** for evaluating algorithmic trading strategies against historical market data. It includes a Python backend with a FastAPI-powered REST API, a browser-based dashboard for interactive backtesting, and a library of 6 quantitative strategies ranging from simple moving averages to machine learning models.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Download market data (requires internet)
python3 download_data.py

# Start the dashboard (API + Frontend)
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# Open browser at http://localhost:8000
```

### Docker

```bash
docker-compose up --build
# Dashboard at http://localhost:8000
```

---

## Project Structure

```
antos/
├── api/                          # FastAPI REST API
│   ├── server.py                 # App entrypoint, CORS, route registration
│   ├── models.py                 # Pydantic request/response schemas
│   └── routes/
│       ├── strategies.py         # GET /api/strategies — strategy registry
│       ├── symbols.py            # GET /api/symbols — available assets
│       └── backtest.py           # POST /api/backtest — run a backtest
│
├── src/                          # Core backtesting engine
│   ├── events.py                 # Event types: Market, Signal, Order, Fill
│   ├── data_provider.py          # CSV data loader + chronological merger
│   ├── engine.py                 # Main simulation loop + metrics calculator
│   ├── portfolio.py              # Position tracking, NAV sizing, cash clamping
│   ├── execution/
│   │   ├── base.py               # Abstract execution handler
│   │   └── sim_broker.py         # Simulated broker (slippage, commission)
│   └── strategy/
│       ├── base.py               # Abstract strategy interface
│       ├── sma_crossover.py      # SMA Golden/Death Cross
│       ├── rsi_mean_reversion.py # RSI Overbought/Oversold
│       ├── peak_breakout_pullback.py  # Donchian breakout + ATR stop
│       ├── volatility_squeeze.py      # BB squeeze + momentum breakout
│       └── rolling_ridge.py           # ML Ridge Regression (regime-aware)
│
├── frontend/                     # Browser dashboard (vanilla HTML/CSS/JS)
│   ├── index.html                # Single-page app
│   ├── css/                      # Styles
│   └── js/                       # Chart rendering (TradingView), API calls
│
├── data/                         # Market data (CSV)
│   ├── spy_daily.csv             # 2020–2026 daily data
│   ├── btc_usd_daily.csv         # 2020–2026 daily data
│   ├── ... (18 assets)
│   └── crisis/                   # 2006–2012 data for stress testing
│       ├── spy_daily.csv
│       ├── bac_daily.csv
│       └── ... (11 assets)
│
├── doc/                          # Documentation (this directory)
├── compare_strategies.py         # Multi-strategy comparison + chart generator
├── download_data.py              # yfinance data fetcher
├── run_backtest.py               # CLI backtest runner
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Python 3.10 slim container
└── docker-compose.yml            # Container orchestration
```

---

## Architecture

The system follows an **event-driven simulation pattern**. Each bar is processed sequentially through a strict pipeline that prevents lookahead bias:

```
┌──────────────────┐
│ CSV Data Provider │ ── streams MarketEvent ──►
└──────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────┐
│                BacktestEngine Loop                  │
│                                                     │
│  1. Process pending orders at TODAY's Open price    │
│     └─► SimulatedBroker fills → FillEvent           │
│     └─► Portfolio updates cash/positions            │
│                                                     │
│  2. Mark-to-market at TODAY's Close price            │
│     └─► Portfolio records equity snapshot            │
│                                                     │
│  3. Strategy evaluates current bar                   │
│     └─► Generates SignalEvent (LONG/SHORT/EXIT)     │
│                                                     │
│  4. Portfolio sizes + queues OrderEvent              │
│     └─► Queued for TOMORROW's Open execution        │
└────────────────────────────────────────────────────┘
```

### Key Design Decisions
- **Orders execute at next bar's Open** — eliminates the lookahead bias present in most retail backtesters
- **NAV-based position sizing** — allocation scales with portfolio growth, not fixed-dollar amounts
- **Cash clamping** — strict cash-account model, no margin borrowing
- **Multi-asset support** — events from different assets are merged chronologically with deterministic tie-breaking by symbol name

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/strategies` | Returns all registered strategies with parameter schemas |
| `GET` | `/api/symbols` | Returns available asset tickers from the data directory |
| `POST` | `/api/backtest` | Runs a backtest and returns equity curve, metrics, trade log |

### Backtest Request Schema

```json
{
  "strategy_id": "rolling_ridge",
  "symbols": ["SPY", "BTC-USD"],
  "initial_cash": 100000.0,
  "commission_rate": 0.001,
  "slippage_rate": 0.0005,
  "risk_free_rate": 0.0,
  "params": {
    "lookback_window": 90,
    "l2_lambda": 1.0,
    "prediction_threshold": 0.001,
    "strength": 0.50,
    "trend_filter_window": 200
  }
}
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `pandas` | Data manipulation, equity curve construction |
| `numpy` | Linear algebra (Ridge Regression solver) |
| `yfinance` | Historical market data download |
| `matplotlib` | Chart generation (comparison plots) |
| `fastapi` | REST API framework |
| `uvicorn` | ASGI server |

---

## Available Data

### Current Period (2020–2026)
SPY, BTC-USD, ETH-USD, AAPL, AMZN, AMD, COIN, DIS, GOOGL, JPM, META, MSFT, NFLX, NVDA, TSLA, V

### Crisis Period (2006–2012)
SPY, BAC, GLD, AAPL, AMZN, GOOGL, GS, JPM, MSFT, QQQ, XLF

Data is downloaded via `download_data.py` using the `yfinance` API.
