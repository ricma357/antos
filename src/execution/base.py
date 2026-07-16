from abc import ABC, abstractmethod
from typing import List
from src.events import OrderEvent, FillEvent, MarketEvent

class BaseExecutionHandler(ABC):
    """
    Abstract Base Class managing order routing and execution reporting.
    
    Acts as the boundary between our system and the brokerage. Orders are queued
    upon receipt and only filled when the next market tick arrives, using that
    tick's Open price. This eliminates close-price execution lookahead bias.
    """

    @abstractmethod
    def queue_order(self, event: OrderEvent) -> None:
        """
        Queues an OrderEvent for deferred execution on the next market tick.
        
        Args:
            event (OrderEvent): The validated order parameters to queue.
        """
        pass

    @abstractmethod
    def process_market_event(self, event: MarketEvent) -> List[FillEvent]:
        """
        Called when a new MarketEvent arrives. Iterates through pending orders
        matching this symbol and fills them against the new bar's Open price.
        
        Args:
            event (MarketEvent): The latest OHLCV market update.
            
        Returns:
            List[FillEvent]: A list of execution fills for orders that matched this symbol.
        """
        pass
