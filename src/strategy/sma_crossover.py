from typing import List, Dict
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent


class SMACrossover(BaseStrategy):
    """
    Moving Average Crossover quantitative strategy.

    Generates a 'LONG' signal when a fast simple moving average crosses above a slow
    simple moving average (Golden Cross), and generates an 'EXIT' signal when the fast
    crosses below the slow moving average (Death Cross).
    """

    def __init__(self, short_window: int = 50, long_window: int = 200):
        """
        Args:
            short_window (int): The window size for the fast SMA calculation.
            long_window (int): The window size for the slow SMA calculation.
        
        Raises:
            ValueError: If short_window >= long_window.
        """
        if short_window >= long_window:
            raise ValueError(
                f"short_window ({short_window}) must be less than long_window ({long_window})"
            )
        self.short_window = short_window
        self.long_window = long_window

        # Track sliding window of closing prices per symbol to keep memory consumption bounded
        self._price_history: Dict[str, List[float]] = {}

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        """
        Appends the new price data point and evaluates moving average crossover conditions.
        """
        signals: List[SignalEvent] = []
        symbol = event.symbol

        if symbol not in self._price_history:
            self._price_history[symbol] = []

        # Append latest close price to rolling list
        self._price_history[symbol].append(event.close_price)

        # Restrict history memory size to a tiny buffer past our slow window length
        max_required_history = self.long_window + 5
        if len(self._price_history[symbol]) > max_required_history:
            self._price_history[symbol].pop(0)

        # Only evaluate signals once the rolling history matches our longest lookback window
        if len(self._price_history[symbol]) >= self.long_window:
            short_slice = self._price_history[symbol][-self.short_window:]
            long_slice = self._price_history[symbol][-self.long_window:]

            short_sma = sum(short_slice) / self.short_window
            long_sma = sum(long_slice) / self.long_window

            currently_long = current_qty > 0

            if short_sma > long_sma and not currently_long:
                # Golden Cross: Enter Market
                signals.append(SignalEvent(
                    symbol=symbol,
                    timestamp=event.timestamp,
                    signal_type='LONG',
                    strength=0.20
                ))
            elif short_sma < long_sma and currently_long:
                # Death Cross: Exit Position
                signals.append(SignalEvent(
                    symbol=symbol,
                    timestamp=event.timestamp,
                    signal_type='EXIT',
                    strength=0.20
                ))

        return signals
