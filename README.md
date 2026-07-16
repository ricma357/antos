# Antos

An **event-driven quantitative backtesting platform** for evaluating algorithmic trading strategies against historical market data — with a FastAPI REST API, a browser dashboard, and a paper-trading bot scheduled around US market hours.

## Quick Start

```bash
pip install -r requirements.txt
python3 download_data.py   # fetch market data (requires internet)
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
# Open http://localhost:8000
```

Or with Docker:

```bash
docker-compose up --build
```

## Documentation

Full documentation lives in [`doc/`](doc/README.md):

- [Project overview & architecture](doc/README.md)
- [Engine architecture](doc/architecture.md)
- [Strategy library](doc/strategies.md)
- [Paper trading](doc/paper_trading.md)
- [Performance report](doc/performance_report.md)
- [System analysis](doc/system_analysis.md)

## Highlights

- **No lookahead bias** — orders queue on signal day and fill at the *next* bar's Open
- **NAV-based position sizing** with strict cash-account clamping (no margin)
- **Multi-asset backtests** — chronological event merging across symbols
- **5 strategies** — SMA crossover, RSI mean reversion, Donchian breakout + ATR stop, volatility squeeze, and a regime-aware rolling Ridge Regression model
- **Live paper trading** — market-clock scheduler (09:40 / 15:50 ET ticks), trade journal, notifications
