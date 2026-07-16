# Trading Strategies Reference

This document describes every strategy implemented in Antos, including the mathematical models, signal logic, parameters, and known strengths/weaknesses based on backtesting.

---

## 1. SMA Crossover

**File:** [sma_crossover.py](file:///Users/flipis/dev/antos/src/strategy/sma_crossover.py)
**Type:** Trend-Following
**Signals:** LONG / EXIT

### How It Works
Tracks two Simple Moving Averages: a **fast** (short) and a **slow** (long). When the fast SMA crosses above the slow SMA (**Golden Cross**), it enters long. When the fast crosses below (**Death Cross**), it exits.

### Signal Logic
```
IF fast_SMA > slow_SMA AND not currently long → LONG
IF fast_SMA < slow_SMA AND currently long     → EXIT
```

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `short_window` | 50 | Fast SMA period (days) |
| `long_window` | 200 | Slow SMA period (days) |

### Strengths & Weaknesses
- ✅ **Excellent crisis protection** — the 200-day SMA acts as a "cash shelter" that keeps you out of bear markets
- ✅ Very few trades (low commission drag)
- ✅ Best all-weather strategy by average Sharpe (0.751 across bull + crisis)
- ❌ Slow to react — the 200-day lag misses the first ~6 months of a new bull market
- ❌ Whipsaws in sideways markets

### Performance
| Period | Variant | Cum. Return | Max DD | Sharpe |
|--------|---------|-------------|--------|--------|
| 2020–2026 | 50/200 | +77.32% | -27.97% | 0.717 |
| 2020–2026 | 20/100 | +128.58% | -20.46% | 1.049 |
| 2006–2012 | 50/200 | +25.68% | -10.59% | 0.470 |
| 2006–2012 | 20/100 | +30.52% | -15.57% | 0.454 |

---

## 2. RSI Mean Reversion

**File:** [rsi_mean_reversion.py](file:///Users/flipis/dev/antos/src/strategy/rsi_mean_reversion.py)
**Type:** Counter-Trend (Mean Reversion)
**Signals:** LONG / EXIT

### How It Works
Uses the **Relative Strength Index** (RSI), originally developed by J. Welles Wilder in 1978. Buys when the RSI drops below the "oversold" threshold (indicating the asset has been beaten down and is due for a bounce) and sells when RSI rises above the "overbought" threshold.

### Signal Logic
```
RSI = 100 - (100 / (1 + avg_gain / avg_loss))

IF RSI < oversold_threshold AND not currently long  → LONG
IF RSI > overbought_threshold AND currently long     → EXIT
```

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `period` | 14 | RSI lookback period |
| `oversold` | 30.0 | Entry threshold (buy below this) |
| `overbought` | 70.0 | Exit threshold (sell above this) |
| `strength` | 0.20 | Capital allocation per trade |

### Strengths & Weaknesses
- ✅ Works well in range-bound / sideways markets
- ✅ Low drawdown in bull markets (-7.08%)
- ❌ **Worst crisis performer** — lost 9% in 2008–2012 with -28.68% drawdown
- ❌ Structurally fights trends — buys dips in a falling market

### Performance
| Period | Cum. Return | Max DD | Sharpe |
|--------|-------------|--------|--------|
| 2020–2026 | +28.24% | -7.08% | 0.725 |
| 2006–2012 | -9.00% | -28.68% | -0.095 |

> **Note:** The current implementation uses Simple Moving Averages for RSI gain/loss smoothing instead of Wilder's SMMA. This causes slight deviations from industry-standard RSI charting tools.

---

## 3. Peak Breakout Pullback

**File:** [peak_breakout_pullback.py](file:///Users/flipis/dev/antos/src/strategy/peak_breakout_pullback.py)
**Type:** Trend Breakout
**Signals:** LONG / EXIT

### How It Works
Detects when price breaks above a **Donchian Channel** (the highest high of N bars) with **volume confirmation**, waits for a pullback to confirm the breakout is genuine, then enters when price resumes upward. Uses an **ATR-based trailing stop** to ride the trend and lock in profits.

### State Machine
```
SCANNING → BREAKOUT_DETECTED (price > N-bar high + volume > SMA)
         → WAITING_FOR_PULLBACK (price retraces)
         → LONG (price resumes upward → entry)
         → EXIT (ATR trailing stop hit)
```

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `lookback_window` | 5 | Donchian Channel lookback (bars) |
| `atr_period` | 14 | ATR smoothing period |
| `vol_sma_period` | 20 | Volume SMA for breakout confirmation |
| `atr_multiplier` | 3.0 | Trailing stop distance (in ATR units) |
| `strength` | 0.20 | Capital allocation per trade |

### Performance
| Period | Cum. Return | Max DD | Sharpe |
|--------|-------------|--------|--------|
| 2020–2026 | +32.20% | -11.65% | 0.906 |
| 2006–2012 | -2.84% | -40.80% | 0.018 |

---

## 4. Volatility Squeeze Momentum

**File:** [volatility_squeeze.py](file:///Users/flipis/dev/antos/src/strategy/volatility_squeeze.py)
**Type:** Breakout (Institutional)
**Signals:** LONG / EXIT

### How It Works
Based on John Carter's **TTM Squeeze** concept. Detects when volatility compresses to abnormally low levels (Bollinger Band width falls below a historical percentile), then enters aggressively when price breaks out of the compressed range. This is the **opposite** of retail Bollinger Band strategies (which buy the lower band / sell the upper band).

### Signal Logic
```
BB_Width = (Upper_BB - Lower_BB) / Middle_BB
squeeze_detected = BB_Width < percentile(BB_Width_history, threshold)

IF squeeze_detected AND Close > Upper_BB AND ROC > 0 → LONG
IF trailing_stop_hit OR squeeze_expired               → EXIT
```

### State Machine
```
SCANNING → SQUEEZED (low volatility detected)
         → LONG (breakout above upper BB with positive momentum)
         → EXIT (ATR trailing stop or patience expired)
```

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `bb_period` | 20 | Bollinger Band SMA period |
| `bb_std` | 2.0 | Standard deviation multiplier |
| `squeeze_lookback` | 120 | History window for percentile comparison |
| `squeeze_percentile` | 20.0 | Squeeze threshold (bottom N%) |
| `roc_period` | 10 | Rate of Change for momentum direction |
| `atr_period` | 14 | ATR smoothing period for trailing stop |
| `atr_trail_mult` | 2.5 | Trailing stop distance (ATR units) |
| `patience` | 5 | Max bars to wait for breakout after squeeze |
| `strength` | 0.50 | Capital allocation per trade |

### Performance
| Period | Cum. Return | Max DD | Sharpe |
|--------|-------------|--------|--------|
| 2020–2026 | +31.75% | -10.63% | 0.827 |
| 2006–2012 | +0.99% | -21.43% | 0.061 |

---

## 5. Rolling Ridge Regression (Regime-Aware) ★

**File:** [rolling_ridge.py](file:///Users/flipis/dev/antos/src/strategy/rolling_ridge.py)
**Type:** Machine Learning + Regime Filter
**Signals:** LONG / EXIT

This is the most advanced strategy in the system. It combines a **walk-forward machine learning model** (Ridge Regression) with a **macro trend filter** (200-day SMA).

### Mathematical Model

On every bar, the strategy refits a regularized linear model using the most recent `lookback_window` bars:

```
Features (X):
  1. ROC_1    — 1-bar return (immediate momentum)
  2. ROC_3    — 3-bar return (short-term trend)
  3. Range_Ratio — today's high-low range / 14-day average range
  4. Volume_Z — volume Z-score vs 20-day average
  5. MA_Distance — distance to 20-period SMA (% deviation)

Target (Y):
  Next-bar return = (close[t+1] - close[t]) / close[t]

Solver (Ridge Regression):
  β = (X^T · X + λ · I)^(-1) · X^T · Y

Prediction:
  predicted_return = x_today · β
```

### Regime Filter

The strategy determines the macro market regime before generating any signals:

```
SMA_200 = mean(close[-200:])

IF close >= SMA_200 → BULL REGIME
   IF predicted_return > threshold → LONG
   IF predicted_return < -threshold AND holding → EXIT
   
IF close < SMA_200 → BEAR REGIME
   EXIT all positions → CASH SHELTER (no new trades)
```

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `lookback_window` | 90 | Training window size (bars) |
| `l2_lambda` | 1.0 | Regularization strength |
| `prediction_threshold` | 0.001 | Min predicted return to trigger trade |
| `strength` | 0.50 | Capital allocation per trade |
| `trend_filter_window` | 200 | SMA period for regime detection |

### Performance
| Period | Cum. Return | Max DD | Sharpe |
|--------|-------------|--------|--------|
| 2020–2026 | **+268.90%** | -25.75% | **1.142** |
| 2006–2012 | +9.98% | -16.32% | 0.176 |

### Design Evolution & Lessons Learned

The regime filter was added after testing the original Long-Only ML model against the 2008 financial crisis, which revealed a critical flaw:

| Variant | Crisis Return | Crisis Max DD |
|---------|---------------|---------------|
| Original (Long-Only) | **-39.86%** | **-56.75%** |
| Short-Selling in Bear | **-88.22%** | **-92.55%** |
| Defensive Hybrid (Final) | **+9.98%** | **-16.32%** |

**Key findings:**
1. **Long-Only ML in a crash = catching falling knives.** The model correctly predicted downward momentum but could only sit in cash or buy, repeatedly getting burned.
2. **Short-Selling was catastrophic.** The ML model's directional accuracy (~55%) is far too low for profitable shorting. Each wrong short prediction actively burns capital, and during 2008's whipsaw volatility the model was churning 327 trades on BAC alone.
3. **Cash shelter is the optimal bear response.** Simply exiting to cash when price drops below SMA 200 eliminated 71% of the drawdown while preserving upside.

---

## Combined Performance Ranking

Ranked by **Average Sharpe** across both the 2020–2026 bull market and the 2006–2012 crisis:

| Rank | Strategy | Bull Return | Crisis Return | Bull Sharpe | Crisis Sharpe | Avg Sharpe |
|------|----------|-------------|---------------|-------------|---------------|------------|
| 🥇 | SMA Crossover (20/100) | +128.58% | +30.52% | 1.049 | 0.454 | **0.751** |
| 🥈 | Ridge ML (Regime-Aware) ★ | +268.90% | +9.98% | 1.142 | 0.176 | **0.659** |
| 🥉 | SMA Crossover (50/200) | +77.32% | +25.68% | 0.717 | 0.470 | **0.594** |
| 4 | Peak Breakout Pullback | +32.20% | -2.84% | 0.906 | 0.018 | 0.462 |
| 5 | Volatility Squeeze | +31.75% | +0.99% | 0.827 | 0.061 | 0.444 |
| 6 | RSI Mean Reversion | +28.24% | -9.00% | 0.725 | -0.095 | 0.315 |

### Interpretation

- **For maximum upside:** Ridge ML dominates bull markets with +269% return and the highest Sharpe (1.142)
- **For all-weather consistency:** SMA 20/100 is the safest all-rounder, positive in both bull and crisis
- **For crisis protection:** SMA 50/200 has the lowest crisis drawdown (-10.59%)
- **Avoid in crises:** RSI Mean Reversion and Peak Breakout lose money during crashes
