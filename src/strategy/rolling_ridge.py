import logging
import numpy as np
from typing import List, Dict
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent

logger = logging.getLogger(__name__)


class RollingRidgeDirectionalPredictor(BaseStrategy):
    """
    Regime-Aware Rolling Ridge Regression Directional Predictor.

    Combines walk-forward Ridge Regression (predicting next-bar return direction)
    with a macro trend filter (SMA) to determine the market regime:

        Bull Regime (Close >= SMA):
            - ML predicts UP  → LONG
            - ML predicts DOWN → EXIT (cash shelter)

        Bear Regime (Close < SMA):
            - EXIT all positions, shelter in CASH.
            - No new trades opened (no longs, no shorts).

    This prevents "catching falling knives" during crashes (2008-style drawdowns)
    by forbidding any new entries in bear markets. Short-selling was tested but
    proved destructive due to insufficient directional accuracy (see doc/strategies.md).

    Mathematical Formulation (Ridge Regression):
      beta = (X^T * X + lambda * I)^-1 * X^T * Y
      predicted_return = x_today * beta
    """

    VOL_WINDOW = 20  # trailing window (bars) for realized-volatility estimate

    def __init__(
        self,
        lookback_window: int = 90,
        l2_lambda: float = 1.0,
        prediction_threshold: float = 0.001,
        strength: float = 0.50,
        trend_filter_window: int = 200,
        vol_threshold_k: float = 0.15,
        regime_hysteresis: float = 0.0,
    ):
        """
        Args:
            lookback_window:      Number of recent bars used for model training.
            l2_lambda:            L2 regularization strength (lambda). Prevents overfitting.
            prediction_threshold: Predicted return threshold to trigger an entry/exit.
            strength:             Capital allocation fraction per trade (0.0-1.0).
            trend_filter_window:  SMA period for macro regime detection (default: 200).
                                  Price above this SMA = Bull, below = Bear.
            vol_threshold_k:      If set, the entry/exit threshold becomes
                                  k x trailing realized daily volatility
                                  (std of the last VOL_WINDOW returns) instead
                                  of the fixed prediction_threshold. A fixed
                                  threshold means something different in a
                                  calm market than in a VIX-40 regime; scaling
                                  demands proportionally stronger conviction
                                  when noise is high. None = fixed threshold.
                                  Default 0.15 — tuned on the 2020-2023 train
                                  window only, validated out-of-sample on
                                  2024-2026 and 2006-2012 crisis data
                                  (see doc/validation_baseline.md).
            regime_hysteresis:    Dead band around the trend SMA to prevent
                                  regime whipsaw. With hysteresis b, an
                                  established BULL regime only flips to BEAR
                                  when close < SMA×(1−b), and BEAR only flips
                                  back when close > SMA×(1+b). 0 = flip on
                                  every crossing (legacy behavior).
        """
        if lookback_window < 10:
            raise ValueError(f"lookback_window must be >= 10, got {lookback_window}")
        if l2_lambda < 0:
            raise ValueError(f"l2_lambda must be non-negative, got {l2_lambda}")
        if trend_filter_window < 10:
            raise ValueError(f"trend_filter_window must be >= 10, got {trend_filter_window}")
        if vol_threshold_k is not None and vol_threshold_k < 0:
            raise ValueError(f"vol_threshold_k must be non-negative, got {vol_threshold_k}")
        if vol_threshold_k == 0:
            vol_threshold_k = None  # 0 = disabled (UI convention) → fixed threshold
        if not 0.0 <= regime_hysteresis < 0.5:
            raise ValueError(f"regime_hysteresis must be in [0, 0.5), got {regime_hysteresis}")

        self.lookback_window = lookback_window
        self.l2_lambda = l2_lambda
        self.prediction_threshold = prediction_threshold
        self.strength = strength
        self.trend_filter_window = trend_filter_window
        self.vol_threshold_k = vol_threshold_k
        self.regime_hysteresis = regime_hysteresis

        # Path-dependent regime state (per symbol) and O(1) rolling SMA
        # accumulator, both maintained by _append_bar so warmup() replays
        # build identical regime state to full calculate_signals replays.
        self._regime: Dict[str, str] = {}
        self._sma_sum: Dict[str, float] = {}

        # History cache per symbol: List[dict]
        self._history: Dict[str, List[dict]] = {}

        # Prediction diagnostics: last directional call awaiting its
        # outcome, and the rolling record of resolved calls per symbol.
        self._last_prediction: Dict[str, float] = {}
        self._hit_history: Dict[str, List[bool]] = {}
        self._max_hit_history = 500

    def _compute_features(self, history: List[dict], idx: int) -> np.ndarray:
        """
        Computes 5 normalized indicators for index idx in history.
        Uses historical data up to index idx (inclusive).
        """
        # We need lookback history up to idx
        window = history[idx - 24 : idx + 1]

        closes = np.array([w['close'] for w in window])
        highs = np.array([w['high'] for w in window])
        lows = np.array([w['low'] for w in window])
        volumes = np.array([w['volume'] for w in window])

        # 1. ROC_1 (1-bar return)
        roc_1 = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0.0

        # 2. ROC_3 (3-bar return)
        roc_3 = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] > 0 else 0.0

        # 3. Range Ratio (Current High-Low Range normalized by average range)
        ranges = highs - lows
        avg_range = np.mean(ranges[-14:])
        range_ratio = ranges[-1] / avg_range if avg_range > 0 else 1.0

        # 4. Volume Z-Score relative to 20-period average
        vol_mean = np.mean(volumes[-20:])
        vol_std = np.std(volumes[-20:])
        volume_z = (volumes[-1] - vol_mean) / vol_std if vol_std > 0 else 0.0

        # 5. Distance to 20-period Simple Moving Average
        ma_20 = np.mean(closes[-20:])
        ma_dist = (closes[-1] - ma_20) / ma_20 if ma_20 > 0 else 0.0

        return np.array([roc_1, roc_3, range_ratio, volume_z, ma_dist])

    def _compute_regime(self, symbol: str) -> str:
        """
        Returns the current regime for the symbol from the state machine
        maintained in _append_bar: 'BULL', 'BEAR', or 'UNKNOWN' when the
        trend window hasn't filled yet. With regime_hysteresis > 0 the
        state is path-dependent — an established regime persists until
        price breaks decisively out of the SMA dead band.
        """
        return self._regime.get(symbol, 'UNKNOWN')

    def _append_bar(self, event: MarketEvent) -> List[dict]:
        """
        Appends the event to the per-symbol history cache, maintains the
        rolling trend-SMA accumulator, and advances the regime state
        machine. Runs on both the warmup and live paths so regime state is
        identical however history was replayed.
        """
        symbol = event.symbol
        if symbol not in self._history:
            self._history[symbol] = []
        history = self._history[symbol]
        history.append({
            'timestamp': event.timestamp,
            'open': event.open_price,
            'high': event.high_price,
            'low': event.low_price,
            'close': event.close_price,
            'volume': event.volume
        })

        # O(1) rolling SMA over the trend filter window
        window = self.trend_filter_window
        self._sma_sum[symbol] = self._sma_sum.get(symbol, 0.0) + event.close_price
        if len(history) > window:
            self._sma_sum[symbol] -= history[-(window + 1)]['close']

        if len(history) >= window:
            sma = self._sma_sum[symbol] / window
            close = event.close_price
            prev = self._regime.get(symbol)
            b = self.regime_hysteresis

            if prev == 'BULL':
                # Established bull: demand a decisive break below the band.
                regime = 'BEAR' if close < sma * (1.0 - b) else 'BULL'
            elif prev == 'BEAR':
                # Established bear: demand a decisive reclaim above the band.
                regime = 'BULL' if close > sma * (1.0 + b) else 'BEAR'
            else:
                # First reading: plain comparison seeds the state.
                regime = 'BULL' if close >= sma else 'BEAR'
            self._regime[symbol] = regime

        return history

    def warmup(self, event: MarketEvent, current_qty: int = 0) -> None:
        """
        State-only fast path for historical replay: appends the bar to the
        history cache and skips feature construction, training, and
        prediction entirely. The model's only cross-bar state is that
        history, so warmup + one calculate_signals on the live bar produces
        the same decision as replaying everything through calculate_signals
        — at ~1 ridge fit per tick instead of one per historical bar.
        """
        self._append_bar(event)

    def export_diagnostics(self) -> dict:
        """Serializes prediction-tracking state for cross-tick persistence."""
        return {
            "last_prediction": dict(self._last_prediction),
            "hit_history": {sym: list(hits) for sym, hits in self._hit_history.items()},
        }

    def restore_diagnostics(self, diagnostics: dict) -> None:
        """Restores prediction-tracking state saved by export_diagnostics."""
        if not diagnostics:
            return
        self._last_prediction = dict(diagnostics.get("last_prediction", {}))
        self._hit_history = {
            sym: [bool(h) for h in hits]
            for sym, hits in diagnostics.get("hit_history", {}).items()
        }

    def get_regime(self, symbol: str) -> str:
        """Public accessor for the symbol's current macro regime."""
        return self._compute_regime(symbol)

    def get_hit_rate(self, symbol: str, window: int = None) -> float:
        """
        Fraction of resolved directional calls that got the sign right.

        Args:
            symbol: instrument to report on.
            window: number of most recent calls to consider (None = all).

        Returns:
            Hit rate in [0, 1], or None if fewer than 5 calls have resolved
            (too few to be meaningful).
        """
        hits = self._hit_history.get(symbol, [])
        if window is not None:
            hits = hits[-window:]
        if len(hits) < 5:
            return None
        return sum(hits) / len(hits)

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        signals: List[SignalEvent] = []
        symbol = event.symbol
        history = self._append_bar(event)

        # ── Resolve the previous directional call, if any ──────────────
        # The prediction made on the prior bar forecast THIS bar's return;
        # now that it has arrived we can score it.
        if symbol in self._last_prediction and len(history) >= 2:
            prev_close = history[-2]['close']
            if prev_close > 0:
                actual_return = (history[-1]['close'] - prev_close) / prev_close
                predicted = self._last_prediction.pop(symbol)
                hits = self._hit_history.setdefault(symbol, [])
                hits.append((predicted > 0) == (actual_return > 0))
                if len(hits) > self._max_hit_history:
                    del hits[:-self._max_hit_history]

        # We need at least 25 bars for computing features, plus lookback_window bars for training,
        # plus 1 extra bar for the next-day target return.
        min_required_bars = max(self.lookback_window + 26, self.trend_filter_window)
        if len(history) < min_required_bars:
            return signals

        # ── Regime Detection ───────────────────────────────────────────
        regime = self._compute_regime(symbol)
        if regime == 'UNKNOWN':
            return signals

        # ── Construct Training Set X (Features) and Y (Targets) ────────
        X = []
        Y = []

        start_idx = len(history) - 1 - self.lookback_window
        for i in range(start_idx, len(history) - 1):
            features = self._compute_features(history, i)
            next_return = (history[i + 1]['close'] - history[i]['close']) / history[i]['close']
            X.append(features)
            Y.append(next_return)

        X = np.array(X)
        Y = np.array(Y)

        # ── Solve Ridge Regression ─────────────────────────────────────
        # NOTE (2026-07-16, deliberate): features are NOT standardized and
        # there is NO intercept — and this is load-bearing. The textbook
        # fix (z-scored features + unpenalized intercept via Y-centering)
        # was implemented and falsified against the validation harness:
        # holdout 2024-2026 degraded and the 2006-2012 crisis flipped from
        # +28% to -22% (see doc/validation_baseline.md, "Falsified
        # experiments"). With ~50% directional hit rates, the model's edge
        # comes from over-shrinkage: raw return-scale features under this
        # penalty crush predictions toward zero, so it only trades when
        # trailing drift is strong — an accidental but effective
        # high-conviction trend filter. An unpenalized intercept instead
        # injects trailing drift into EVERY prediction, whipsawing the
        # threshold and doubling fee drag. Do not "fix" this without
        # beating the baseline in validate_strategy.py on BOTH periods.
        K = X.shape[1]
        XTX = np.dot(X.T, X)
        XT_Y = np.dot(X.T, Y)
        reg_matrix = XTX + self.l2_lambda * np.eye(K)

        try:
            beta = np.linalg.solve(reg_matrix, XT_Y)
        except np.linalg.LinAlgError:
            logger.warning(f"Singular matrix encountered in Ridge solver for {symbol}. Skipping prediction.")
            return signals

        # ── Predict next-bar return ────────────────────────────────────
        current_features = self._compute_features(history, len(history) - 1)
        predicted_return = float(np.dot(current_features, beta))

        # ── Effective threshold: fixed or volatility-scaled ────────────
        threshold = self.prediction_threshold
        if self.vol_threshold_k is not None:
            closes = np.array([h['close'] for h in history[-(self.VOL_WINDOW + 1):]])
            returns = np.diff(closes) / closes[:-1]
            sigma = float(returns.std())
            if sigma > 0:
                threshold = self.vol_threshold_k * sigma

        predicts_up = predicted_return > threshold
        predicts_down = predicted_return < -threshold

        # Track directional calls (only when the model actually commits to
        # a direction) so live systems can monitor rolling accuracy.
        if predicts_up or predicts_down:
            self._last_prediction[symbol] = predicted_return

        # ── Regime-Aware Signal Generation ─────────────────────────────
        if regime == 'BULL':
            # Bull market: ML-guided LONG/EXIT for alpha.
            if predicts_up:
                if current_qty <= 0:
                    signals.append(SignalEvent(symbol, event.timestamp, 'LONG', self.strength))
            elif predicts_down:
                if current_qty > 0:
                    # Cash shelter: exit long position
                    signals.append(SignalEvent(symbol, event.timestamp, 'EXIT', self.strength))

        elif regime == 'BEAR':
            # Bear market: CASH SHELTER. Exit everything, open nothing.
            # Short-selling with this model's accuracy is destructive due to
            # whipsaw losses and commission drag during high-volatility periods.
            if current_qty != 0:
                signals.append(SignalEvent(symbol, event.timestamp, 'EXIT', self.strength))

        return signals
