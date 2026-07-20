import unittest
from datetime import datetime

import pandas as pd

from src.validation import (
    slice_metrics,
    yearly_breakdown,
    comparison_table,
    alpha_beta,
    edge_decay,
    TRADING_DAYS,
)
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


def curve_from_returns(returns, start=100_000.0):
    """Builds an equity DataFrame from a list of daily returns."""
    dates = pd.bdate_range("2023-01-02", periods=len(returns) + 1)
    values = [start]
    for r in returns:
        values.append(values[-1] * (1 + r))
    return pd.DataFrame({'Equity': values}, index=dates)


class TestAlphaBeta(unittest.TestCase):
    def test_identical_curves_beta_one_alpha_zero(self):
        rb = [0.01, -0.01, 0.02, -0.005] * 20
        bench = curve_from_returns(rb)
        strat = curve_from_returns(rb)
        stats = alpha_beta(strat, bench)
        self.assertAlmostEqual(stats['beta'], 1.0, places=6)
        self.assertAlmostEqual(stats['alpha_ann_pct'], 0.0, places=6)
        self.assertAlmostEqual(stats['correlation'], 1.0, places=6)

    def test_half_beta_plus_drift_recovered(self):
        rb = [0.01, -0.01, 0.02, -0.005] * 20
        drift = 0.0004
        rs = [0.5 * r + drift for r in rb]
        stats = alpha_beta(curve_from_returns(rs), curve_from_returns(rb))
        self.assertAlmostEqual(stats['beta'], 0.5, places=6)
        self.assertAlmostEqual(stats['alpha_ann_pct'],
                               drift * TRADING_DAYS * 100, places=4)

    def test_uncorrelated_strategy_low_r_squared(self):
        rb = ([0.01, -0.01] * 40)
        rs = ([0.0, 0.0, 0.01, -0.01] * 20)  # different rhythm
        stats = alpha_beta(curve_from_returns(rs), curve_from_returns(rb))
        self.assertLess(abs(stats['beta']), 0.6)
        self.assertLess(stats['r_squared'], 0.5)

    def test_flat_benchmark_guarded(self):
        bench = curve_from_returns([0.0] * 80)
        strat = curve_from_returns([0.01, -0.01] * 40)
        stats = alpha_beta(strat, bench)
        self.assertEqual(stats['beta'], 0.0)

    def test_too_few_days_returns_zeros(self):
        bench = curve_from_returns([0.01] * 5)
        stats = alpha_beta(bench, bench)
        self.assertEqual(stats['n_days'], 5)
        self.assertEqual(stats['beta'], 0.0)


class TestEdgeDecay(unittest.TestCase):
    def test_decaying_alpha_visible_in_halves(self):
        rb = [0.01, -0.01] * 60
        # Drift only in the first half — a "signal that got arbitraged away"
        rs = [r + (0.001 if i < 60 else 0.0) for i, r in enumerate(rb)]
        halves = edge_decay(curve_from_returns(rs), curve_from_returns(rb))
        self.assertEqual(len(halves), 2)
        self.assertGreater(halves[0]['alpha_ann_pct'],
                           halves[1]['alpha_ann_pct'] + 5.0)

    def test_short_sample_returns_empty(self):
        bench = curve_from_returns([0.01] * 10)
        self.assertEqual(edge_decay(bench, bench), [])


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
