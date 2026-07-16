import unittest
import tempfile
import os
from src.journal import TradeJournal

class TestTradeJournal(unittest.TestCase):
    def setUp(self):
        # Create a temporary file for the database to keep tests isolated
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.journal = TradeJournal(self.db_path)

    def tearDown(self):
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_add_and_retrieve_trade(self):
        self.journal.add_trade(
            timestamp="2026-06-27 03:00:00",
            strategy_id="test_strat",
            symbol="SPY",
            direction="BUY",
            quantity=10,
            price=500.0,
            commission=5.0,
            realized_pnl=0.0,
            remaining_cash=5000.0,
            position_after=10
        )
        
        trades = self.journal.get_trades(limit=5)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["symbol"], "SPY")
        self.assertEqual(trades[0]["direction"], "BUY")
        self.assertEqual(trades[0]["quantity"], 10)
        self.assertEqual(trades[0]["price"], 500.0)
        self.assertEqual(trades[0]["remaining_cash"], 5000.0)

    def test_performance_summary(self):
        # 1. Winning trade
        self.journal.add_trade(
            timestamp="2026-06-27 03:00:00",
            strategy_id="test_strat",
            symbol="BTC-USD",
            direction="SELL",
            quantity=1,
            price=61000.0,
            commission=10.0,
            realized_pnl=1000.0,  # $1,000 profit
            remaining_cash=6000.0,
            position_after=0
        )
        
        # 2. Losing trade
        self.journal.add_trade(
            timestamp="2026-06-27 03:05:00",
            strategy_id="test_strat",
            symbol="BTC-USD",
            direction="SELL",
            quantity=1,
            price=59000.0,
            commission=10.0,
            realized_pnl=-500.0,  # $500 loss
            remaining_cash=5500.0,
            position_after=0
        )
        
        # Run SQL aggregate query metrics calculation
        summary = self.journal.get_performance_summary("test_strat")
        self.assertEqual(summary["total_trades"], 2)
        self.assertEqual(summary["total_pnl"], 500.0)
        self.assertEqual(summary["win_rate_pct"], 50.0)
        self.assertEqual(summary["profit_factor"], 2.0)  # 1000 / 500 = 2.0

if __name__ == "__main__":
    unittest.main()
