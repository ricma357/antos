import os
import tempfile
import unittest

from src.data_provider import HistoricalCSVDataProvider


def write_csv(data_dir, symbol, rows, header="Date,Open,High,Low,Close,Volume"):
    safe = symbol.lower().replace("-", "_")
    path = os.path.join(data_dir, f"{safe}_daily.csv")
    with open(path, "w") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")
    return path


class TestHistoricalCSVDataProvider(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_loads_and_streams_chronologically(self):
        write_csv(self.data_dir, "SPY", [
            "2024-01-03,102,103,101,102.5,1000",
            "2024-01-02,100,101,99,100.5,1000",   # deliberately out of order
        ])
        provider = HistoricalCSVDataProvider(self.data_dir, ["SPY"])
        events = list(provider.stream_events())
        self.assertEqual(len(events), 2)
        self.assertLess(events[0].timestamp, events[1].timestamp)
        self.assertEqual(events[0].open_price, 100.0)

    def test_multi_symbol_merge_deterministic_tiebreak(self):
        write_csv(self.data_dir, "SPY", ["2024-01-02,100,101,99,100.5,1000"])
        write_csv(self.data_dir, "AAPL", ["2024-01-02,50,51,49,50.5,2000"])
        provider = HistoricalCSVDataProvider(self.data_dir, ["SPY", "AAPL"])
        events = list(provider.stream_events())
        # Same timestamp → sorted by symbol name: AAPL before SPY
        self.assertEqual([e.symbol for e in events], ["AAPL", "SPY"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            HistoricalCSVDataProvider(self.data_dir, ["TSLA"])

    def test_missing_column_raises(self):
        write_csv(self.data_dir, "SPY", ["2024-01-02,100,101,99,1000"],
                  header="Date,Open,High,Low,Volume")  # no Close
        with self.assertRaises(ValueError):
            HistoricalCSVDataProvider(self.data_dir, ["SPY"])

    def test_nan_rows_dropped(self):
        write_csv(self.data_dir, "SPY", [
            "2024-01-02,100,101,99,100.5,1000",
            "2024-01-03,,103,101,102.5,1000",     # NaN Open
        ])
        provider = HistoricalCSVDataProvider(self.data_dir, ["SPY"])
        self.assertEqual(len(list(provider.stream_events())), 1)

    def test_adj_close_preferred_over_close(self):
        write_csv(self.data_dir, "SPY",
                  ["2024-01-02,100,101,99,100.5,95.0,1000"],
                  header="Date,Open,High,Low,Close,Adj Close,Volume")
        provider = HistoricalCSVDataProvider(self.data_dir, ["SPY"])
        event = next(provider.stream_events())
        self.assertEqual(event.close_price, 95.0)

    def test_date_range_filtering(self):
        write_csv(self.data_dir, "SPY", [
            "2024-01-02,100,101,99,100.5,1000",
            "2024-01-03,101,102,100,101.5,1000",
            "2024-01-04,102,103,101,102.5,1000",
            "2024-01-05,103,104,102,103.5,1000",
        ])
        provider = HistoricalCSVDataProvider(
            self.data_dir, ["SPY"],
            start_date="2024-01-03", end_date="2024-01-04",
        )
        events = list(provider.stream_events())
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].open_price, 101.0)
        self.assertEqual(events[-1].open_price, 102.0)

    def test_empty_data_raises(self):
        write_csv(self.data_dir, "SPY", [])
        with self.assertRaises(ValueError):
            HistoricalCSVDataProvider(self.data_dir, ["SPY"])


if __name__ == "__main__":
    unittest.main()
