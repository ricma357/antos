import unittest
from datetime import datetime

from src.portfolio import Portfolio
from src.events import MarketEvent, SignalEvent, FillEvent


TS = datetime(2024, 1, 2)


def make_bar(symbol="SPY", close=100.0, ts=TS):
    return MarketEvent(
        timestamp=ts, symbol=symbol,
        open_price=close, high_price=close, low_price=close,
        close_price=close, volume=1_000_000,
    )


def make_signal(symbol="SPY", signal_type="LONG", strength=0.5, ts=TS):
    return SignalEvent(symbol=symbol, timestamp=ts,
                       signal_type=signal_type, strength=strength)


def make_fill(symbol="SPY", qty=10, direction="BUY", price=100.0,
              commission=1.0, ts=TS):
    return FillEvent(symbol=symbol, timestamp=ts, quantity=qty,
                     direction=direction, fill_price=price,
                     commission=commission)


class TestPortfolioInit(unittest.TestCase):
    def test_negative_initial_cash_raises(self):
        with self.assertRaises(ValueError):
            Portfolio(initial_cash=-100.0)

    def test_zero_initial_cash_raises(self):
        with self.assertRaises(ValueError):
            Portfolio(initial_cash=0.0)


class TestMarkToMarket(unittest.TestCase):
    def test_equity_snapshot_recorded(self):
        p = Portfolio(initial_cash=100_000.0)
        p.update_market_price(make_bar(close=100.0))
        self.assertEqual(len(p.equity_curve), 1)
        ts, cash, holdings, equity = p.equity_curve[0]
        self.assertEqual(cash, 100_000.0)
        self.assertEqual(holdings, 0.0)
        self.assertEqual(equity, 100_000.0)

    def test_holdings_marked_at_latest_close(self):
        p = Portfolio(initial_cash=100_000.0)
        p.positions["SPY"] = 100
        p.update_market_price(make_bar(close=110.0))
        _, _, holdings, equity = p.equity_curve[-1]
        self.assertEqual(holdings, 100 * 110.0)
        self.assertEqual(equity, 100_000.0 + 11_000.0)


class TestGenerateOrderLong(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(initial_cash=100_000.0)
        self.p.update_market_price(make_bar(close=100.0))

    def test_long_from_flat_sizes_off_nav(self):
        order = self.p.generate_order(make_signal(strength=0.5))
        self.assertIsNotNone(order)
        self.assertEqual(order.direction, "BUY")
        # 100k NAV * 0.5 strength / $100 = 500 shares
        self.assertEqual(order.quantity, 500)
        self.assertEqual(self.p.reserved_cash["SPY"], 500 * 100.0)

    def test_long_clamped_to_available_cash(self):
        # NAV includes holdings, so full-strength target can exceed free cash.
        self.p.positions["SPY"] = 0
        self.p.positions["AAPL"] = 500          # $50k of holdings
        self.p.cash = 50_000.0
        self.p.latest_prices["AAPL"] = 100.0
        # NAV = 100k → target 1000 shares = $100k, but only $50k cash free.
        order = self.p.generate_order(make_signal(strength=1.0))
        self.assertEqual(order.quantity, 500)   # clamped to affordable

    def test_long_respects_reserved_cash(self):
        first = self.p.generate_order(make_signal(strength=1.0))
        self.assertEqual(first.quantity, 1000)  # all cash committed
        # Second buy signal for another symbol must see zero free cash.
        self.p.update_market_price(make_bar(symbol="AAPL", close=50.0))
        second = self.p.generate_order(make_signal(symbol="AAPL", strength=1.0))
        self.assertIsNone(second)

    def test_duplicate_long_ignored(self):
        self.p.positions["SPY"] = 100
        self.assertIsNone(self.p.generate_order(make_signal(signal_type="LONG")))

    def test_no_known_price_returns_none(self):
        self.assertIsNone(self.p.generate_order(make_signal(symbol="TSLA")))

    def test_unknown_signal_type_returns_none(self):
        self.assertIsNone(self.p.generate_order(make_signal(signal_type="HOLD")))


class TestGenerateOrderShortAndExit(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(initial_cash=100_000.0)
        self.p.update_market_price(make_bar(close=100.0))

    def test_short_from_flat(self):
        order = self.p.generate_order(make_signal(signal_type="SHORT", strength=0.3))
        self.assertEqual(order.direction, "SELL")
        self.assertEqual(order.quantity, 300)

    def test_short_while_long_liquidates_and_flips(self):
        self.p.positions["SPY"] = 200
        order = self.p.generate_order(make_signal(signal_type="SHORT", strength=0.5))
        self.assertEqual(order.direction, "SELL")
        # NAV = 100k cash + 20k holdings = 120k → target 600 short + 200 liquidation
        self.assertEqual(order.quantity, 600 + 200)

    def test_long_while_short_covers_and_flips(self):
        self.p.positions["SPY"] = -200
        order = self.p.generate_order(make_signal(signal_type="LONG", strength=0.5))
        self.assertEqual(order.direction, "BUY")
        # NAV = 100k - 20k = 80k → target 400 long + 200 cover, all affordable
        self.assertEqual(order.quantity, 400 + 200)

    def test_exit_long_sells_full_position(self):
        self.p.positions["SPY"] = 150
        order = self.p.generate_order(make_signal(signal_type="EXIT"))
        self.assertEqual(order.direction, "SELL")
        self.assertEqual(order.quantity, 150)

    def test_exit_short_buys_to_cover(self):
        self.p.positions["SPY"] = -150
        order = self.p.generate_order(make_signal(signal_type="EXIT"))
        self.assertEqual(order.direction, "BUY")
        self.assertEqual(order.quantity, 150)

    def test_exit_flat_returns_none(self):
        self.assertIsNone(self.p.generate_order(make_signal(signal_type="EXIT")))


class TestUpdateFill(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(initial_cash=100_000.0)
        self.p.update_market_price(make_bar(close=100.0))

    def test_buy_fill_updates_cash_position_and_avg_price(self):
        self.p.update_fill(make_fill(qty=100, direction="BUY", price=100.0, commission=10.0))
        self.assertEqual(self.p.positions["SPY"], 100)
        self.assertEqual(self.p.cash, 100_000.0 - (100 * 100.0 + 10.0))
        self.assertEqual(self.p.holdings_avg_price["SPY"], 100.0)
        self.assertEqual(len(self.p.trade_log), 1)

    def test_buy_fill_releases_reserved_cash(self):
        self.p.reserved_cash["SPY"] = 10_000.0
        self.p.update_fill(make_fill(qty=100, direction="BUY", price=100.0))
        self.assertNotIn("SPY", self.p.reserved_cash)

    def test_averaging_up_recomputes_weighted_cost(self):
        self.p.update_fill(make_fill(qty=100, direction="BUY", price=100.0, commission=0.0))
        self.p.update_fill(make_fill(qty=100, direction="BUY", price=120.0, commission=0.0))
        self.assertEqual(self.p.positions["SPY"], 200)
        self.assertAlmostEqual(self.p.holdings_avg_price["SPY"], 110.0)

    def test_sell_fill_updates_cash_and_position(self):
        self.p.update_fill(make_fill(qty=100, direction="BUY", price=100.0, commission=0.0))
        cash_before = self.p.cash
        self.p.update_fill(make_fill(qty=100, direction="SELL", price=110.0, commission=5.0))
        self.assertEqual(self.p.positions["SPY"], 0)
        self.assertEqual(self.p.cash, cash_before + (100 * 110.0 - 5.0))
        self.assertEqual(self.p.holdings_avg_price["SPY"], 0.0)

    def test_short_entry_records_avg_entry_price(self):
        self.p.update_fill(make_fill(qty=100, direction="SELL", price=100.0, commission=0.0))
        self.assertEqual(self.p.positions["SPY"], -100)
        self.assertEqual(self.p.holdings_avg_price["SPY"], 100.0)

    def test_trade_log_captures_nav_after(self):
        self.p.update_fill(make_fill(qty=100, direction="BUY", price=100.0, commission=0.0))
        entry = self.p.trade_log[-1]
        self.assertEqual(entry["position_after"], 100)
        # NAV unchanged by the purchase itself (cash → holdings at same price)
        self.assertAlmostEqual(entry["nav_after"], 100_000.0)


if __name__ == "__main__":
    unittest.main()
