import unittest
import time
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from src.scheduler import BotScheduler, MarketClockScheduler, EST

# ─── Legacy BotScheduler Tests ───────────────────────────────────────────────

class TestBotScheduler(unittest.TestCase):
    def test_scheduler_ticks_and_stops(self):
        ticks = []
        def tick_callback():
            ticks.append(time.time())

        # Create a fast 0.1s interval scheduler for validation
        scheduler = BotScheduler(tick_callback, 0.1)
        
        scheduler.start()
        time.sleep(0.35)  # Wait for at least 3 triggers
        scheduler.stop()
        
        # Verify it doesn't tick after stop
        current_ticks = len(ticks)
        time.sleep(0.2)
        self.assertEqual(len(ticks), current_ticks)
        self.assertTrue(current_ticks >= 2)

# ─── MarketClockScheduler.next_run_time() Tests ─────────────────────────────

class TestMarketClockNextRunTime(unittest.TestCase):
    """
    Tests the pure-function scheduling logic in isolation.
    Each test constructs a specific Eastern Time datetime and asserts the 
    computed next target run time.
    """

    def _est(self, y, m, d, h, mi, s=0):
        """Helper to construct a timezone-aware EST datetime."""
        return datetime(y, m, d, h, mi, s, tzinfo=EST)

    # ── Weekday: Before Market Open ──────────────────────────────────────

    def test_weekday_before_open(self):
        """Monday 07:00 ET → should target Monday 09:40 ET."""
        dt = self._est(2026, 6, 29, 7, 0)  # Monday 7:00 AM
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 6, 29, 9, 40)
        self.assertEqual(result, expected)

    def test_weekday_early_morning(self):
        """Wednesday 00:30 ET → should target Wednesday 09:40 ET."""
        dt = self._est(2026, 7, 1, 0, 30)  # Wednesday 12:30 AM
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 7, 1, 9, 40)
        self.assertEqual(result, expected)

    # ── Weekday: Between Open and Close ──────────────────────────────────

    def test_weekday_between_open_and_close(self):
        """Monday 12:00 ET → should target Monday 15:50 ET."""
        dt = self._est(2026, 6, 29, 12, 0)
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 6, 29, 15, 50)
        self.assertEqual(result, expected)

    def test_weekday_right_after_open_tick(self):
        """Tuesday 09:41 ET → should target Tuesday 15:50 ET."""
        dt = self._est(2026, 6, 30, 9, 41)
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 6, 30, 15, 50)
        self.assertEqual(result, expected)

    def test_weekday_at_exactly_open(self):
        """Tuesday 09:40 ET → should target Tuesday 15:50 ET (open tick already due)."""
        dt = self._est(2026, 6, 30, 9, 40)
        result = MarketClockScheduler.next_run_time(dt)
        # At the exact open target, we should advance to close
        expected = self._est(2026, 6, 30, 15, 50)
        self.assertEqual(result, expected)

    # ── Weekday: After Market Close ──────────────────────────────────────

    def test_weekday_after_close(self):
        """Monday 18:00 ET → should target Tuesday 09:40 ET."""
        dt = self._est(2026, 6, 29, 18, 0)
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 6, 30, 9, 40)
        self.assertEqual(result, expected)

    def test_weekday_right_after_close_tick(self):
        """Thursday 15:51 ET → should target Friday 09:40 ET."""
        dt = self._est(2026, 7, 2, 15, 51)
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 7, 3, 9, 40)  # Friday
        self.assertEqual(result, expected)

    # ── Friday Evening → Monday ──────────────────────────────────────────

    def test_friday_after_close(self):
        """Friday 16:30 ET → should target Monday 09:40 ET."""
        dt = self._est(2026, 7, 3, 16, 30)  # Friday
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 7, 6, 9, 40)  # Monday
        self.assertEqual(result, expected)

    # ── Weekend ──────────────────────────────────────────────────────────

    def test_saturday_morning(self):
        """Saturday 10:00 ET → should target Monday 09:40 ET."""
        dt = self._est(2026, 7, 4, 10, 0)  # Saturday
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 7, 6, 9, 40)  # Monday
        self.assertEqual(result, expected)

    def test_sunday_evening(self):
        """Sunday 21:00 ET → should target Monday 09:40 ET."""
        dt = self._est(2026, 7, 5, 21, 0)  # Sunday
        result = MarketClockScheduler.next_run_time(dt)
        expected = self._est(2026, 7, 6, 9, 40)  # Monday
        self.assertEqual(result, expected)


# ─── MarketClockScheduler.tick_phase() Tests ─────────────────────────────────

class TestMarketClockTickPhase(unittest.TestCase):
    def _est(self, y, m, d, h, mi, s=0):
        return datetime(y, m, d, h, mi, s, tzinfo=EST)

    def test_morning_is_open(self):
        dt = self._est(2026, 6, 29, 9, 40)
        self.assertEqual(MarketClockScheduler.tick_phase(dt), "OPEN")

    def test_afternoon_is_close(self):
        dt = self._est(2026, 6, 29, 15, 50)
        self.assertEqual(MarketClockScheduler.tick_phase(dt), "CLOSE")

    def test_11am_is_open(self):
        dt = self._est(2026, 6, 29, 11, 59)
        self.assertEqual(MarketClockScheduler.tick_phase(dt), "OPEN")

    def test_noon_is_close(self):
        dt = self._est(2026, 6, 29, 12, 0)
        self.assertEqual(MarketClockScheduler.tick_phase(dt), "CLOSE")


# ─── MarketClockScheduler Start/Stop Tests ───────────────────────────────────

class TestMarketClockSchedulerLifecycle(unittest.TestCase):
    def test_start_and_stop(self):
        ticks = []
        def callback():
            ticks.append(time.time())

        scheduler = MarketClockScheduler(callback)
        self.assertFalse(scheduler.is_active())
        self.assertTrue(scheduler.start())
        self.assertTrue(scheduler.is_active())

        # Give the thread a moment to compute next_run_time
        time.sleep(0.2)

        # Verify next_run is populated
        next_run = scheduler.get_next_run_iso()
        self.assertIsNotNone(next_run)

        scheduler.stop()
        time.sleep(0.1)
        self.assertFalse(scheduler.is_active())

    def test_double_start_returns_false(self):
        scheduler = MarketClockScheduler(lambda: None)
        self.assertTrue(scheduler.start())
        self.assertFalse(scheduler.start())
        scheduler.stop()


if __name__ == "__main__":
    unittest.main()
