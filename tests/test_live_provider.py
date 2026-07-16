import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from datetime import datetime
from src.live_data_provider import LiveDataProvider

class TestLiveDataProvider(unittest.TestCase):
    @patch("yfinance.download")
    def test_get_latest_bars_multi_ticker(self, mock_download):
        # Create a mock MultiIndex DataFrame resembling yfinance download output
        columns = pd.MultiIndex.from_product(
            [["SPY", "BTC-USD"], ["Open", "High", "Low", "Close", "Volume"]],
            names=["ticker", "field"]
        )
        dates = [pd.Timestamp("2026-06-26"), pd.Timestamp("2026-06-27")]
        data = [
            [550.0, 555.0, 548.0, 552.0, 100000, 60000.0, 61000.0, 59500.0, 60500.0, 500],
            [553.0, 558.0, 551.0, 556.0, 110000, 60600.0, 62000.0, 60100.0, 61500.0, 600]
        ]
        mock_df = pd.DataFrame(data, index=dates, columns=columns)
        mock_download.return_value = mock_df

        provider = LiveDataProvider()
        bars = provider.get_latest_bars(["SPY", "BTC-USD"])

        # Check yfinance was invoked correctly
        mock_download.assert_called_once_with(
            tickers=["SPY", "BTC-USD"],
            period="2d",
            interval="1d",
            progress=False,
            group_by="ticker",
            session=None
        )

        # Assert results
        self.assertEqual(len(bars), 2)
        spy_bar = next(b for b in bars if b.symbol == "SPY")
        btc_bar = next(b for b in bars if b.symbol == "BTC-USD")

        self.assertEqual(spy_bar.close_price, 556.0)
        self.assertEqual(spy_bar.volume, 110000)
        self.assertEqual(btc_bar.close_price, 61500.0)
        self.assertEqual(btc_bar.volume, 600)

if __name__ == "__main__":
    unittest.main()
