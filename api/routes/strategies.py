from fastapi import APIRouter
from typing import List
from api.models import StrategyInfo, StrategyParam

router = APIRouter()

# Registry of available strategies with their configuration schemas
AVAILABLE_STRATEGIES = [
    StrategyInfo(
        id="sma_crossover",
        name="SMA Crossover",
        description="Classic trend-following strategy. Uses two Simple Moving Averages (a fast and a slow) to detect momentum shifts. When the fast SMA crosses above the slow SMA (Golden Cross), it signals an uptrend and enters long. When the fast crosses below (Death Cross), it exits. Best suited for trending markets with clear directional bias.",
        parameters=[
            StrategyParam(name="short_window", type="int", default=50,
                          description="Fast SMA period (days). A shorter window (e.g. 20) reacts faster to price changes but generates more false signals. A longer window (e.g. 50) is smoother but slower to react."),
            StrategyParam(name="long_window", type="int", default=200,
                          description="Slow SMA period (days). The industry standard is 200 days. This acts as the trend filter — price above the 200-day SMA is considered bullish territory.")
        ]
    ),
    StrategyInfo(
        id="rsi_mean_reversion",
        name="RSI Mean Reversion",
        description="Counter-trend strategy based on the Relative Strength Index (RSI), developed by J. Welles Wilder in 1978. It buys when an asset is 'oversold' (RSI dips below a threshold) and sells when 'overbought' (RSI exceeds a threshold). Works best in range-bound, sideways markets. Tends to underperform in strong trending markets.",
        parameters=[
            StrategyParam(name="period", type="int", default=14,
                          description="RSI lookback period (bars). The standard is 14. Lower values (e.g. 7) make the RSI more sensitive and generate more signals. Higher values (e.g. 21) produce smoother, slower signals."),
            StrategyParam(name="oversold", type="float", default=30.0,
                          description="Oversold threshold. When RSI drops below this level, the asset is considered 'beaten down' and likely to bounce. Standard is 30. More aggressive traders use 20."),
            StrategyParam(name="overbought", type="float", default=70.0,
                          description="Overbought threshold. When RSI rises above this level, the asset is considered 'overextended' and likely to pull back. Standard is 70. More conservative traders use 80."),
            StrategyParam(name="strength", type="float", default=0.20,
                          description="Capital allocation fraction (0.0–1.0). Controls what percentage of total portfolio value is deployed per trade. 0.20 = 20% of NAV per position. Higher values concentrate risk.")
        ]
    ),
    StrategyInfo(
        id="peak_breakout_pullback",
        name="Peak Breakout Pullback",
        description="Institutional-grade trend breakout strategy. Detects when price breaks above a Donchian Channel (the highest high of N bars) with volume confirmation, waits for a pullback to confirm the breakout is real, then enters on a resumption bar. Uses an ATR-based trailing stop to ride the trend and lock in profits. This is the most sophisticated strategy in the system.",
        parameters=[
            StrategyParam(name="lookback_window", type="int", default=5,
                          description="Donchian Channel lookback (bars). Defines how many bars to scan for the highest high. A value of 5 means 'break above the 5-day high'. Larger values (e.g. 20) require bigger breakouts but filter out more noise."),
            StrategyParam(name="atr_period", type="int", default=14,
                          description="ATR (Average True Range) smoothing period. ATR measures daily price volatility. Used to dynamically set trailing stop distance. Standard is 14. Lower values react faster to volatility changes."),
            StrategyParam(name="vol_sma_period", type="int", default=20,
                          description="Volume SMA lookback (bars). The breakout is only confirmed if volume exceeds this moving average. This filters out low-conviction, low-volume breakouts that often fail. Standard is 20."),
            StrategyParam(name="atr_multiplier", type="float", default=3.0,
                          description="Trailing stop distance in ATR units. The stop is placed this many ATRs below the current price. Higher values (e.g. 4.0) give the trade more room to breathe but risk larger losses. Lower values (e.g. 2.0) lock in profits faster but may exit prematurely."),
            StrategyParam(name="strength", type="float", default=0.20,
                          description="Capital allocation fraction (0.0–1.0). Controls what percentage of total portfolio value is deployed per trade. 0.20 = 20% of NAV per position.")
        ]
    ),
    StrategyInfo(
        id="volatility_squeeze",
        name="Volatility Squeeze Momentum",
        description="Institutional-grade breakout strategy that detects when volatility compresses to abnormally low levels (a 'squeeze'), then enters aggressively when price breaks out. Unlike retail Bollinger Band strategies that buy the lower band and sell the upper band (mean reversion), this strategy does the OPPOSITE — it waits for the bands to squeeze tight, determines momentum direction, and rides the explosive breakout. Default settings deploy 50% of capital per trade for aggressive returns.",
        parameters=[
            StrategyParam(name="bb_period", type="int", default=20,
                          description="Bollinger Band SMA period. Standard is 20. This is the moving average that forms the center of the bands. Lower values make the bands more reactive."),
            StrategyParam(name="bb_std", type="float", default=2.0,
                          description="Bollinger Band standard deviation multiplier. Standard is 2.0. Higher values (e.g. 2.5) make the bands wider, requiring a bigger move to trigger a breakout signal."),
            StrategyParam(name="squeeze_lookback", type="int", default=120,
                          description="Number of bars to compare current BB width against. The squeeze is detected when current width is in the lowest percentile of this history. 120 = ~6 months of daily data."),
            StrategyParam(name="squeeze_percentile", type="float", default=20.0,
                          description="Percentile threshold for squeeze detection. BB width must be below this percentile of its history to qualify. Lower = stricter. 20 = width must be in the bottom 20% of recent history."),
            StrategyParam(name="roc_period", type="int", default=10,
                          description="Rate of Change lookback (bars). Measures momentum direction over this window. 10 = 'is the price higher than 10 bars ago?' Used to confirm breakout direction."),
            StrategyParam(name="atr_period", type="int", default=14,
                          description="ATR smoothing period for the trailing stop. Standard is 14."),
            StrategyParam(name="atr_trail_mult", type="float", default=2.5,
                          description="Trailing stop distance in ATR units. 2.5 = stop is placed 2.5x the daily volatility below the price. Tighter (2.0) = more trades, locks profits faster. Wider (3.5) = rides bigger trends."),
            StrategyParam(name="patience", type="int", default=5,
                          description="Max bars to wait for a breakout after a squeeze is detected. If no breakout occurs within this window, the squeeze is considered a false signal and is discarded."),
            StrategyParam(name="strength", type="float", default=0.50,
                          description="Capital allocation fraction (0.0–1.0). Default is 0.50 (50% of NAV) for aggressive positioning. Increase to 0.80 for maximum aggression, decrease to 0.30 for conservative mode.")
        ]
    ),
    StrategyInfo(
        id="rolling_ridge",
        name="Rolling Ridge Regression (Regime-Aware)",
        description="Defensive hybrid strategy combining Machine Learning (Ridge Regression) with a macro trend filter. In Bull markets (price > 200-SMA), the ML model actively predicts next-candle direction and trades LONG/CASH. In Bear markets (price < 200-SMA), the strategy exits all positions and shelters in cash — avoiding the 'catching falling knives' problem. This reduced the 2008 crisis max drawdown from -57% (old Long-Only ML) to -16% while maintaining positive returns.",
        parameters=[
            StrategyParam(name="lookback_window", type="int", default=90,
                          description="Model training lookback window (bars). Defines the size of the rolling training dataset. Shorter windows (e.g., 45) adapt quickly to new regimes but are noisier; longer windows (e.g., 120) are more stable."),
            StrategyParam(name="l2_lambda", type="float", default=1.0,
                          description="L2 regularization strength (lambda). Restricts the magnitude of coefficients to prevent the model from overfitting to noise. Higher = simpler model, lower = more complex."),
            StrategyParam(name="prediction_threshold", type="float", default=0.001,
                          description="Minimum expected return to trigger a trade signal. E.g., 0.001 requires a predicted 0.1% return. Prevents overtrading on low-conviction signals."),
            StrategyParam(name="strength", type="float", default=0.50,
                          description="Capital allocation fraction (0.0–1.0). Controls the fraction of total portfolio value deployed per trade. Default is 0.50."),
            StrategyParam(name="trend_filter_window", type="int", default=200,
                          description="SMA period for macro regime detection. Price above this SMA = Bull regime (ML trades actively), below = Bear regime (cash shelter, no new positions). The industry standard is 200 days. Shorter values (e.g., 100) switch regimes faster but risk more whipsaws.")
        ]
    )
]

@router.get("/strategies", response_model=List[StrategyInfo])
def get_strategies():
    """Returns the list of available strategies and their parameter schemas."""
    return AVAILABLE_STRATEGIES
