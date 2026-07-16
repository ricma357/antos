import os
import logging
import pandas as pd
from typing import List, Generator
from datetime import datetime
from src.events import MarketEvent

logger = logging.getLogger(__name__)


class HistoricalCSVDataProvider:
    """
    Historical data feed that streams daily OHLCV rows as a sequential event stream.

    Loads one or multiple assets, merges them chronologically, and acts as a generator
    yielding MarketEvents. This ensures complete temporal isolation for the backtester.
    """

    REQUIRED_COLUMNS = {'Date', 'Open', 'High', 'Low', 'Close', 'Volume'}

    def __init__(self, data_dir: str, symbols: List[str]):
        """
        Args:
            data_dir (str): Folder containing the CSV files.
            symbols (List[str]): List of instrument tickers to parse.
        
        Raises:
            FileNotFoundError: If a CSV for any symbol is missing.
            ValueError: If the CSV schema is invalid or data is empty.
        """
        self.data_dir = data_dir
        self.symbols = symbols
        self._event_stream: List[MarketEvent] = []
        self._load_and_chronologize()

    def _load_and_chronologize(self) -> None:
        """
        Reads files, validates schema, converts rows to MarketEvents,
        and sorts them chronologically.
        """
        all_events: List[MarketEvent] = []

        for symbol in self.symbols:
            safe_name = symbol.lower().replace('-', '_')
            file_name = f"{safe_name}_daily.csv"
            file_path = os.path.join(self.data_dir, file_name)

            if not os.path.exists(file_path):
                raise FileNotFoundError(
                    f"Historical CSV file not found: {file_path}. Run download_data.py first."
                )

            # Load dataset using pandas
            df = pd.read_csv(file_path)

            # Schema validation — fail fast on corrupted data files
            missing = self.REQUIRED_COLUMNS - set(df.columns)
            if missing:
                raise ValueError(
                    f"CSV for '{symbol}' is missing required columns: {missing}. "
                    f"Found columns: {list(df.columns)}"
                )

            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date')

            # Drop rows with NaN in critical price columns
            price_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            before_len = len(df)
            df = df.dropna(subset=price_cols)
            dropped = before_len - len(df)
            if dropped > 0:
                logger.warning(f"{symbol}: Dropped {dropped} rows with NaN price data")

            # Use Adj Close (dividend & split adjusted) for all signal calculations.
            # Fall back to Close only if Adj Close column is absent.
            close_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'

            for _, row in df.iterrows():
                # Extract clean timezone-naive datetime representation
                timestamp = row['Date'].to_pydatetime()

                market_bar = MarketEvent(
                    timestamp=timestamp,
                    symbol=symbol,
                    open_price=float(row['Open']),
                    high_price=float(row['High']),
                    low_price=float(row['Low']),
                    close_price=float(row[close_col]),
                    volume=int(row['Volume'])
                )
                all_events.append(market_bar)

        if not all_events:
            raise ValueError("No market data was loaded. Check your data directory and symbols.")

        # Chronological sort with deterministic secondary key (symbol) to prevent
        # non-deterministic processing order when multiple assets share the same timestamp
        self._event_stream = sorted(all_events, key=lambda x: (x.timestamp, x.symbol))
        logger.info(f"Ingested {len(self._event_stream)} daily bars across {len(self.symbols)} instruments.")

    def stream_events(self) -> Generator[MarketEvent, None, None]:
        """
        Generator yielding MarketEvents chronologically.
        """
        for event in self._event_stream:
            yield event
