import os
import logging
from typing import List, Dict, Any
import requests
from datetime import datetime

from src.execution.base import BaseExecutionHandler
from src.events import OrderEvent, FillEvent, MarketEvent

logger = logging.getLogger(__name__)

class AlpacaPaperBroker(BaseExecutionHandler):
    """
    Execution handler that interfaces with Alpaca's Paper Trading API.
    Converts OrderEvents into live paper orders submitted to Alpaca,
    and polls the Alpaca API to map fills into FillEvents.
    """

    def __init__(self, api_key: str = None, api_secret: str = None, base_url: str = None):
        # Load credentials from arguments or environment variables
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self.api_secret = api_secret or os.environ.get("ALPACA_API_SECRET")
        self.base_url = base_url or os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if not self.api_key or not self.api_secret:
            logger.warning(
                "Alpaca API credentials missing. Please set ALPACA_API_KEY and ALPACA_API_SECRET. "
                "AlpacaPaperBroker will fail to execute orders."
            )

        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json"
        }

        # Track orders: alpaca_order_id -> OrderEvent
        self.pending_orders: Dict[str, OrderEvent] = {}

    def _map_symbol_to_alpaca(self, symbol: str) -> str:
        # Convert crypto tickers (e.g. BTC-USD -> BTC/USD)
        if "-" in symbol:
            return symbol.replace("-", "/")
        return symbol

    def queue_order(self, event: OrderEvent) -> None:
        """
        Submits order directly to Alpaca paper API.
        """
        if not self.api_key or not self.api_secret:
            logger.error("Cannot queue order: Alpaca credentials missing.")
            return

        if event.quantity <= 0:
            logger.warning(f"Rejected order with non-positive quantity: {event}")
            return

        alpaca_symbol = self._map_symbol_to_alpaca(event.symbol)
        side = event.direction.lower()  # 'buy' or 'sell'
        order_type = event.order_type.lower()  # 'mkt' or 'lmt' -> 'market' or 'limit'
        if order_type == 'mkt':
            order_type = 'market'
        elif order_type == 'lmt':
            order_type = 'limit'

        payload = {
            "symbol": alpaca_symbol,
            "qty": str(event.quantity),
            "side": side,
            "type": order_type,
            "time_in_force": "day"
        }

        if order_type == 'limit':
            if event.price is None:
                logger.error(f"Limit order for {event.symbol} missing price parameter.")
                return
            payload["limit_price"] = str(event.price)

        url = f"{self.base_url}/v2/orders"
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            if response.status_code == 200 or response.status_code == 201:
                order_data = response.json()
                alpaca_order_id = order_data["id"]
                self.pending_orders[alpaca_order_id] = event
                logger.info(f"Successfully placed order on Alpaca. Order ID: {alpaca_order_id} | Symbol: {event.symbol}")
            else:
                logger.error(f"Alpaca order placement failed: Code {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Network error placing order on Alpaca: {e}", exc_info=True)

    def process_market_event(self, event: MarketEvent) -> List[FillEvent]:
        """
        Polls the status of pending Alpaca orders to verify if fills have occurred.
        Returns a list of FillEvents for completed transactions.
        """
        if not self.pending_orders:
            return []

        fills: List[FillEvent] = []
        completed_order_ids: List[str] = []

        # Process each pending order
        for order_id, order_event in list(self.pending_orders.items()):
            # Only poll if the current market tick is for the same symbol
            if order_event.symbol != event.symbol:
                continue

            url = f"{self.base_url}/v2/orders/{order_id}"
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    logger.error(f"Failed to fetch order status for {order_id}: {response.status_code}")
                    continue

                order_data = response.json()
                status = order_data.get("status")

                if status == "filled":
                    fill_price = float(order_data.get("filled_avg_price", 0.0))
                    filled_qty = int(order_data.get("filled_qty", order_event.quantity))
                    
                    # Convert Alpaca timestamp (ISO format) to naive datetime
                    filled_at_str = order_data.get("filled_at")
                    if filled_at_str:
                        # e.g. "2026-06-27T00:30:15.123456Z"
                        filled_at = datetime.fromisoformat(filled_at_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    else:
                        filled_at = event.timestamp

                    # Note: Paper trading commissions are typically zero on Alpaca, 
                    # but we keep fields for bookkeeping compatibility.
                    fill_event = FillEvent(
                        symbol=order_event.symbol,
                        timestamp=filled_at,
                        quantity=filled_qty,
                        direction=order_event.direction,
                        fill_price=fill_price,
                        commission=0.0,
                        slippage=0.0
                    )
                    fills.append(fill_event)
                    completed_order_ids.append(order_id)
                    logger.info(f"Alpaca order filled: {order_id} | Symbol: {order_event.symbol} | Price: {fill_price}")

                elif status in ["canceled", "rejected", "expired"]:
                    completed_order_ids.append(order_id)
                    logger.warning(f"Alpaca order {status}: {order_id} | Symbol: {order_event.symbol}")

            except Exception as e:
                logger.error(f"Error checking order status on Alpaca for {order_id}: {e}")

        # Clean up completed orders
        for order_id in completed_order_ids:
            self.pending_orders.pop(order_id, None)

        return fills
