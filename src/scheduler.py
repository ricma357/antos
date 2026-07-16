import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# US Eastern timezone for NYSE/NASDAQ market hours
EST = ZoneInfo("America/New_York")

# Market session targets (Eastern Time)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 40   # 10 minutes after the 9:30 bell
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 50  # 10 minutes before the 4:00 close


class BotScheduler:
    """
    Legacy interval-based scheduler retained for backward compatibility.
    Executes callback at a fixed interval (in seconds).
    """

    def __init__(self, callback: Callable[[], None], interval_seconds: float = 3600.0):
        self.callback = callback
        self.interval = interval_seconds
        self._thread: threading.Thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._last_run: float = 0.0

    def start(self) -> bool:
        with self._lock:
            if self._running:
                logger.warning("Scheduler is already running.")
                return False
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, name="AntosSchedulerThread", daemon=True)
            self._thread.start()
            logger.info(f"Scheduler started with interval of {self.interval} seconds.")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                logger.warning("Scheduler is not running.")
                return False
            self._stop_event.set()
            self._running = False
            logger.info("Scheduler stop signal set.")
            return True

    def is_active(self) -> bool:
        with self._lock:
            return self._running

    def set_interval(self, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("Interval must be positive.")
        with self._lock:
            self.interval = interval_seconds
            logger.info(f"Scheduler interval updated to {self.interval} seconds.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            logger.info("Scheduler triggering bot tick callback.")
            start_time = time.time()
            try:
                self.callback()
            except Exception as ex:
                logger.error(f"Error executing scheduler tick callback: {ex}", exc_info=True)
            self._last_run = time.time()
            elapsed = time.time() - start_time
            sleep_time = max(0.1, self.interval - elapsed)
            if self._stop_event.wait(sleep_time):
                break
        logger.info("Scheduler background thread terminated.")


class MarketClockScheduler:
    """
    Timezone-aware market-hours scheduler that fires exactly twice per US trading day:
      1. Market Open tick  — 09:40 AM Eastern (10 min after open bell)
      2. Market Close tick — 03:50 PM Eastern (10 min before close bell)

    Automatically skips weekends (Sat/Sun). Sleeps precisely until the next
    target wall-clock time using America/New_York timezone math.
    """

    # Short poll interval (seconds) for wall-clock checks.
    # threading.Event.wait() uses the monotonic clock, which PAUSES during
    # macOS system sleep.  By polling every 30 s and comparing the real
    # wall-clock (datetime.now), we guarantee the tick fires within 30 s
    # of laptop wake — even after hours of sleep.
    POLL_INTERVAL_SECONDS = 30

    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._next_run: Optional[datetime] = None

    @staticmethod
    def _now_est() -> datetime:
        """Returns the current time in US/Eastern."""
        return datetime.now(tz=EST)

    @staticmethod
    def next_run_time(from_dt: Optional[datetime] = None) -> datetime:
        """
        Calculates the next wall-clock target (Open or Close tick) from the given datetime.
        If from_dt is None, uses the current Eastern time.

        Logic:
          - On a weekday:
              * Before 09:40 ET  → next run is today 09:40 ET
              * Between 09:40 and 15:50 ET → next run is today 15:50 ET
              * After 15:50 ET  → next run is next business day 09:40 ET
          - On a weekend (Sat/Sun):
              * Next run is Monday 09:40 ET
        """
        if from_dt is None:
            from_dt = datetime.now(tz=EST)

        # Ensure timezone-aware
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=EST)

        today = from_dt.date()
        weekday = today.weekday()  # Mon=0 ... Sun=6

        open_target = datetime(today.year, today.month, today.day,
                               MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, 0, tzinfo=EST)
        close_target = datetime(today.year, today.month, today.day,
                                MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE, 0, tzinfo=EST)

        if weekday < 5:  # Monday through Friday
            if from_dt < open_target:
                return open_target
            elif from_dt < close_target:
                return close_target
            else:
                # After close — advance to next business day open
                next_day = today + timedelta(days=1)
                # Skip weekend
                while next_day.weekday() >= 5:
                    next_day += timedelta(days=1)
                return datetime(next_day.year, next_day.month, next_day.day,
                                MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, 0, tzinfo=EST)
        else:
            # Weekend — advance to Monday
            days_until_monday = 7 - weekday  # Sat=2, Sun=1
            next_monday = today + timedelta(days=days_until_monday)
            return datetime(next_monday.year, next_monday.month, next_monday.day,
                            MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, 0, tzinfo=EST)

    @staticmethod
    def missed_ticks_between(from_dt: datetime, to_dt: datetime) -> list:
        """
        Returns all tick targets that fall strictly between from_dt and to_dt.
        Used to catch up after laptop sleep or container restart.

        Example: if from_dt is 09:40 ET and to_dt is 17:00 ET on the same
        weekday, returns [15:50 ET] — the close tick that was missed.
        """
        missed = []
        if from_dt >= to_dt:
            return missed
        # Start scanning from 1 minute after from_dt to avoid re-firing it
        cursor = from_dt + timedelta(minutes=1)
        safety = 0
        while safety < 20:  # cap iterations to avoid infinite loops
            target = MarketClockScheduler.next_run_time(cursor)
            if target >= to_dt:
                break
            missed.append(target)
            cursor = target + timedelta(minutes=1)
            safety += 1
        return missed

    @staticmethod
    def tick_phase(at_dt: Optional[datetime] = None) -> str:
        """
        Returns a human-readable label for the current tick phase.
        'OPEN' if executing near market open, 'CLOSE' if near market close.
        """
        if at_dt is None:
            at_dt = datetime.now(tz=EST)
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=EST)
        # If hour is before noon Eastern, it's an open tick
        if at_dt.hour < 12:
            return "OPEN"
        return "CLOSE"

    def get_next_run_iso(self) -> Optional[str]:
        """Returns the next scheduled run time as an ISO string, or None."""
        with self._lock:
            if self._next_run is not None:
                return self._next_run.isoformat()
        return None

    def start(self) -> bool:
        with self._lock:
            if self._running:
                logger.warning("MarketClockScheduler is already running.")
                return False
            self._stop_event.clear()
            self._running = True
            # Eagerly compute next run so it's available immediately after start()
            self._next_run = self.next_run_time()
            self._thread = threading.Thread(
                target=self._run_loop, name="AntosMarketClockThread", daemon=True
            )
            self._thread.start()
            logger.info(f"MarketClockScheduler started. Next run: {self._next_run.isoformat()}")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                logger.warning("MarketClockScheduler is not running.")
                return False
            self._stop_event.set()
            self._running = False
            logger.info("MarketClockScheduler stop signal set.")
            return True

    def is_active(self) -> bool:
        with self._lock:
            return self._running

    def _run_loop(self) -> None:
        """
        Sleep-resilient scheduler loop.

        Instead of one long ``Event.wait(N)`` — which freezes when macOS
        sleeps because the monotonic clock pauses — we poll in 30-second
        intervals and compare the **wall clock** (``datetime.now``).

        After executing a scheduled tick, we also scan for any additional
        ticks that were missed during oversleep and execute them in order.
        """
        while not self._stop_event.is_set():
            now = self._now_est()
            target = self.next_run_time(now)
            with self._lock:
                self._next_run = target

            sleep_total = max(0.1, (target - now).total_seconds())
            phase = self.tick_phase(target)

            logger.info(
                f"MarketClockScheduler: Next {phase} tick at {target.strftime('%Y-%m-%d %H:%M %Z')} "
                f"(sleeping {sleep_total:.0f}s / {sleep_total/3600:.1f}h)"
            )

            # ---- wall-clock polling loop ----
            # Poll every POLL_INTERVAL_SECONDS, checking the real clock each
            # time.  When the laptop wakes from sleep the wall clock jumps
            # forward, so we break out within one poll cycle.
            while not self._stop_event.is_set():
                now = self._now_est()
                if now >= target:
                    break
                remaining = (target - now).total_seconds()
                self._stop_event.wait(min(self.POLL_INTERVAL_SECONDS, max(0.1, remaining)))

            if self._stop_event.is_set():
                break

            # ---- execute the scheduled tick ----
            actual_now = self._now_est()
            phase = self.tick_phase(target)
            logger.info(f"MarketClockScheduler: Executing {phase} tick.")
            try:
                self.callback()
            except Exception as ex:
                logger.error(f"MarketClockScheduler: Error during {phase} tick: {ex}", exc_info=True)

            # ---- catch-up missed ticks (laptop was asleep) ----
            missed = self.missed_ticks_between(target, actual_now)
            for missed_target in missed:
                if self._stop_event.is_set():
                    break
                missed_phase = self.tick_phase(missed_target)
                logger.info(
                    f"MarketClockScheduler: CATCH-UP — executing missed {missed_phase} tick "
                    f"from {missed_target.strftime('%Y-%m-%d %H:%M %Z')}"
                )
                try:
                    self.callback()
                except Exception as ex:
                    logger.error(
                        f"MarketClockScheduler: Error during catch-up {missed_phase} tick: {ex}",
                        exc_info=True
                    )

        with self._lock:
            self._next_run = None
        logger.info("MarketClockScheduler background thread terminated.")
