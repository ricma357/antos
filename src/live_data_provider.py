import logging
from typing import List
import pandas as pd
import yfinance as yf
from src.events import MarketEvent

logger = logging.getLogger(__name__)

class LiveDataProvider:
    """
    Live data provider fetching real-time market ticks/bars from external APIs.
    Currently integrates with Yahoo Finance (yfinance).
    """

    def __init__(self, proxy: str = None):
        self.proxy = proxy

    def get_latest_bars(self, symbols: List[str]) -> List[MarketEvent]:
        """
        Fetches the latest completed daily candle for each requested symbol.
        Returns a list of MarketEvent objects.
        """
        if not symbols:
            return []

        events: List[MarketEvent] = []
        
        try:
            session = None
            if self.proxy:
                import requests
                session = requests.Session()
                session.proxies = {
                    "http": self.proxy,
                    "https": self.proxy
                }

            # Group by ticker ensures consistent multi-index column layout
            # (Ticker, Field) even if only 1 ticker is requested.
            df = yf.download(
                tickers=symbols,
                period="2d",
                interval="1d",
                progress=False,
                group_by="ticker",
                session=session
            )
            
            if df.empty:
                logger.error(f"yfinance returned empty dataset for tickers: {symbols}")
                return []

            for symbol in symbols:
                try:
                    # Clean symbol string to match yfinance group layout
                    if len(symbols) > 1 or isinstance(df.columns, pd.MultiIndex):
                        if symbol not in df.columns.levels[0]:
                            logger.warning(f"Ticker {symbol} not found in yfinance output columns.")
                            continue
                        ticker_df = df[symbol].dropna(how="all")
                    else:
                        ticker_df = df.dropna(how="all")

                    if ticker_df.empty:
                        logger.warning(f"No recent data points found for symbol {symbol}")
                        continue

                    # Extract the latest bar
                    last_row = ticker_df.iloc[-1]
                    candle_date = ticker_df.index[-1]
                    
                    # Convert to timezone-naive datetime object
                    if hasattr(candle_date, 'to_pydatetime'):
                        timestamp = candle_date.to_pydatetime()
                    else:
                        timestamp = pd.to_datetime(candle_date).to_pydatetime()
                        
                    # Standardize timezone to naive UTC-like representation
                    if timestamp.tzinfo is not None:
                        timestamp = timestamp.replace(tzinfo=None)
                    
                    close_col = 'Adj Close' if 'Adj Close' in last_row and not pd.isna(last_row['Adj Close']) else 'Close'
                    
                    event = MarketEvent(
                        timestamp=timestamp,
                        symbol=symbol,
                        open_price=float(last_row['Open']),
                        high_price=float(last_row['High']),
                        low_price=float(last_row['Low']),
                        close_price=float(last_row[close_col]),
                        volume=int(last_row['Volume'])
                    )
                    events.append(event)
                except Exception as sym_ex:
                    logger.error(f"Failed to parse live bar for symbol {symbol}: {sym_ex}")
                    
        except Exception as ex:
            logger.error(f"Failed to fetch live data from yfinance: {ex}")

        return events
