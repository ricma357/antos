import os
import json
import tempfile
import unittest
from typing import List
from unittest.mock import patch

from src.live_bot import (
    LiveBotService,
    BotAlreadyActive,
    BotInactive,
    CredentialsMissing,
    DataNotFound,
    calculate_metrics,
)
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent


class AlwaysLongStrategy(BaseStrategy):
    """Goes LONG on every bar while flat. Deterministic and history-agnostic."""

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        if current_qty == 0:
            return [SignalEvent(symbol=event.symbol, timestamp=event.timestamp,
                                signal_type="LONG", strength=0.5)]
        return []


def write_bars(data_dir, symbol, n_days=30, price=100.0):
    safe = symbol.lower().replace("-", "_")
    with open(os.path.join(data_dir, f"{safe}_daily.csv"), "w") as f:
        f.write("Date,Open,High,Low,Close,Volume\n")
        for day in range(1, n_days + 1):
            f.write(f"2024-01-{day:02d},{price},{price + 1},{price - 1},{price},1000000\n")


class LiveBotServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = self._tmp.name
        self.state_file = os.path.join(self.data_dir, "state", "live_bot_state.json")
        write_bars(self.data_dir, "SPY")
        self.service = LiveBotService(
            data_dir=self.data_dir,
            state_file=self.state_file,
            strategy_factory=lambda sid, params: AlwaysLongStrategy(),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _start(self, **overrides):
        kwargs = dict(strategy_id="test", symbols=["SPY"], initial_cash=100_000.0)
        kwargs.update(overrides)
        return self.service.start(**kwargs)


class TestLifecycle(LiveBotServiceTestCase):
    def test_start_initializes_state(self):
        state = self._start()
        self.assertTrue(state["active"])
        self.assertEqual(state["symbols"], ["SPY"])
        self.assertEqual(state["cash"], 100_000.0)
        self.assertTrue(os.path.exists(self.state_file))

    def test_double_start_raises(self):
        self._start()
        with self.assertRaises(BotAlreadyActive):
            self._start()

    def test_start_unknown_symbol_raises(self):
        with self.assertRaises(DataNotFound):
            self._start(symbols=["TSLA"])

    def test_alpaca_without_env_credentials_raises(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ALPACA_API_KEY", "ALPACA_API_SECRET")}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(CredentialsMissing):
                self._start(broker_type="alpaca")

    def test_stop_deactivates_and_freezes(self):
        self._start()
        state = self.service.stop()
        self.assertFalse(state["active"])

    def test_reset_restores_default_state(self):
        self._start()
        self.service.tick()
        state = self.service.reset()
        self.assertFalse(state["active"])
        self.assertEqual(state["trade_log"], [])
        self.assertEqual(state["cash"], 100_000.0)

    def test_legacy_credentials_scrubbed_on_load(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        legacy = self.service.default_state()
        legacy["alpaca_api_key"] = "SHOULD-BE-REMOVED"
        legacy["alpaca_api_secret"] = "SHOULD-BE-REMOVED"
        with open(self.state_file, "w") as f:
            json.dump(legacy, f)
        state = self.service.load_state()
        self.assertNotIn("alpaca_api_key", state)
        self.assertNotIn("alpaca_api_secret", state)


class TestTick(LiveBotServiceTestCase):
    def test_tick_when_inactive_raises(self):
        with self.assertRaises(BotInactive):
            self.service.tick()

    def test_first_tick_queues_order_second_tick_fills_it(self):
        self._start()
        state1 = self.service.tick()
        # Signal generated on tick 1 → order queued, not yet filled
        self.assertEqual(len(state1["pending_orders"]), 1)
        self.assertEqual(state1["trade_log"], [])

        state2 = self.service.tick()
        # Order fills at next day's open on tick 2
        self.assertEqual(len(state2["trade_log"]), 1)
        fill = state2["trade_log"][0]
        self.assertEqual(fill["direction"], "BUY")
        self.assertEqual(fill["symbol"], "SPY")
        self.assertGreater(state2["positions"]["SPY"]["qty"], 0)
        self.assertLess(state2["cash"], 100_000.0)

    def test_tick_advances_index_and_extends_equity_curve(self):
        self._start()
        before = self.service.status()["current_index"]
        state = self.service.tick()
        self.assertEqual(state["current_index"], before + 1)
        self.assertEqual(len(state["equity_curve"]), 2)  # initial point + tick

    def test_bot_halts_at_data_boundary(self):
        self._start()
        state = self.service.status()
        state["current_index"] = 10_000  # beyond available data
        self.service.save_state(state)
        result = self.service.tick()
        self.assertFalse(result["active"])


class TestCalculateMetrics(unittest.TestCase):
    def test_metrics_from_equity_curve(self):
        state = {
            "initial_cash": 100_000.0,
            "trade_log": [
                {"direction": "SELL", "realized_pnl": 500.0},
                {"direction": "SELL", "realized_pnl": -200.0},
            ],
            "equity_curve": [
                {"time": "2024-01-01", "value": 100_000.0, "drawdown": 0.0},
                {"time": "2024-01-02", "value": 110_000.0, "drawdown": 0.0},
                {"time": "2024-01-03", "value": 104_500.0, "drawdown": -0.05},
            ],
        }
        m = calculate_metrics(state)
        self.assertAlmostEqual(m["total_return_pct"], 4.5)
        self.assertAlmostEqual(m["max_drawdown_pct"], -5.0)
        self.assertAlmostEqual(m["win_rate_pct"], 50.0)
        self.assertAlmostEqual(m["profit_factor"], 2.5)
        self.assertEqual(m["num_trades"], 2)

    def test_empty_equity_curve_returns_existing_metrics(self):
        state = {"equity_curve": [], "metrics": {"sharpe": 1.23}}
        self.assertEqual(calculate_metrics(state), {"sharpe": 1.23})


if __name__ == "__main__":
    unittest.main()
