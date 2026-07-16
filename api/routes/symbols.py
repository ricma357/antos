import os
from fastapi import APIRouter
from typing import List

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

@router.get("/symbols", response_model=List[str])
def get_symbols():
    """Scans the data directory and returns a list of available tickers."""
    symbols = []
    if os.path.exists(DATA_DIR):
        for filename in os.listdir(DATA_DIR):
            if filename.endswith("_daily.csv"):
                # e.g. btc_usd_daily.csv -> BTC-USD
                # e.g. spy_daily.csv -> SPY
                base = filename.replace("_daily.csv", "")
                parts = base.split("_")
                if len(parts) > 1:
                    symbol = "-".join(parts).upper()
                else:
                    symbol = parts[0].upper()
                symbols.append(symbol)
    
    return sorted(symbols)
