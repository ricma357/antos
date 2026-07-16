from abc import ABC, abstractmethod
from typing import List
from src.events import MarketEvent, SignalEvent

class BaseStrategy(ABC):
    """
    Abstract Base Class (ABC) providing a uniform interface for all trading strategies.
    
    This guarantees that both simple moving average crossovers and advanced machine learning
    models conform to the exact same input/output contract: consuming a MarketEvent and 
    generating optional SignalEvents.
    """

    @abstractmethod
    def calculate_signals(self, event: MarketEvent, current_qty: int) -> List[SignalEvent]:
        """
        Consumes a new price bar (MarketEvent) and runs quantitative calculations
        to generate potential trading recommendations.

        Args:
            event (MarketEvent): The latest OHLCV market update.
            current_qty (int): The current position quantity held in the portfolio.

        Returns:
            List[SignalEvent]: A list of zero or more generated signal recommendations.
        """
        pass

    def warmup(self, event: MarketEvent, current_qty: int = 0) -> None:
        """
        Feeds a historical bar to rebuild internal state WITHOUT requiring a
        trading decision. Live systems replay the full history through this
        on every tick, so expensive strategies should override it with a
        state-only fast path (e.g. append to history, skip model fitting).

        The default delegates to calculate_signals and discards the signals,
        so behavior is identical for strategies that don't override it.
        """
        self.calculate_signals(event, current_qty)

    def export_diagnostics(self) -> dict:
        """
        Returns JSON-serializable diagnostic state (e.g. prediction hit
        history) so live systems that rebuild the strategy each tick can
        persist it across process/instance boundaries. Default: nothing.
        """
        return {}

    def restore_diagnostics(self, diagnostics: dict) -> None:
        """Restores state previously produced by export_diagnostics."""
        pass
