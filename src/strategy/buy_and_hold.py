from typing import List
from src.strategy.base import BaseStrategy
from src.events import MarketEvent, SignalEvent


class BuyAndHold(BaseStrategy):
    """
    Passive benchmark: buys each symbol on its first bar and never trades again.

    Every active strategy must justify its complexity, turnover, and fees
    against this baseline. For multi-asset runs pass strength = 1/n_symbols
    so capital is split equally.
    """

    def __init__(self, strength: float = 1.0):
        if not 0.0 < strength <= 1.0:
            raise ValueError(f"strength must be in (0.0, 1.0], got {strength}")
        self.strength = strength
        self._entered = set()

    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        if event.symbol not in self._entered and current_qty == 0:
            self._entered.add(event.symbol)
            return [SignalEvent(
                symbol=event.symbol,
                timestamp=event.timestamp,
                signal_type='LONG',
                strength=self.strength,
            )]
        return []
