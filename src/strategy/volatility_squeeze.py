import logging
from typing import List, Dict, Optional
from collections import deque
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent

logger = logging.getLogger(__name__)


class VolatilitySqueezeMomentum(BaseStrategy):
    """
    Volatility Squeeze Momentum Strategy — Institutional Breakout Detection.

    Core Thesis:
    When volatility compresses to abnormally low levels (a "squeeze"), a large
    directional move is imminent. We detect the squeeze using Bollinger Band Width,
    determine direction using momentum (Rate of Change), and enter aggressively
    when price breaks out of the compressed range.

    Why this is different from retail:
    - Most retail traders use Bollinger Bands for MEAN REVERSION (buy lower band,
      sell upper band). We do the opposite — we trade BREAKOUTS out of the bands.
    - We only act after a squeeze (low volatility period), which filters out
      random noise and focuses on high-conviction setups.
    - The squeeze pattern is used institutionally (TTM Squeeze by John Carter).

    State Machine (per symbol):
    1. SCANNING:  Monitoring Bollinger Bandwidth for compression.
    2. SQUEEZED:  Bandwidth has dropped below threshold. Waiting for breakout.
    3. LONG:      Breakout was bullish. Riding with ATR trailing stop.
    4. SHORT_BIAS: (future) Breakout was bearish. Currently we only trade long.

    Signal Generation:
    - SQUEEZE DETECTED: BB_Width < percentile_threshold of its own N-bar history.
    - BREAKOUT UP: Close > Upper Bollinger Band AND ROC > 0.
    - EXIT: Price hits ATR trailing stop OR squeeze fails (no breakout within patience bars).
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        squeeze_lookback: int = 120,
        squeeze_percentile: float = 20.0,
        roc_period: int = 10,
        atr_period: int = 14,
        atr_trail_mult: float = 2.5,
        patience: int = 5,
        strength: float = 0.50,
    ):
        """
        Args:
            bb_period:          Bollinger Band SMA period.
            bb_std:             Bollinger Band standard deviation multiplier.
            squeeze_lookback:   How many bars of BB Width history to rank the squeeze against.
            squeeze_percentile: Width must be below this percentile to qualify as a squeeze.
                                Lower = stricter filter, fewer but higher-quality setups.
            roc_period:         Rate of Change lookback for momentum direction.
            atr_period:         ATR period for trailing stop calculation.
            atr_trail_mult:     Trailing stop distance in ATR multiples.
            patience:           Max bars to wait for a breakout after squeeze detection.
                                If no breakout occurs, reset to SCANNING.
            strength:           Capital allocation fraction per trade (0.0–1.0).
        """
        if bb_period < 5:
            raise ValueError(f"bb_period must be >= 5, got {bb_period}")
        if squeeze_lookback < bb_period:
            raise ValueError(f"squeeze_lookback must be >= bb_period, got {squeeze_lookback}")

        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_lookback = squeeze_lookback
        self.squeeze_percentile = squeeze_percentile
        self.roc_period = roc_period
        self.atr_period = atr_period
        self.atr_trail_mult = atr_trail_mult
        self.patience = patience
        self.strength = strength

        # Per-symbol state
        self._closes: Dict[str, deque] = {}
        self._highs: Dict[str, deque] = {}
        self._lows: Dict[str, deque] = {}
        self._bb_widths: Dict[str, deque] = {}

        self._state: Dict[str, str] = {}
        self._squeeze_bar_count: Dict[str, int] = {}
        self._trailing_stop: Dict[str, float] = {}
        self._atr: Dict[str, float] = {}
        self._atr_seeded: Dict[str, bool] = {}

    def _max_lookback(self) -> int:
        return max(self.bb_period, self.squeeze_lookback, self.roc_period, self.atr_period) + 2

    def _compute_bb(self, closes: deque) -> tuple:
        """Returns (middle_band, upper_band, lower_band, bandwidth)."""
        if len(closes) < self.bb_period:
            return None, None, None, None

        window = list(closes)[-self.bb_period:]
        mean = sum(window) / self.bb_period
        variance = sum((x - mean) ** 2 for x in window) / self.bb_period
        std = variance ** 0.5

        upper = mean + self.bb_std * std
        lower = mean - self.bb_std * std
        bandwidth = (upper - lower) / mean if mean > 0 else 0.0

        return mean, upper, lower, bandwidth

    def _compute_roc(self, closes: deque) -> Optional[float]:
        """Rate of Change: (current - N bars ago) / N bars ago."""
        if len(closes) < self.roc_period + 1:
            return None
        current = closes[-1]
        past = closes[-(self.roc_period + 1)]
        return (current - past) / past if past > 0 else 0.0

    def _update_atr(self, symbol: str):
        """Wilder's smoothed ATR."""
        highs = self._highs[symbol]
        lows = self._lows[symbol]
        closes = self._closes[symbol]

        if len(closes) < 2:
            return

        prev_close = closes[-2]
        tr = max(
            highs[-1] - lows[-1],
            abs(highs[-1] - prev_close),
            abs(lows[-1] - prev_close),
        )

        if not self._atr_seeded.get(symbol, False):
            if len(closes) >= self.atr_period + 1:
                trs = []
                close_list = list(closes)
                high_list = list(highs)
                low_list = list(lows)
                for i in range(1, self.atr_period + 1):
                    idx = -(i)
                    pc = close_list[idx - 1]
                    trs.append(max(
                        high_list[idx] - low_list[idx],
                        abs(high_list[idx] - pc),
                        abs(low_list[idx] - pc),
                    ))
                self._atr[symbol] = sum(trs) / len(trs)
                self._atr_seeded[symbol] = True
            else:
                self._atr[symbol] = tr
        else:
            self._atr[symbol] = (
                (self._atr[symbol] * (self.atr_period - 1) + tr) / self.atr_period
            )

    def _is_squeeze(self, symbol: str, current_width: float) -> bool:
        """Check if current BB width is below the Nth percentile of recent history."""
        widths = self._bb_widths[symbol]
        if len(widths) < self.squeeze_lookback:
            return False

        sorted_widths = sorted(list(widths)[-self.squeeze_lookback:])
        threshold_idx = int(len(sorted_widths) * self.squeeze_percentile / 100.0)
        threshold_idx = max(0, min(threshold_idx, len(sorted_widths) - 1))
        threshold = sorted_widths[threshold_idx]

        return current_width <= threshold

    def _reset_to_scanning(self, symbol: str):
        self._state[symbol] = 'SCANNING'
        self._squeeze_bar_count.pop(symbol, None)
        self._trailing_stop.pop(symbol, None)

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        signals: List[SignalEvent] = []
        symbol = event.symbol
        max_hist = self._max_lookback()

        # Initialize per-symbol state
        if symbol not in self._closes:
            self._closes[symbol] = deque(maxlen=max_hist)
            self._highs[symbol] = deque(maxlen=max_hist)
            self._lows[symbol] = deque(maxlen=max_hist)
            self._bb_widths[symbol] = deque(maxlen=self.squeeze_lookback + 10)
            self._state[symbol] = 'SCANNING'
            self._atr_seeded[symbol] = False

        self._closes[symbol].append(event.close_price)
        self._highs[symbol].append(event.high_price)
        self._lows[symbol].append(event.low_price)

        # Not enough data yet
        if len(self._closes[symbol]) < max_hist:
            return signals

        # Compute indicators
        self._update_atr(symbol)
        mid, upper, lower, bandwidth = self._compute_bb(self._closes[symbol])
        if bandwidth is None:
            return signals

        self._bb_widths[symbol].append(bandwidth)
        roc = self._compute_roc(self._closes[symbol])
        atr = self._atr.get(symbol, 0)
        state = self._state[symbol]
        close = event.close_price

        # ── Active Position: Trailing Stop Management ──────────────────
        if current_qty > 0:
            new_stop = close - (self.atr_trail_mult * atr)

            if symbol not in self._trailing_stop:
                self._trailing_stop[symbol] = new_stop
            else:
                self._trailing_stop[symbol] = max(self._trailing_stop[symbol], new_stop)

            if close <= self._trailing_stop[symbol]:
                signals.append(SignalEvent(symbol, event.timestamp, 'EXIT', self.strength))
                self._reset_to_scanning(symbol)
            return signals

        # ── State Machine for Entries ──────────────────────────────────
        if state == 'SCANNING':
            if self._is_squeeze(symbol, bandwidth):
                self._state[symbol] = 'SQUEEZED'
                self._squeeze_bar_count[symbol] = 0

        elif state == 'SQUEEZED':
            self._squeeze_bar_count[symbol] = self._squeeze_bar_count.get(symbol, 0) + 1

            # Breakout UP: Price closes above upper BB AND momentum is positive
            if close > upper and roc is not None and roc > 0:
                signals.append(SignalEvent(symbol, event.timestamp, 'LONG', self.strength))
                self._state[symbol] = 'LONG'
                self._trailing_stop[symbol] = close - (self.atr_trail_mult * atr)
                return signals

            # Patience expired — no breakout, false squeeze
            if self._squeeze_bar_count[symbol] >= self.patience:
                self._reset_to_scanning(symbol)

        return signals
