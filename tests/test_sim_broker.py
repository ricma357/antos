import unittest
from datetime import datetime

from src.execution.sim_broker import SimulatedBroker
from src.events import MarketEvent, OrderEvent


def make_bar(symbol="SPY", open_=100.0, high=105.0, low=95.0, close=102.0,
             ts=None):
    return MarketEvent(
        timestamp=ts or datetime(2024, 1, 2),
        symbol=symbol,
        open_price=open_,
        high_price=high,
        low_price=low,
        close_price=close,
        volume=1_000_000,
    )


class TestSimulatedBrokerValidation(unittest.TestCase):
    def test_negative_commission_raises(self):
        with self.assertRaises(ValueError):
            SimulatedBroker(commission_rate=-0.001)

    def test_negative_slippage_raises(self):
        with self.assertRaises(ValueError):
            SimulatedBroker(slippage_rate=-0.0005)

    def test_non_positive_quantity_rejected(self):
        broker = SimulatedBroker()
        broker.queue_order(OrderEvent(symbol="SPY", order_type="MKT",
                                      quantity=0, direction="BUY"))
        self.assertEqual(broker.pending_orders, [])


class TestMarketOrders(unittest.TestCase):
    def setUp(self):
        self.broker = SimulatedBroker(commission_rate=0.001, slippage_rate=0.0005)

    def test_buy_fills_at_open_plus_slippage(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="MKT",
                                           quantity=10, direction="BUY"))
        fills = self.broker.process_market_event(make_bar(open_=100.0))
        self.assertEqual(len(fills), 1)
        fill = fills[0]
        self.assertAlmostEqual(fill.fill_price, 100.0 + 100.0 * 0.0005)
        self.assertAlmostEqual(fill.commission, fill.fill_price * 10 * 0.001)
        self.assertEqual(fill.quantity, 10)
        self.assertEqual(self.broker.pending_orders, [])

    def test_sell_fills_at_open_minus_slippage(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="MKT",
                                           quantity=5, direction="SELL"))
        fills = self.broker.process_market_event(make_bar(open_=200.0))
        self.assertAlmostEqual(fills[0].fill_price, 200.0 - 200.0 * 0.0005)

    def test_order_for_other_symbol_stays_pending(self):
        self.broker.queue_order(OrderEvent(symbol="AAPL", order_type="MKT",
                                           quantity=10, direction="BUY"))
        fills = self.broker.process_market_event(make_bar(symbol="SPY"))
        self.assertEqual(fills, [])
        self.assertEqual(len(self.broker.pending_orders), 1)

    def test_zero_slippage_fills_exactly_at_open(self):
        broker = SimulatedBroker(commission_rate=0.0, slippage_rate=0.0)
        broker.queue_order(OrderEvent(symbol="SPY", order_type="MKT",
                                      quantity=1, direction="BUY"))
        fills = broker.process_market_event(make_bar(open_=123.45))
        self.assertEqual(fills[0].fill_price, 123.45)
        self.assertEqual(fills[0].commission, 0.0)


class TestLimitOrders(unittest.TestCase):
    def setUp(self):
        self.broker = SimulatedBroker(commission_rate=0.0, slippage_rate=0.0005)

    def test_buy_limit_hit_fills_at_limit_price(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="LMT",
                                           quantity=10, direction="BUY", price=97.0))
        fills = self.broker.process_market_event(make_bar(open_=100.0, low=96.0))
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].fill_price, 97.0)
        self.assertEqual(fills[0].slippage, 0.0)  # limit fills carry no slippage

    def test_buy_limit_gap_down_price_improvement(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="LMT",
                                           quantity=10, direction="BUY", price=97.0))
        # Open gaps below the limit → filled at the better Open price
        fills = self.broker.process_market_event(make_bar(open_=95.0, low=94.0))
        self.assertEqual(fills[0].fill_price, 95.0)

    def test_buy_limit_not_hit_stays_pending(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="LMT",
                                           quantity=10, direction="BUY", price=90.0))
        fills = self.broker.process_market_event(make_bar(low=95.0))
        self.assertEqual(fills, [])
        self.assertEqual(len(self.broker.pending_orders), 1)

    def test_sell_limit_hit_fills_at_limit_price(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="LMT",
                                           quantity=10, direction="SELL", price=104.0))
        fills = self.broker.process_market_event(make_bar(open_=100.0, high=105.0))
        self.assertEqual(fills[0].fill_price, 104.0)

    def test_sell_limit_gap_up_price_improvement(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="LMT",
                                           quantity=10, direction="SELL", price=104.0))
        fills = self.broker.process_market_event(make_bar(open_=110.0, high=112.0))
        self.assertEqual(fills[0].fill_price, 110.0)

    def test_limit_order_without_price_raises(self):
        self.broker.queue_order(OrderEvent(symbol="SPY", order_type="LMT",
                                           quantity=10, direction="BUY", price=None))
        with self.assertRaises(ValueError):
            self.broker.process_market_event(make_bar())


if __name__ == "__main__":
    unittest.main()
