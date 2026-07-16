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

    def __init__(
        self,
        lookback_window: int = 90,
        l2_lambda: float = 1.0,
        prediction_threshold: float = 0.001,
        strength: float = 0.50,
        trend_filter_window: int = 200,
    ):
        """
        Args:
            lookback_window:      Number of recent bars used for model training.
            l2_lambda:            L2 regularization strength (lambda). Prevents overfitting.
            prediction_threshold: Predicted return threshold to trigger an entry/exit.
            strength:             Capital allocation fraction per trade (0.0-1.0).
            trend_filter_window:  SMA period for macro regime detection (default: 200).
                                  Price above this SMA = Bull, below = Bear.
        """
        if lookback_window < 10:
            raise ValueError(f"lookback_window must be >= 10, got {lookback_window}")
        if l2_lambda < 0:
            raise ValueError(f"l2_lambda must be non-negative, got {l2_lambda}")
        if trend_filter_window < 10:
            raise ValueError(f"trend_filter_window must be >= 10, got {trend_filter_window}")

        self.lookback_window = lookback_window
        self.l2_lambda = l2_lambda
        self.prediction_threshold = prediction_threshold
        self.strength = strength
        self.trend_filter_window = trend_filter_window

        # History cache per symbol: List[dict]
        self._history: Dict[str, List[dict]] = {}

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

    def _compute_regime(self, history: List[dict]) -> str:
        """
        Determines the macro regime by comparing the latest close to the
        trend_filter_window-period SMA.

        Returns:
            'BULL' if close >= SMA, 'BEAR' if close < SMA, 'UNKNOWN' if not
            enough data.
        """
        if len(history) < self.trend_filter_window:
            return 'UNKNOWN'

        closes = [h['close'] for h in history[-self.trend_filter_window:]]
        sma = sum(closes) / len(closes)
        current_close = history[-1]['close']

        return 'BULL' if current_close >= sma else 'BEAR'

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        signals: List[SignalEvent] = []
        symbol = event.symbol

        if symbol not in self._history:
            self._history[symbol] = []

        self._history[symbol].append({
            'timestamp': event.timestamp,
            'open': event.open_price,
            'high': event.high_price,
            'low': event.low_price,
            'close': event.close_price,
            'volume': event.volume
        })

        history = self._history[symbol]

        # We need at least 25 bars for computing features, plus lookback_window bars for training,
        # plus 1 extra bar for the next-day target return.
        min_required_bars = max(self.lookback_window + 26, self.trend_filter_window)
        if len(history) < min_required_bars:
            return signals

        # ── Regime Detection ───────────────────────────────────────────
        regime = self._compute_regime(history)
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

        predicts_up = predicted_return > self.prediction_threshold
        predicts_down = predicted_return < -self.prediction_threshold

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
