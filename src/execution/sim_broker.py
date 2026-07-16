import logging
from typing import List
from src.execution.base import BaseExecutionHandler
from src.events import OrderEvent, FillEvent, MarketEvent

logger = logging.getLogger(__name__)


class SimulatedBroker(BaseExecutionHandler):
    """
    Simulated Broker execution engine designed for offline backtesting.

    Orders are NOT filled instantly. Instead, they are queued and executed on the
    next market bar's Open price. This accurately models the real-world constraint
    that you cannot trade at a price that has already passed.

    Applies configurable slippage (price impact) and commission (broker fees).
    """

    def __init__(self, commission_rate: float = 0.001, slippage_rate: float = 0.0005):
        """
        Initializes the simulated execution environment.

        Args:
            commission_rate (float): Broker fee as a fraction of trade value (e.g. 0.001 = 0.1%).
            slippage_rate (float): Estimated market slippage as a fraction of price (e.g. 0.0005 = 0.05%).
        """
        if commission_rate < 0:
            raise ValueError(f"commission_rate must be >= 0, got {commission_rate}")
        if slippage_rate < 0:
            raise ValueError(f"slippage_rate must be >= 0, got {slippage_rate}")

        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.pending_orders: List[OrderEvent] = []

    def queue_order(self, event: OrderEvent) -> None:
        """
        Queues an order for deferred execution on the next market tick.
        """
        if event.quantity <= 0:
            logger.warning(f"Rejected order with non-positive quantity: {event}")
            return
        self.pending_orders.append(event)

    def process_market_event(self, event: MarketEvent) -> List[FillEvent]:
        """
        Fills all pending orders matching this symbol using the current bar's price structure.

        Critical anti-lookahead mechanism:
        - Market ('MKT') orders are filled at the Open price of the current bar (plus slippage).
        - Limit ('LMT') orders are checked against the High/Low price range of the current bar.
          If hit, they are filled at the limit price (or Open price if there was favorable gapping,
          representing price improvement) without slippage. If not hit, they remain pending.
        """
        fills: List[FillEvent] = []
        remaining_orders: List[OrderEvent] = []

        for order in self.pending_orders:
            if order.symbol != event.symbol:
                # Order is for a different symbol; keep it pending
                remaining_orders.append(order)
                continue

            fill_price: float
            slippage_offset: float = 0.0

            # Handle Limit order matching
            if order.order_type == 'LMT':
                if order.price is None:
                    raise ValueError(f"Limit order for {order.symbol} missing price parameter.")

                limit_hit = False
                fill_price = order.price

                if order.direction == 'BUY':
                    if event.low_price <= order.price:
                        limit_hit = True
                        # If Open gaps down below our limit price, we get filled at the better Open price.
                        fill_price = min(order.price, event.open_price)
                elif order.direction == 'SELL':
                    if event.high_price >= order.price:
                        limit_hit = True
                        # If Open gaps up above our limit price, we get filled at the better Open price.
                        fill_price = max(order.price, event.open_price)

                if not limit_hit:
                    # Limit price not reached on this bar; keep the order pending
                    remaining_orders.append(order)
                    continue

            # Handle Market order matching
            else:
                base_price = event.open_price
                direction_multiplier = 1 if order.direction == 'BUY' else -1
                slippage_offset = base_price * self.slippage_rate
                fill_price = base_price + (direction_multiplier * slippage_offset)

            # Commission calculation
            transaction_value = fill_price * order.quantity
            commission_fee = transaction_value * self.commission_rate

            fills.append(FillEvent(
                symbol=order.symbol,
                timestamp=event.timestamp,
                quantity=order.quantity,
                direction=order.direction,
                fill_price=fill_price,
                commission=commission_fee,
                slippage=slippage_offset
            ))

        self.pending_orders = remaining_orders
        return fills
