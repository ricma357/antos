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
