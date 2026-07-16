import unittest
from datetime import datetime, timedelta

from src.strategy.rolling_ridge import RollingRidgeDirectionalPredictor
from src.events import MarketEvent


def feed_series(strategy, closes, symbol="SPY", volumes=None, current_qty=0):
    """Feeds a close-price series as daily bars; returns all emitted signals."""
    signals = []
    start = datetime(2024, 1, 1)
    for i, close in enumerate(closes):
        volume = volumes[i] if volumes else 1_000_000
        bar = MarketEvent(
            timestamp=start + timedelta(days=i), symbol=symbol,
            open_price=close, high_price=close * 1.01,
            low_price=close * 0.99, close_price=close, volume=volume,
        )
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
