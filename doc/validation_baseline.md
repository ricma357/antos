# Validation Baseline — Rolling Ridge (pre-improvement)

Snapshot taken 2026-07-16, commit `3766ee2`, before any model changes.
All future changes are judged against these numbers via `validate_strategy.py`.

Params: lookback=90, λ=1.0, threshold=0.001, strength=0.50, trend_filter=200.
Costs: 0.1% commission, 0.05% slippage. Sharpe uses 252-day annualization
(differs from doc/performance_report.md, which uses a dynamic factor).

## Bull 2020–2026 (SPY, BTC-USD)

| Period | Strategy Ret% | B&H Ret% | Strat DD% | Bench DD% | Strat Sharpe | Bench Sharpe |
|--------|--------------|----------|-----------|-----------|--------------|--------------|
| FULL | +268.90 | +484.87 | −25.75 | −66.60 | 0.948 | 0.699 |
| 2020 | +65.05 | +139.69 | −9.59 | −38.52 | 2.451 | 1.833 |
| 2021 | +23.72 | +48.84 | −19.68 | −43.97 | 0.689 | 0.784 |
| 2022 | −6.76 | −54.38 | −7.04 | −55.90 | −1.978 | −1.163 |
| 2023 | +27.49 | +100.73 | −11.74 | −14.16 | 1.166 | 2.007 |
| 2024 | +48.97 | +89.99 | −13.83 | −21.48 | 1.367 | 1.401 |
| 2025 | −0.14 | −3.66 | −9.58 | −27.99 | 0.030 | 0.066 |
| 2026 | −1.37 | −10.44 | −2.57 | −29.49 | −0.732 | −0.447 |

Trades: 222 (111 round trips, 48.6% win rate).

## Crisis 2006–2012 (SPY, GLD, JPM)

| Period | Strategy Ret% | B&H Ret% | Strat DD% | Bench DD% | Strat Sharpe | Bench Sharpe |
|--------|--------------|----------|-----------|-----------|--------------|--------------|
| FULL | +28.06 | +88.19 | −16.89 | −35.52 | 0.331 | 0.545 |
| 2008 | −9.10 | −16.87 | −16.24 | −35.52 | −0.868 | −0.385 |
| 2009 | +28.99 | +26.41 | −11.78 | −16.97 | 1.256 | 1.017 |

Trades: 200 (99 round trips, 48.5% win rate).
(Full yearly table reproducible via `python3 validate_strategy.py --crisis`.)

## Shipped improvements

### Volatility-scaled entry threshold (2026-07-17) — `vol_threshold_k=0.15`

A trade now requires `|predicted return| > k × trailing 20-bar realized
volatility` instead of a fixed 0.1%. Tuned on the 2020–2023 train window
only (stable plateau k=0.10–0.20; plateau center chosen), then validated
out-of-sample. Results vs this baseline:

| Metric | Baseline (fixed) | Vol-scaled k=0.15 | Verdict |
|--------|------------------|-------------------|---------|
| Bull FULL return | +268.90% | +295.29% | ✓ |
| Bull FULL max DD | −25.75% | −20.40% | ✓ |
| Bull trades | 222 | 110 | ✓ (half the fee drag) |
| Holdout 2025 return | −0.14% | +2.01% | ✓ |
| Holdout 2026 return | −1.37% | −0.77% | ✓ |
| Crisis FULL return | +28.06% | **+77.49%** | ✓✓ |
| Crisis FULL Sharpe | 0.331 | 0.695 (beats B&H 0.545) | ✓✓ |
| Crisis 2008 return | −9.10% | −2.54% | ✓✓ |
| Crisis trades | 200 | 126 | ✓ |

(Holdout 2024: +39.88% vs +48.97% — the one give-back, accepted for the
across-the-board risk and crisis gains.)

**Why it works:** consistent with the falsified-experiment lesson below —
the model's edge is high-conviction trend filtering, not prediction.
A fixed threshold lets noise through exactly when noise is largest;
scaling by realized vol demands proportionally stronger conviction in
volatile regimes, cutting the 2008/2010/2011 churn that bled the
baseline. Shipped as the constructor default; the live bot picks it up
via registry defaults. Set `vol_threshold_k=0` to recover the old
fixed-threshold behavior.

## Falsified experiments

### Feature standardization + unpenalized intercept (2026-07-16)

The textbook ridge fix — z-scored features and an intercept fit via
target centering — was implemented, tuned honestly (λ and threshold
re-tuned on 2020–2023 only; best plateau λ=10, thr=0.002), and evaluated
on held-out data. Results vs this baseline:

| Metric | Baseline | Standardized+intercept | Verdict |
|--------|----------|------------------------|---------|
| Bull FULL return | +268.90% | +151.79% | ✗ |
| Bull FULL Sharpe | 0.948 | 0.753 | ✗ |
| Holdout 2024 return | +48.97% | +15.27% | ✗ |
| Crisis FULL return | +28.06% | **−22.04%** | ✗✗ |
| Crisis max DD | −16.89% | −31.89% | ✗✗ |
| Crisis trades | 200 | 292 | ✗ |

**Why it failed:** directional hit rates are ~49–52% everywhere — the
features carry no real predictive edge. The baseline model's advantage
is its *accidental over-shrinkage*: an unscaled L2 penalty on raw
return-scale features crushes predictions toward zero, so it only
trades when trailing drift is strong, functioning as a high-conviction
trend filter with low turnover. The unpenalized intercept injected
trailing drift (≈±0.1%/day) into every prediction, constantly crossing
the entry threshold, whipsawing in choppy regimes (2008, 2010–2011) and
roughly doubling fee drag.

**Kept from the experiment:** per-symbol directional hit-rate
diagnostics (`get_hit_rate`), which exposed the coin-flip accuracy and
now feed the live kill-switch guardrail.

**Lesson for future work:** improvements should target *when to trust
the trend* (volatility-scaled conviction thresholds, regime hysteresis,
turnover control) rather than better point predictions from these
features.

## Honest read

- The strategy's edge is **risk reduction**, not raw return: it lags
  buy-and-hold badly in absolute terms in both periods but wins on
  drawdown everywhere, and on Sharpe in the bull period.
- 2022 is the strategy's showcase year: −6.8% vs −54.4% for B&H.
- Crisis-period Sharpe (0.331) loses to a passive SPY/GLD/JPM mix (0.545)
  — GLD's diversification alone beats the regime filter here.
- Win rate ~48.5% in both regimes: the model wins by cutting losers
  early, not by predicting well. Directional accuracy improvements
  (tasks #12, #16) are where the headroom is.
