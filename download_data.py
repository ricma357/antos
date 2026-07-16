import os
import yfinance as yf
import pandas as pd

def download_historical_data(symbol: str, start_date: str, end_date: str, output_dir: str) -> None:
    """
    Downloads daily historical OHLCV data for a ticker and saves it as a CSV file.
    
    Args:
        symbol (str): The asset ticker code (e.g. 'SPY', 'BTC-USD').
        start_date (str): Fetch start window (YYYY-MM-DD).
        end_date (str): Fetch end window (YYYY-MM-DD).
        output_dir (str): Relative or absolute target directory path.
    """
    print(f"Initiating historical fetch for {symbol}...")
    try:
        df = yf.download(symbol, start=start_date, end=end_date)
        if df.empty:
            print(f"Error: Empty dataset returned for symbol '{symbol}'. Verify ticker.")
            return

        # Flatten multi-index columns if present in newer yfinance versions
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Reset index to guarantee Date becomes a standard column
        df = df.reset_index()

        # Clean symbol string for safe file storage
        safe_name = symbol.lower().replace('-', '_')
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f"{safe_name}_daily.csv")

        # Save to disk
        df.to_csv(file_path, index=False)
        print(f"Data saved to {file_path} | Record Count: {len(df)}")
    except Exception as e:
        print(f"Failed to fetch data for {symbol}: {str(e)}")

if __name__ == "__main__":
    DATA_PATH = "/Users/flipis/dev/antos/data"
    
    # Downloading highly liquid benchmark assets for testing
    download_historical_data("SPY", "2020-01-01", "2026-05-01", DATA_PATH)
    download_historical_data("BTC-USD", "2020-01-01", "2026-05-01", DATA_PATH)
    download_historical_data("AAPL", "2020-01-01", "2026-05-01", DATA_PATH)
    download_historical_data("TSLA", "2020-01-01", "2026-05-01", DATA_PATH)
    download_historical_data("ETH-USD", "2020-01-01", "2026-05-01", DATA_PATH)
