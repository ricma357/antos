# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

Antos — an event-driven quantitative backtesting platform with a FastAPI REST API, a vanilla-JS browser dashboard, and a paper/live trading bot scheduled around US market hours. Full docs in `doc/` (start with `doc/README.md`).

## Commands

```bash
# Environment (Python 3.12 venv already exists at .venv/)
.venv/bin/pip install -r requirements-dev.txt

# Run all tests (fast, ~2s)
.venv/bin/python -m pytest tests/ -q

# Run the dashboard (API + frontend at http://localhost:8000)
.venv/bin/uvicorn api.server:app --port 8000 --reload

# CLI backtest / multi-strategy comparison (charts saved to data/)
.venv/bin/python run_backtest.py
.venv/bin/python compare_strategies.py
```

CI: GitHub Actions runs pytest on Python 3.10 and 3.12 on every push/PR to `main`.

## Architecture

Event-driven simulation: `MarketEvent → Strategy → SignalEvent → Portfolio → OrderEvent → Broker → FillEvent → Portfolio`.

Per-bar order in `BacktestEngine.run()` is load-bearing for lookahead-bias prevention — do not reorder:
1. Fill *yesterday's* queued orders at *today's* Open (`SimulatedBroker.process_market_event`)
2. Mark-to-market at today's Close (`Portfolio.update_market_price`)
3. Strategy evaluates today's bar → signals
4. Signals are sized and queued for *tomorrow's* Open

Key modules:
- `src/engine.py` — event loop + metrics (Sharpe/Sortino/Calmar, round-trip win rate)
- `src/portfolio.py` — NAV-based sizing; strict cash account: BUY quantities clamped to free cash, SHORT notional must be fully collateralized by free cash
- `src/execution/sim_broker.py` — next-open fills, slippage, commission; `paper_broker.py` — Alpaca paper API
- `src/strategy/` — strategies subclass `BaseStrategy.calculate_signals(event, current_qty)`
- `src/data_provider.py` — CSV loader; events sorted by `(timestamp, symbol)` for deterministic multi-asset merging
- `api/routes/bot.py` — live bot endpoints; state persisted to `data/live_bot_state.json`
- `src/scheduler.py` — `MarketClockScheduler` fires 09:40 & 15:50 ET, wall-clock polling to survive laptop sleep

## Conventions

- Tests use `unittest` style (run via pytest); new tests follow the patterns in `tests/test_engine.py` (tmp-dir CSV fixtures + `ScriptedStrategy`)
- Output goes through `logging` — never `print()`. Per-fill detail is DEBUG; summaries are INFO. CLI scripts call `logging.basicConfig`.
- **Never accept or persist broker credentials via the API or state file.** Alpaca credentials come only from `ALPACA_API_KEY` / `ALPACA_API_SECRET` / `ALPACA_BASE_URL` environment variables.
- CSV naming: `{symbol.lower().replace('-', '_')}_daily.csv` in `data/` (crisis-era data in `data/crisis/`)
- Strategy params are exposed to the UI via `AVAILABLE_STRATEGIES` in `api/routes/strategies.py` — new strategies must be registered there
