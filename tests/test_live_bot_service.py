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


class FlipFlopStrategy(BaseStrategy):
    """LONG when flat, EXIT when long — pathological churn generator.

    Re-evaluated on the same bar after each fill, this strategy would trade
    forever: LONG fills → EXIT queued → EXIT fills → LONG queued → ...
    Exactly the duplicate-order pathology observed in the live ledger.
    """

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        signal_type = "EXIT" if current_qty > 0 else "LONG"
        return [SignalEvent(symbol=event.symbol, timestamp=event.timestamp,
                            signal_type=signal_type, strength=0.5)]


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
        self.strategy_cls = AlwaysLongStrategy  # tests may override before ticking
        self.service = LiveBotService(
            data_dir=self.data_dir,
            state_file=self.state_file,
            strategy_factory=lambda sid, params: self.strategy_cls(),
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


class TestSameBarIdempotency(LiveBotServiceTestCase):
    """Live mode delivers the same daily candle on every scheduler tick
    (open, close, catch-ups). Signals must be evaluated once per bar."""

    def _live_bar(self):
        from datetime import datetime
        return MarketEvent(
            timestamp=datetime(2024, 2, 1), symbol="SPY",
            open_price=100.0, high_price=101.0, low_price=99.0,
            close_price=100.0, volume=1_000_000,
        )

    def test_repeated_live_bar_does_not_churn_orders(self):
        self.strategy_cls = FlipFlopStrategy
        with patch("src.live_bot.LiveDataProvider") as MockProvider:
            MockProvider.return_value.get_latest_bars.return_value = [self._live_bar()]
            self._start(live_mode=True)

            state1 = self.service.tick()  # evaluates bar → queues LONG
            self.assertEqual(len(state1["pending_orders"]), 1)
            self.assertEqual(state1["trade_log"], [])
            self.assertEqual(state1["last_signal_date"], "2024-02-01")

            state2 = self.service.tick()  # same bar: fills, must NOT re-signal
            self.assertEqual(len(state2["trade_log"]), 1)
            self.assertEqual(state2["pending_orders"], [])

            state3 = self.service.tick()  # same bar again: fully idempotent
            self.assertEqual(len(state3["trade_log"]), 1)
            self.assertEqual(state3["pending_orders"], [])

    def test_new_bar_date_is_evaluated_again(self):
        self.strategy_cls = AlwaysLongStrategy
        with patch("src.live_bot.LiveDataProvider") as MockProvider:
            MockProvider.return_value.get_latest_bars.return_value = [self._live_bar()]
            self._start(live_mode=True)
            self.service.tick()  # queues LONG for Feb 1

            # Next trading day's candle arrives
            from datetime import datetime
            next_bar = MarketEvent(
                timestamp=datetime(2024, 2, 2), symbol="SPY",
                open_price=102.0, high_price=103.0, low_price=101.0,
                close_price=102.0, volume=1_000_000,
            )
            MockProvider.return_value.get_latest_bars.return_value = [next_bar]
            state = self.service.tick()
            # Feb 1 order filled at Feb 2 open, and Feb 2 was evaluated
            self.assertEqual(len(state["trade_log"]), 1)
            self.assertEqual(state["last_signal_date"], "2024-02-02")


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
