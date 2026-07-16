import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np

from src.strategy.rolling_ridge import RollingRidgeDirectionalPredictor
from src.events import MarketEvent


def make_bar(close, day_offset, symbol="SPY", volume=1_000_000):
    return MarketEvent(
        timestamp=datetime(2024, 1, 1) + timedelta(days=day_offset),
        symbol=symbol,
        open_price=close, high_price=close * 1.01,
        low_price=close * 0.99, close_price=close, volume=volume,
    )


def feed_series(strategy, closes, symbol="SPY", volumes=None, current_qty=0):
    """Feeds a close-price series as daily bars; returns all emitted signals."""
    signals = []
    for i, close in enumerate(closes):
        volume = volumes[i] if volumes else 1_000_000
        bar = make_bar(close, i, symbol=symbol, volume=volume)
        signals.extend(strategy.calculate_signals(bar, current_qty))
    return signals


def small_strategy(**overrides):
    """Small windows so tests warm up in ~45 bars instead of ~250."""
    params = dict(lookback_window=15, l2_lambda=1.0,
                  prediction_threshold=0.001, strength=0.5,
                  trend_filter_window=15)
    params.update(overrides)
    return RollingRidgeDirectionalPredictor(**params)


class TestDriftCapture(unittest.TestCase):
    """Steady drift must produce directional signals: with constant
    growth all features are constant, so the (deliberately shrunk)
    projection onto them must still carry the trailing-drift signal
    past the entry threshold. Guards the model's core behavior."""

    def test_steady_uptrend_goes_long(self):
        strategy = small_strategy()
        closes = [100.0 * (1.02 ** i) for i in range(60)]
        signals = feed_series(strategy, closes, current_qty=0)
        self.assertTrue(any(s.signal_type == 'LONG' for s in signals),
                        "constant +2%/day drift must trigger LONG via the intercept")

    def test_steady_downtrend_exits_in_bear_regime(self):
        strategy = small_strategy()
        closes = [100.0 * (0.98 ** i) for i in range(60)]
        signals = feed_series(strategy, closes, current_qty=1)
        self.assertTrue(any(s.signal_type == 'EXIT' for s in signals))
        self.assertFalse(any(s.signal_type == 'LONG' for s in signals),
                         "bear regime must never open new longs")


class TestNumericalRobustness(unittest.TestCase):
    def test_extreme_volume_scale_stays_finite(self):
        # Volumes in the trillions previously dominated XTX; standardization
        # must keep the solve well-conditioned and predictions finite.
        strategy = small_strategy()
        closes = [100.0 + (i % 7) - 3 + i * 0.5 for i in range(60)]
        volumes = [int(1e12 + i * 1e10) for i in range(60)]
        signals = feed_series(strategy, closes, volumes=volumes)
        for s in signals:
            self.assertIn(s.signal_type, ('LONG', 'EXIT'))

    def test_no_signals_before_warmup(self):
        strategy = small_strategy()
        closes = [100.0 * (1.02 ** i) for i in range(40)]  # < min_required
        self.assertEqual(feed_series(strategy, closes), [])


class TestWarmupFastPath(unittest.TestCase):
    def test_warmup_does_zero_ridge_fits(self):
        strategy = small_strategy()
        closes = [100.0 * (1.02 ** i) for i in range(60)]
        with patch("numpy.linalg.solve", wraps=np.linalg.solve) as solve:
            for i, close in enumerate(closes):
                strategy.warmup(make_bar(close, i))
            self.assertEqual(solve.call_count, 0,
                             "warmup must never fit the model")
            # The live bar still gets exactly one fit
            strategy.calculate_signals(make_bar(closes[-1] * 1.02, 60), 0)
            self.assertEqual(solve.call_count, 1)

    def test_warmup_then_live_bar_equals_full_replay(self):
        """The decision on the live bar must be identical whether history
        was replayed via warmup or via full calculate_signals."""
        closes = [100.0 * (1.02 ** i) for i in range(60)]
        live_close = closes[-1] * 1.02

        full = small_strategy()
        feed_series(full, closes)
        full_signals = full.calculate_signals(make_bar(live_close, 60), 0)

        fast = small_strategy()
        for i, close in enumerate(closes):
            fast.warmup(make_bar(close, i))
        fast_signals = fast.calculate_signals(make_bar(live_close, 60), 0)

        self.assertEqual(
            [(s.signal_type, s.strength) for s in full_signals],
            [(s.signal_type, s.strength) for s in fast_signals],
        )
        self.assertTrue(full_signals, "sanity: the drift series must signal")

    def test_base_class_default_warmup_delegates(self):
        from src.strategy.base import BaseStrategy
        from src.events import SignalEvent

        class Counting(BaseStrategy):
            calls = 0
            def calculate_signals(self, event, current_qty):
                self.calls += 1
                return [SignalEvent(event.symbol, event.timestamp, 'LONG', 0.5)]

        strat = Counting()
        strat.warmup(make_bar(100.0, 0))
        self.assertEqual(strat.calls, 1)


class TestHitRateDiagnostics(unittest.TestCase):
    def test_hit_rate_none_before_enough_calls(self):
        strategy = small_strategy()
        self.assertIsNone(strategy.get_hit_rate("SPY"))

    def test_perfect_hit_rate_on_steady_trend(self):
        strategy = small_strategy()
        closes = [100.0 * (1.02 ** i) for i in range(70)]
        feed_series(strategy, closes)
        hit_rate = strategy.get_hit_rate("SPY")
        self.assertIsNotNone(hit_rate)
        # Every call predicts up, every next bar is up.
        self.assertEqual(hit_rate, 1.0)

    def test_windowed_hit_rate(self):
        strategy = small_strategy()
        closes = [100.0 * (1.02 ** i) for i in range(70)]
        feed_series(strategy, closes)
        self.assertEqual(strategy.get_hit_rate("SPY", window=10), 1.0)
        self.assertIsNone(strategy.get_hit_rate("SPY", window=3),
                          "fewer than 5 calls in window is not meaningful")

    def test_hit_history_is_capped(self):
        strategy = small_strategy()
        strategy._max_hit_history = 20
        closes = [100.0 * (1.02 ** i) for i in range(120)]
        feed_series(strategy, closes)
        self.assertLessEqual(len(strategy._hit_history["SPY"]), 20)


if __name__ == "__main__":
    unittest.main()
