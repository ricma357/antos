import os
import tempfile
import unittest
from typing import List

from src.engine import BacktestEngine
from src.execution.sim_broker import SimulatedBroker
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent


class ScriptedStrategy(BaseStrategy):
    """Emits a pre-scripted signal on the Nth bar it sees. Deterministic."""

    def __init__(self, script):
        # script: {bar_index: (signal_type, strength)}
        self.script = script
        self.bar_count = 0

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        signals = []
        if self.bar_count in self.script:
            sig_type, strength = self.script[self.bar_count]
            signals.append(SignalEvent(
                symbol=event.symbol, timestamp=event.timestamp,
                signal_type=sig_type, strength=strength,
            ))
        self.bar_count += 1
        return signals


def write_bars(data_dir, symbol, bars):
    """bars: list of (date, open, high, low, close) tuples."""
    safe = symbol.lower().replace("-", "_")
    with open(os.path.join(data_dir, f"{safe}_daily.csv"), "w") as f:
        f.write("Date,Open,High,Low,Close,Volume\n")
        for date, o, h, l, c in bars:
            f.write(f"{date},{o},{h},{l},{c},1000000\n")


class TestBacktestEngine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, bars, script, initial_cash=100_000.0,
             commission=0.0, slippage=0.0):
        write_bars(self.data_dir, "SPY", bars)
        engine = BacktestEngine(
            data_dir=self.data_dir,
            symbols=["SPY"],
            initial_cash=initial_cash,
            strategy=ScriptedStrategy(script),
            execution_handler=SimulatedBroker(commission_rate=commission,
                                              slippage_rate=slippage),
        )
        return engine.run("Test Strategy")

    def test_order_fills_at_next_bar_open_no_lookahead(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),   # bar 0: LONG signal at close
            ("2024-01-03", 105, 106, 104, 105),  # bar 1: fill must be at THIS open
            ("2024-01-04", 110, 111, 109, 110),
        ]
        result = self._run(bars, {0: ("LONG", 0.5)})
        self.assertEqual(len(result.trade_log), 1)
        fill = result.trade_log[0]
        # Sized off bar-0 close ($100): 100k * 0.5 / 100 = 500 shares,
        # but filled at bar-1 open ($105) — proving no lookahead.
        self.assertEqual(fill["quantity"], 500)
        self.assertEqual(fill["fill_price"], 105.0)
        self.assertEqual(fill["direction"], "BUY")

    def test_round_trip_profit_reflected_in_final_balance(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),   # LONG signal
            ("2024-01-03", 100, 101, 99, 100),   # buy 500 @ 100
            ("2024-01-04", 120, 121, 119, 120),  # EXIT signal at close
            ("2024-01-05", 120, 121, 119, 120),  # sell 500 @ 120
        ]
        result = self._run(bars, {0: ("LONG", 0.5), 2: ("EXIT", 0.5)})
        self.assertEqual(len(result.trade_log), 2)
        # Profit: 500 shares * $20 = $10,000 (zero fees)
        self.assertAlmostEqual(result.metrics["final_balance"], 110_000.0)
        self.assertAlmostEqual(result.metrics["total_return_pct"], 10.0)

    def test_commission_and_slippage_reduce_returns(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),
            ("2024-01-03", 100, 101, 99, 100),
            ("2024-01-04", 100, 101, 99, 100),
            ("2024-01-05", 100, 101, 99, 100),
        ]
        result = self._run(bars, {0: ("LONG", 0.5), 2: ("EXIT", 0.5)},
                           commission=0.001, slippage=0.0005)
        # Flat market round trip → final balance strictly below initial
        self.assertLess(result.metrics["final_balance"], 100_000.0)

    def test_no_signals_means_no_trades_flat_equity(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),
            ("2024-01-03", 105, 106, 104, 105),
        ]
        result = self._run(bars, {})
        self.assertEqual(result.metrics["num_trades"], 0)
        self.assertAlmostEqual(result.metrics["final_balance"], 100_000.0)
        self.assertAlmostEqual(result.metrics["max_drawdown_pct"], 0.0)
        self.assertEqual(result.metrics["sharpe"], 0.0)

    def test_equity_df_structure(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),
            ("2024-01-03", 105, 106, 104, 105),
            ("2024-01-04", 110, 111, 109, 110),
        ]
        result = self._run(bars, {0: ("LONG", 0.5)})
        df = result.equity_df
        self.assertEqual(len(df), 3)  # one row per trading day
        for col in ["Cash", "Holdings", "Equity", "Peak", "Drawdown", "DailyReturn"]:
            self.assertIn(col, df.columns)
        # Equity must equal Cash + Holdings on every row
        self.assertTrue(((df["Cash"] + df["Holdings"]) - df["Equity"]).abs().max() < 1e-9)

    def test_drawdown_computed_from_peak(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),   # LONG signal
            ("2024-01-03", 100, 101, 99, 100),   # buy 1000 @ 100 (full NAV)
            ("2024-01-04", 120, 121, 119, 120),  # peak: equity 120k
            ("2024-01-05", 90, 91, 89, 90),      # trough: equity 90k
        ]
        result = self._run(bars, {0: ("LONG", 1.0)})
        # Drawdown from 120k peak to 90k = -25%
        self.assertAlmostEqual(result.metrics["max_drawdown_pct"], -25.0)

    def test_win_rate_winning_round_trip(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),   # LONG signal
            ("2024-01-03", 100, 101, 99, 100),   # buy @ 100
            ("2024-01-04", 120, 121, 119, 120),  # EXIT signal
            ("2024-01-05", 120, 121, 119, 120),  # sell @ 120 → profit
        ]
        result = self._run(bars, {0: ("LONG", 0.5), 2: ("EXIT", 0.5)})
        self.assertEqual(result.metrics["num_round_trips"], 1)
        self.assertAlmostEqual(result.metrics["win_rate_pct"], 100.0)

    def test_win_rate_losing_round_trip(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),
            ("2024-01-03", 100, 101, 99, 100),   # buy @ 100
            ("2024-01-04", 80, 81, 79, 80),      # EXIT signal
            ("2024-01-05", 80, 81, 79, 80),      # sell @ 80 → loss
        ]
        result = self._run(bars, {0: ("LONG", 0.5), 2: ("EXIT", 0.5)})
        self.assertEqual(result.metrics["num_round_trips"], 1)
        self.assertAlmostEqual(result.metrics["win_rate_pct"], 0.0)

    def test_win_rate_mixed_trips(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),   # LONG signal
            ("2024-01-03", 100, 101, 99, 100),   # buy @ 100
            ("2024-01-04", 120, 121, 119, 120),  # EXIT signal
            ("2024-01-05", 120, 121, 119, 120),  # sell @ 120 → WIN
            ("2024-01-08", 120, 121, 119, 120),  # LONG signal
            ("2024-01-09", 120, 121, 119, 120),  # buy @ 120
            ("2024-01-10", 100, 101, 99, 100),   # EXIT signal
            ("2024-01-11", 100, 101, 99, 100),   # sell @ 100 → LOSS
        ]
        result = self._run(bars, {
            0: ("LONG", 0.5), 2: ("EXIT", 0.5),
            4: ("LONG", 0.5), 6: ("EXIT", 0.5),
        })
        self.assertEqual(result.metrics["num_round_trips"], 2)
        self.assertAlmostEqual(result.metrics["win_rate_pct"], 50.0)

    def test_win_rate_breakeven_price_with_fees_is_loss(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),
            ("2024-01-03", 100, 101, 99, 100),   # buy @ ~100 + fees
            ("2024-01-04", 100, 101, 99, 100),   # EXIT signal
            ("2024-01-05", 100, 101, 99, 100),   # sell @ ~100 - fees
        ]
        result = self._run(bars, {0: ("LONG", 0.5), 2: ("EXIT", 0.5)},
                           commission=0.001, slippage=0.0005)
        self.assertEqual(result.metrics["num_round_trips"], 1)
        self.assertAlmostEqual(result.metrics["win_rate_pct"], 0.0)

    def test_open_position_is_not_a_round_trip(self):
        bars = [
            ("2024-01-02", 100, 101, 99, 100),   # LONG signal
            ("2024-01-03", 100, 101, 99, 100),   # buy — never exited
        ]
        result = self._run(bars, {0: ("LONG", 0.5)})
        self.assertEqual(result.metrics["num_round_trips"], 0)
        self.assertEqual(result.metrics["win_rate_pct"], 0.0)

    def test_multi_asset_engine_run(self):
        write_bars(self.data_dir, "AAPL", [
            ("2024-01-02", 50, 51, 49, 50),
            ("2024-01-03", 50, 51, 49, 50),
        ])
        bars = [
            ("2024-01-02", 100, 101, 99, 100),
            ("2024-01-03", 100, 101, 99, 100),
        ]
        write_bars(self.data_dir, "SPY", bars)
        engine = BacktestEngine(
            data_dir=self.data_dir,
            symbols=["SPY", "AAPL"],
            initial_cash=100_000.0,
            strategy=ScriptedStrategy({}),
            execution_handler=SimulatedBroker(0.0, 0.0),
        )
        result = engine.run("Multi Asset")
        # Duplicate daily timestamps collapse to one equity row per day
        self.assertEqual(len(result.equity_df), 2)


if __name__ == "__main__":
    unittest.main()
