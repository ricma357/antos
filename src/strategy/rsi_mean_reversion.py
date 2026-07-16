from typing import List, Dict
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent


class RSIMeanReversion(BaseStrategy):
    """
    RSI (Relative Strength Index) Mean-Reversion Strategy.

    Philosophy: the opposite of trend-following. When price has fallen sharply
    (RSI < oversold threshold), the market is likely to bounce — buy. When price
    has surged (RSI > overbought threshold), the market is likely to revert — exit.

    Industry context:
    - RSI was developed by J. Welles Wilder (1978).
    - Standard parameters: period=14, oversold=30, overbought=70.
    - Works best in range-bound (sideways/mean-reverting) markets.
    - Tends to suffer in strong trending markets (will buy falling knives).

    Signal rules:
    - RSI crosses below `oversold`  → LONG  (buy the dip)
    - RSI crosses above `overbought` → EXIT  (sell the rip)
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        strength: float = 0.20,
    ):
        """
        Args:
            period (int):      RSI lookback window (standard = 14).
            oversold (float):  RSI level below which we consider the asset oversold.
            overbought (float):RSI level above which we consider the asset overbought.
            strength (float):  Capital fraction to deploy per signal (0.0–1.0).
        
        Raises:
            ValueError: If oversold >= overbought or period < 2.
        """
        if period < 2:
            raise ValueError(f"RSI period must be >= 2, got {period}")
        if oversold >= overbought:
            raise ValueError(
                f"oversold ({oversold}) must be less than overbought ({overbought})"
            )

        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.strength = strength

        # Track the last computed RSI per symbol (to detect threshold crossings)
        self._prev_rsi: Dict[str, float] = {}

        # Wilder's Smoothed Moving Average state trackers
        self._avg_gain: Dict[str, float] = {}
        self._avg_loss: Dict[str, float] = {}

        # Raw prices for the seed window
        self._seed_prices: Dict[str, List[tuple]] = {}
        self._last_price: Dict[str, float] = {}

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        """
        Appends new close price, computes RSI using Wilder's SMMA, and checks for threshold crossings.
        """
        signals: List[SignalEvent] = []
        symbol = event.symbol
        price = event.close_price

        # Initialize tracking states if ticker is new
        if symbol not in self._prev_rsi:
            self._prev_rsi[symbol] = 50.0
            self._seed_prices[symbol] = []

        # If last price is not recorded yet, record it and wait for next bar
        if symbol not in self._last_price:
            self._last_price[symbol] = price
            return signals

        last_price = self._last_price[symbol]
        gain = max(price - last_price, 0.0)
        loss = max(last_price - price, 0.0)
        self._last_price[symbol] = price

        # If we have already initialized the Wilder averages, update them recursively
        if symbol in self._avg_gain:
            self._avg_gain[symbol] = (self._avg_gain[symbol] * (self.period - 1) + gain) / self.period
            self._avg_loss[symbol] = (self._avg_loss[symbol] * (self.period - 1) + loss) / self.period

            # Compute RSI
            if self._avg_loss[symbol] == 0.0:
                current_rsi = 100.0 if self._avg_gain[symbol] > 0.0 else 50.0
            else:
                rs = self._avg_gain[symbol] / self._avg_loss[symbol]
                current_rsi = 100.0 - (100.0 / (1.0 + rs))

        # Otherwise, we are still in the seed window
        else:
            self._seed_prices[symbol].append((gain, loss))
            if len(self._seed_prices[symbol]) == self.period:
                # Seed averages using simple SMA
                gains_list = [g for g, l in self._seed_prices[symbol]]
                losses_list = [l for g, l in self._seed_prices[symbol]]
                self._avg_gain[symbol] = sum(gains_list) / self.period
                self._avg_loss[symbol] = sum(losses_list) / self.period

                # Compute seed RSI
                if self._avg_loss[symbol] == 0.0:
                    current_rsi = 100.0 if self._avg_gain[symbol] > 0.0 else 50.0
                else:
                    rs = self._avg_gain[symbol] / self._avg_loss[symbol]
                    current_rsi = 100.0 - (100.0 / (1.0 + rs))

                # Free the seed buffer — no longer needed
                del self._seed_prices[symbol]
            else:
                # Still building seed window, cannot calculate RSI yet
                return signals

        # Check signal rules
        prev_rsi = self._prev_rsi[symbol]
        currently_long = current_qty > 0

        # Entry: RSI crosses DOWN through the oversold threshold (buy the dip)
        if prev_rsi >= self.oversold and current_rsi < self.oversold and not currently_long:
            signals.append(SignalEvent(
                symbol=symbol,
                timestamp=event.timestamp,
                signal_type='LONG',
                strength=self.strength,
            ))

        # Exit: RSI crosses UP through the overbought threshold (sell the rip)
        elif prev_rsi <= self.overbought and current_rsi > self.overbought and currently_long:
            signals.append(SignalEvent(
                symbol=symbol,
                timestamp=event.timestamp,
                signal_type='EXIT',
                strength=self.strength,
            ))

        self._prev_rsi[symbol] = current_rsi
        return signals
