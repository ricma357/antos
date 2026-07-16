import unittest
from datetime import datetime

import pandas as pd

from src.validation import slice_metrics, yearly_breakdown, comparison_table
from src.strategy.buy_and_hold import BuyAndHold
from src.events import MarketEvent


def equity_frame(dates, values):
    return pd.DataFrame({'Equity': values}, index=pd.to_datetime(dates))


class TestSliceMetrics(unittest.TestCase):
    def test_return_and_drawdown(self):
        df = equity_frame(
            ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            [100_000.0, 120_000.0, 90_000.0, 110_000.0],
        )
        m = slice_metrics(df)
        self.assertAlmostEqual(m['return_pct'], 10.0)
        # Peak 120k → trough 90k = -25%
        self.assertAlmostEqual(m['max_drawdown_pct'], -25.0)

    def test_flat_curve_has_zero_sharpe(self):
        df = equity_frame(["2024-01-01", "2024-01-02", "2024-01-03"],
                          [100_000.0] * 3)
        m = slice_metrics(df)
        self.assertEqual(m['sharpe'], 0.0)
        self.assertEqual(m['return_pct'], 0.0)

    def test_single_row_returns_zeros(self):
        df = equity_frame(["2024-01-01"], [100_000.0])
        self.assertEqual(slice_metrics(df)['return_pct'], 0.0)


class TestYearlyBreakdown(unittest.TestCase):
    def test_splits_by_calendar_year(self):
        df = equity_frame(
            ["2023-06-01", "2023-12-29", "2024-01-02", "2024-12-30"],
            [100_000.0, 110_000.0, 110_000.0, 99_000.0],
        )
        breakdown = yearly_breakdown(df)
        self.assertEqual(sorted(breakdown), [2023, 2024])
        self.assertAlmostEqual(breakdown[2023]['return_pct'], 10.0)
        self.assertAlmostEqual(breakdown[2024]['return_pct'], -10.0)

    def test_drawdown_resets_per_year_slice(self):
        # 2024 starts below the 2023 peak; within-2024 drawdown only
        # counts declines from 2024's own running peak.
        df = equity_frame(
            ["2023-06-01", "2023-12-29", "2024-01-02", "2024-06-03"],
            [100_000.0, 200_000.0, 150_000.0, 150_000.0],
        )
        breakdown = yearly_breakdown(df)
        self.assertAlmostEqual(breakdown[2024]['max_drawdown_pct'], 0.0)

    def test_empty_frame(self):
        self.assertEqual(yearly_breakdown(pd.DataFrame({'Equity': []})), {})


class TestComparisonTable(unittest.TestCase):
    def test_renders_full_and_yearly_rows(self):
        dates = ["2023-01-02", "2023-06-01", "2024-01-02", "2024-06-03"]
        strat = equity_frame(dates, [100_000, 110_000, 120_000, 130_000])
        bench = equity_frame(dates, [100_000, 105_000, 108_000, 112_000])
        lines = comparison_table(strat, bench)
        labels = [line.split()[0] for line in lines[2:]]
        self.assertEqual(labels, ["FULL", "2023", "2024"])


class TestBuyAndHold(unittest.TestCase):
    def _bar(self, symbol, day):
        return MarketEvent(
            timestamp=datetime(2024, 1, day), symbol=symbol,
            open_price=100.0, high_price=101.0, low_price=99.0,
            close_price=100.0, volume=1000,
        )

    def test_signals_long_once_per_symbol(self):
        strat = BuyAndHold(strength=0.5)
        s1 = strat.calculate_signals(self._bar("SPY", 2), current_qty=0)
        self.assertEqual(len(s1), 1)
        self.assertEqual(s1[0].signal_type, 'LONG')
        self.assertEqual(s1[0].strength, 0.5)
        # Same symbol again: silent forever
        s2 = strat.calculate_signals(self._bar("SPY", 3), current_qty=100)
        self.assertEqual(s2, [])
        # Different symbol gets its own entry
        s3 = strat.calculate_signals(self._bar("BTC-USD", 3), current_qty=0)
        self.assertEqual(len(s3), 1)

    def test_invalid_strength_raises(self):
        with self.assertRaises(ValueError):
            BuyAndHold(strength=0.0)
        with self.assertRaises(ValueError):
            BuyAndHold(strength=1.5)


if __name__ == "__main__":
    unittest.main()
