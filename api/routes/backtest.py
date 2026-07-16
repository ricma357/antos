import os
from fastapi import APIRouter, HTTPException
from api.models import BacktestRequest, BacktestResponse, EquityPoint, TradeLogEntry
from src.engine import BacktestEngine
from src.execution.sim_broker import SimulatedBroker
from src.strategy.sma_crossover import SMACrossover
from src.strategy.rsi_mean_reversion import RSIMeanReversion
from src.strategy.peak_breakout_pullback import PeakBreakoutPullback
from src.strategy.volatility_squeeze import VolatilitySqueezeMomentum
from src.strategy.rolling_ridge import RollingRidgeDirectionalPredictor

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

def get_strategy_instance(strategy_id: str, params: dict):
    if strategy_id == "sma_crossover":
        return SMACrossover(
            short_window=params.get("short_window", 50),
            long_window=params.get("long_window", 200)
        )
    elif strategy_id == "rsi_mean_reversion":
        return RSIMeanReversion(
            period=params.get("period", 14),
            oversold=params.get("oversold", 30.0),
            overbought=params.get("overbought", 70.0),
            strength=params.get("strength", 0.20)
        )
    elif strategy_id == "peak_breakout_pullback":
        return PeakBreakoutPullback(
            lookback_window=params.get("lookback_window", 5),
            atr_period=params.get("atr_period", 14),
            vol_sma_period=params.get("vol_sma_period", 20),
            atr_multiplier=params.get("atr_multiplier", 3.0),
            strength=params.get("strength", 0.20)
        )
    elif strategy_id == "volatility_squeeze":
        return VolatilitySqueezeMomentum(
            bb_period=params.get("bb_period", 20),
            bb_std=params.get("bb_std", 2.0),
            squeeze_lookback=params.get("squeeze_lookback", 120),
            squeeze_percentile=params.get("squeeze_percentile", 20.0),
            roc_period=params.get("roc_period", 10),
            atr_period=params.get("atr_period", 14),
            atr_trail_mult=params.get("atr_trail_mult", 2.5),
            patience=params.get("patience", 5),
            strength=params.get("strength", 0.50)
        )
    elif strategy_id == "rolling_ridge":
        return RollingRidgeDirectionalPredictor(
            lookback_window=params.get("lookback_window", 90),
            l2_lambda=params.get("l2_lambda", 1.0),
            prediction_threshold=params.get("prediction_threshold", 0.001),
            strength=params.get("strength", 0.50),
            trend_filter_window=params.get("trend_filter_window", 200)
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy_id}")

@router.post("/", response_model=BacktestResponse)
def run_backtest(req: BacktestRequest):
    """Executes a backtest for a specific strategy and returns the structured results."""
    try:
        strategy = get_strategy_instance(req.strategy_id, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    broker = SimulatedBroker(
        commission_rate=req.commission_rate,
        slippage_rate=req.slippage_rate
    )

    try:
        engine = BacktestEngine(
            data_dir=DATA_DIR,
            symbols=req.symbols,
            initial_cash=req.initial_cash,
            strategy=strategy,
            execution_handler=broker,
            risk_free_rate=req.risk_free_rate
        )
        
        # Format the strategy name with parameters for display
        name_parts = [f"{k}={v}" for k, v in req.params.items()]
        display_name = f"{req.strategy_id} ({', '.join(name_parts)})"
        
        result = engine.run(strategy_name=display_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest engine error: {str(e)}")

    # Map the pandas dataframe to the API schema
    equity_points = []
    drawdown_points = []
    date_start = ""
    date_end = ""
    
    if not result.equity_df.empty:
        # CRITICAL: Sort by index (Date) to prevent TradingView chart crash.
        # When multiple assets are combined (e.g. AAPL + ETH-USD), crypto dates
        # (weekends) interleave with stock dates, creating unsorted timestamps.
        df_sorted = result.equity_df.sort_index()
        
        # Deduplicate: keep only the last entry per date
        df_sorted = df_sorted[~df_sorted.index.duplicated(keep='last')]
        
        date_start = df_sorted.index[0].strftime('%Y-%m-%d')
        date_end = df_sorted.index[-1].strftime('%Y-%m-%d')
        
        df_reset = df_sorted.reset_index()
        for _, row in df_reset.iterrows():
            date_str = row['Date'].strftime('%Y-%m-%d')
            equity_points.append(EquityPoint(time=date_str, value=round(float(row['Equity']), 2)))
            drawdown_points.append(EquityPoint(time=date_str, value=round(float(row['Drawdown'] * 100), 2)))

    # Map trade log
    trade_log = []
    for t in result.trade_log:
        trade_log.append(TradeLogEntry(
            timestamp=t['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            symbol=t['symbol'],
            direction=t['direction'],
            quantity=int(t['quantity']),
            fill_price=float(t['fill_price']),
            commission=float(t['commission']),
            remaining_cash=float(t['remaining_cash']),
            position_after=int(t['position_after']),
            nav_after=float(t['nav_after'])
        ))

    return BacktestResponse(
        strategy_name=result.strategy_name,
        metrics=result.metrics,
        equity_curve=equity_points,
        drawdown_curve=drawdown_points,
        trade_log=trade_log,
        date_start=date_start,
        date_end=date_end,
    )
