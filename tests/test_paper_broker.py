import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
from src.execution.paper_broker import AlpacaPaperBroker
from src.events import OrderEvent, MarketEvent

class TestAlpacaPaperBroker(unittest.TestCase):
    def setUp(self):
        # Initialize with dummy API keys
        self.broker = AlpacaPaperBroker(
            api_key="TEST_KEY",
            api_secret="TEST_SECRET",
            base_url="https://paper-api.alpaca.markets"
        )

    @patch("requests.post")
    def test_queue_order_success(self, mock_post):
        # Mock successful order response from Alpaca
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "order-123-abc",
            "symbol": "SPY",
            "qty": "10",
            "side": "buy",
            "status": "accepted"
        }
        mock_post.return_value = mock_response

        order_event = OrderEvent(
            symbol="SPY",
            order_type="MKT",
            quantity=10,
            direction="BUY"
        )

        self.broker.queue_order(order_event)

        # Ensure post request was made to /v2/orders
        mock_post.assert_called_once()
        self.assertIn("order-123-abc", self.broker.pending_orders)
        self.assertEqual(self.broker.pending_orders["order-123-abc"], order_event)

    @patch("requests.get")
    def test_process_market_event_filled(self, mock_get):
        # Set up a pending order in broker state
        order_event = OrderEvent(
            symbol="BTC-USD",
            order_type="MKT",
            quantity=1,
            direction="BUY"
        )
        self.broker.pending_orders["alpaca-order-btc"] = order_event

        # Mock order filled response from Alpaca
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "alpaca-order-btc",
            "symbol": "BTCUSD",
            "status": "filled",
            "filled_avg_price": "60000.00",
            "filled_qty": "1",
            "filled_at": "2026-06-27T02:00:00.123456Z"
        }
        mock_get.return_value = mock_response

        # Create a market event matching the symbol
        market_event = MarketEvent(
            timestamp=datetime(2026, 6, 27, 2, 0, 0),
            symbol="BTC-USD",
            open_price=59900.0,
            high_price=60100.0,
            low_price=59800.0,
            close_price=60000.0,
            volume=1000
        )

        fills = self.broker.process_market_event(market_event)

        mock_get.assert_called_once_with(
            "https://paper-api.alpaca.markets/v2/orders/alpaca-order-btc",
            headers=self.broker.headers,
            timeout=10
        )
        self.assertEqual(len(fills), 1)
        fill = fills[0]
        self.assertEqual(fill.symbol, "BTC-USD")
        self.assertEqual(fill.fill_price, 60000.0)
        self.assertEqual(fill.quantity, 1)
        self.assertEqual(fill.direction, "BUY")
        self.assertNotIn("alpaca-order-btc", self.broker.pending_orders)

if __name__ == "__main__":
    unittest.main()
