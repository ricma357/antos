import logging
from typing import List, Dict, Optional
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent

logger = logging.getLogger(__name__)


class PeakBreakoutPullback(BaseStrategy):
    """
    Trend Breakout Pullback quantitative strategy with Institutional-Grade Risk Management.

    State Machine:
    1. SCANNING:  Tracks a Donchian Channel (Highest High of N bars).
    2. BREAKOUT:  Triggers when price closes above the Donchian High AND volume > Volume SMA.
                  Identifies the local Swing Low to define risk.
    3. PULLBACK:  Waits for price to retrace without breaching the Swing Low.
    4. LONG:      Enters when a bar closes above the previous bar's high.
                  Trails stop using ATR to ride the trend.
    """

    VALID_STATES = frozenset({'SCANNING', 'BREAKOUT', 'PULLBACK', 'LONG'})

    def __init__(
        self,
        lookback_window: int = 5,
        atr_period: int = 14,
        vol_sma_period: int = 20,
        atr_multiplier: float = 3.0,
        strength: float = 0.20,
    ):
        """
        Args:
            lookback_window (int): Number of bars to scan for Donchian Highs/Lows.
            atr_period (int): ATR smoothing period (Wilder's SMMA).
            vol_sma_period (int): Volume SMA lookback for breakout confirmation.
            atr_multiplier (float): ATR units below price for the trailing stop.
            strength (float): Capital fraction per signal (0.0–1.0).

        Raises:
            ValueError: If any parameter is invalid.
        """
        if lookback_window < 2:
            raise ValueError(f"lookback_window must be >= 2, got {lookback_window}")
        if atr_period < 2:
            raise ValueError(f"atr_period must be >= 2, got {atr_period}")
        if atr_multiplier <= 0:
            raise ValueError(f"atr_multiplier must be > 0, got {atr_multiplier}")

        self.lookback_window = lookback_window
        self.atr_period = atr_period
        self.vol_sma_period = vol_sma_period
        self.atr_multiplier = atr_multiplier
        self.strength = strength

        # Per-symbol state tracking
        self._price_hist: Dict[str, List[MarketEvent]] = {}
        self._state: Dict[str, str] = {}
        self._swing_low: Dict[str, float] = {}
        self._trailing_stop: Dict[str, float] = {}

        # ATR and Volume indicators
        self._atr: Dict[str, float] = {}
        self._atr_seeded: Dict[str, bool] = {}
        self._vol_sma: Dict[str, float] = {}

    def _update_indicators(self, symbol: str, event: MarketEvent) -> None:
        """
        Updates ATR (Wilder's SMMA) and Volume SMA indicators from the price history.
        """
        hist = self._price_hist[symbol]
        if len(hist) < 2:
            return

        # True Range: max of (H-L, |H-prevC|, |L-prevC|)
        prev_close = hist[-2].close_price
        tr = max(
            event.high_price - event.low_price,
            abs(event.high_price - prev_close),
            abs(event.low_price - prev_close),
        )

        # Wilder's Smoothed Moving Average for ATR
        if not self._atr_seeded.get(symbol, False):
            if len(hist) >= self.atr_period + 1:
                # Seed ATR with simple average of last N true ranges
                trs = []
                for i in range(1, self.atr_period + 1):
                    p_c = hist[-i - 1].close_price
                    curr = hist[-i]
                    trs.append(max(
                        curr.high_price - curr.low_price,
                        abs(curr.high_price - p_c),
                        abs(curr.low_price - p_c),
                    ))
                self._atr[symbol] = sum(trs) / len(trs)
                self._atr_seeded[symbol] = True
            else:
                self._atr[symbol] = tr
        else:
            self._atr[symbol] = (
                (self._atr[symbol] * (self.atr_period - 1) + tr) / self.atr_period
            )

        # Volume SMA
        if len(hist) >= self.vol_sma_period:
            vol_sum = sum(e.volume for e in hist[-self.vol_sma_period:])
            self._vol_sma[symbol] = vol_sum / self.vol_sma_period

    def _reset_to_scanning(self, symbol: str) -> None:
        """Cleanly transition a symbol back to SCANNING state."""
        self._state[symbol] = 'SCANNING'
        self._swing_low.pop(symbol, None)
        self._trailing_stop.pop(symbol, None)

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        """
        Processes a market bar and returns signals based on the state machine.
        """
        signals: List[SignalEvent] = []
        symbol = event.symbol

        # Initialize per-symbol state on first encounter
        if symbol not in self._price_hist:
            self._price_hist[symbol] = []
            self._state[symbol] = 'SCANNING'
            self._atr_seeded[symbol] = False

        self._price_hist[symbol].append(event)
        self._update_indicators(symbol, event)

        # Memory management: cap history at longest lookback + buffer
        max_history = max(self.lookback_window, self.atr_period, self.vol_sma_period) + 2
        if len(self._price_hist[symbol]) > max_history:
            self._price_hist[symbol].pop(0)

        # Wait until we have enough data for all indicators
        if len(self._price_hist[symbol]) < max_history:
            return signals

        hist = self._price_hist[symbol]
        state = self._state[symbol]

        # Donchian High (excluding current bar) — the highest high over the lookback
        swing_high = max(e.high_price for e in hist[-self.lookback_window - 1:-1])

        # ── Active Position: Trailing Stop Management ──────────────────
        if current_qty > 0:
            atr = self._atr.get(symbol, 0)
            new_stop = event.close_price - (self.atr_multiplier * atr)

            if symbol not in self._trailing_stop:
                self._trailing_stop[symbol] = new_stop
            else:
                # Ratchet: trailing stop only moves UP, never down
                self._trailing_stop[symbol] = max(self._trailing_stop[symbol], new_stop)

            # Exit if price violates the trailing stop
            if event.close_price <= self._trailing_stop[symbol]:
                signals.append(SignalEvent(symbol, event.timestamp, 'EXIT', self.strength))
                self._reset_to_scanning(symbol)
            return signals

        # ── State Machine Logic for Entries ────────────────────────────
        if state == 'SCANNING':
            vol_sma = self._vol_sma.get(symbol, 0)
            # Breakout: Close above Swing High with volume confirmation
            if event.close_price > swing_high and vol_sma > 0 and event.volume > vol_sma:
                self._state[symbol] = 'BREAKOUT'
                self._swing_low[symbol] = min(e.low_price for e in hist[-self.lookback_window:])

        elif state == 'BREAKOUT':
            prev_event = hist[-2]
            # Pullback: a lower close means momentum has paused
            if event.close_price < prev_event.close_price:
                self._state[symbol] = 'PULLBACK'

            # Invalidation: price collapses below swing low
            if event.close_price < self._swing_low.get(symbol, 0):
                self._reset_to_scanning(symbol)

        elif state == 'PULLBACK':
            prev_event = hist[-2]
            # Entry Trigger: Close above previous bar's high confirms the pivot
            if event.close_price > prev_event.high_price:
                signals.append(SignalEvent(symbol, event.timestamp, 'LONG', self.strength))
                self._state[symbol] = 'LONG'
                # Initialize trailing stop below swing low with ATR padding
                atr = self._atr.get(symbol, 0)
                self._trailing_stop[symbol] = self._swing_low.get(symbol, 0) - (0.5 * atr)

            # Invalidation
            elif event.close_price < self._swing_low.get(symbol, 0):
                self._reset_to_scanning(symbol)

        return signals
