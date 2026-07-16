# Performance Report: Multi-Period Strategy Backtest

**Generated:** June 2026 · **Revised:** July 2026 (see revision section below)
**Engine:** Antos Event-Driven Backtester
**Initial Capital:** $100,000 per test
**Commission:** 0.1% per transaction | **Slippage:** 0.05%

> ⚠️ **July 2026 revision note:** the tables below were produced with the
> legacy first-come-first-served capital allocator and the original
> fixed-threshold Ridge model. Both have since changed (see the revision
> section at the end and `doc/validation_baseline.md` for the full
> experiment log). Headline Ridge numbers under the shipped July 2026
> configuration: **Bull +295.3% / max DD −20.4% / 110 trades** and
> **Crisis +44.9% / max DD −11.6% / Sharpe 0.579 (vs B&H 0.545)**.

---

## Test Configuration

### Period 1: Bull Market (2020–2026)
- **Assets:** SPY (S&P 500 ETF), BTC-USD (Bitcoin)
- **Data Range:** January 2020 – April 2026 (~6 years)
- **Market Context:** COVID crash + recovery, 2021 crypto bull run, 2022 tech correction, 2023–2025 AI-driven rally

### Period 2: Financial Crisis (2006–2012)
- **Assets:** SPY, BAC (Bank of America), GLD (Gold ETF)
- **Data Range:** January 2006 – December 2012 (~7 years)
- **Market Context:** Pre-crisis bubble, 2008 crash (SPY -56%, BAC -95%), recovery

---

## Period 1 Results: 2020–2026 (Bull Market)

| Strategy | Cum. Return | Ann. Return | Max DD | Sharpe | Sortino | Calmar | Trades |
|----------|-------------|-------------|--------|--------|---------|--------|--------|
| **Ridge ML (Regime-Aware) ★** | **+268.90%** | **+22.91%** | -25.75% | **1.142** | **1.257** | **0.890** | 222 |
| SMA Crossover (20/100) | +128.58% | +13.96% | -20.46% | 1.049 | 0.994 | 0.682 | 21 |
| SMA Crossover (50/200) | +77.32% | +9.48% | -27.97% | 0.717 | 0.628 | 0.339 | 9 |
| Peak Breakout Pullback | +32.20% | +4.51% | -11.65% | 0.906 | 0.672 | 0.387 | 54 |
| Volatility Squeeze | +31.75% | +4.45% | -10.63% | 0.827 | 0.518 | 0.419 | 34 |
| RSI Mean Reversion | +28.24% | +4.01% | -7.08% | 0.725 | 0.542 | 0.566 | 18 |

### Key Observations — Bull Market
1. **Ridge ML dominates:** +269% return with the highest Sharpe (1.142) and Sortino (1.257). The walk-forward ML model captures short-term momentum shifts that the slower SMA strategies miss.
2. **SMA 20/100 is the runner-up:** +129% with fewer trades (21 vs 222). The faster 20/100 configuration reacts sooner than the classic 50/200.
3. **Defensive strategies underperform in bull markets:** RSI, Breakout, and Squeeze all cluster around +28–32% because they're designed for specific conditions (dips, breakouts, squeezes) that don't dominate a trending bull market.
4. **Trade frequency matters:** Ridge ML's 222 trades generate ~$222 in commission drag, but the alpha more than compensates.

---

## Period 2 Results: 2006–2012 (Financial Crisis)

| Strategy | Cum. Return | Ann. Return | Max DD | Sharpe | Sortino | Calmar | Trades |
|----------|-------------|-------------|--------|--------|---------|--------|--------|
| SMA Crossover (20/100) | **+30.52%** | **+3.88%** | -15.57% | 0.454 | 0.517 | 0.249 | 68 |
| SMA Crossover (50/200) | +25.68% | +3.32% | **-10.59%** | **0.470** | **0.551** | **0.314** | 23 |
| Ridge ML (Regime-Aware) ★ | +9.98% | +1.37% | -16.32% | 0.176 | 0.188 | 0.084 | 184 |
| Volatility Squeeze | +0.99% | +0.14% | -21.43% | 0.061 | 0.034 | 0.007 | 60 |
| Peak Breakout Pullback | -2.84% | -0.41% | -40.80% | 0.018 | 0.019 | -0.010 | 157 |
| RSI Mean Reversion | -9.00% | -1.34% | -28.68% | -0.095 | -0.101 | -0.047 | 30 |

### Key Observations — Crisis
1. **SMA crossovers survive crashes:** The 200-day SMA acts as a "cash shelter" that moves to cash when price drops below the long-term trend. Both variants stayed positive through 2008.
2. **Ridge ML's regime filter works:** Without the filter, the original Long-Only ML lost -40% (and the short-selling variant lost -88%). The SMA 200 regime filter turned it into a +10% return with -16% max drawdown.
3. **RSI Mean Reversion is the worst crisis performer:** Its "buy the dip" logic systematically buys falling knives during a sustained crash.
4. **Peak Breakout had the worst drawdown** (-40.8%): breakout strategies generate many false signals during high-volatility bear markets.

---

## Combined Ranking

Ranked by **Average Sharpe Ratio** across both time periods (equal weight):

| Rank | Strategy | Bull Sharpe | Crisis Sharpe | **Avg Sharpe** | Bull Return | Crisis Return | Worst DD |
|------|----------|-------------|---------------|----------------|-------------|---------------|----------|
| 🥇 | SMA Crossover (20/100) | 1.049 | 0.454 | **0.751** | +128.58% | +30.52% | -20.46% |
| 🥈 | Ridge ML (Regime-Aware) ★ | 1.142 | 0.176 | **0.659** | +268.90% | +9.98% | -25.75% |
| 🥉 | SMA Crossover (50/200) | 0.717 | 0.470 | **0.594** | +77.32% | +25.68% | -27.97% |
| 4 | Peak Breakout Pullback | 0.906 | 0.018 | 0.462 | +32.20% | -2.84% | -40.80% |
| 5 | Volatility Squeeze | 0.827 | 0.061 | 0.444 | +31.75% | +0.99% | -21.43% |
| 6 | RSI Mean Reversion | 0.725 | -0.095 | 0.315 | +28.24% | -9.00% | -28.68% |

---

## Ridge ML Evolution: The Short-Selling Experiment

During development, we tested three variants of the Ridge ML strategy against the 2008 crisis to find the optimal adaptation:

| Variant | Design | Crisis Return | Crisis Max DD | Verdict |
|---------|--------|---------------|---------------|---------|
| **v1: Long-Only** | ML predicts up → LONG, down → EXIT | -39.86% | -56.75% | ❌ Catches falling knives |
| **v2: Short-Selling** | Bear regime → SHORT on down prediction | -88.22% | -92.55% | ❌ Catastrophic — model accuracy too low for profitable shorts |
| **v3: Defensive Hybrid** | Bear regime → CASH shelter (no trades) | **+9.98%** | **-16.32%** | ✅ Final design |

### Why Short-Selling Failed
The ML model's directional accuracy (~55%) is insufficient for profitable short-selling. When you're long and wrong, you just miss an opportunity (sit in cash). When you're short and wrong, you **actively lose money**. During 2008's extreme volatility, the model churned 327 trades on BAC alone, each wrong short amplifying losses through commissions and adverse price moves.

### Why Cash Shelter Works
The SMA 200 regime filter acts as a binary switch:
- **Price > SMA 200** → "The macro trend is up" → ML trades actively
- **Price < SMA 200** → "The macro trend is down" → Exit everything, do nothing

This captured 71% of the drawdown reduction (from -57% to -16%) with zero complexity. The lesson: **in a crisis, doing nothing is better than being clever**.

---

## Strategy Selection Guide

| Scenario | Best Strategy | Why |
|----------|--------------|-----|
| Aggressive bull-market trading | Ridge ML (Regime-Aware) | Highest absolute return (+269%) and Sharpe (1.142) in trending markets |
| All-weather portfolio | SMA Crossover (20/100) | Best average Sharpe (0.751) — positive in both bull and crisis |
| Maximum crash protection | SMA Crossover (50/200) | Lowest crisis drawdown (-10.59%) |
| Sideways / range-bound markets | RSI Mean Reversion | Designed for oscillating markets, lowest bull drawdown (-7.08%) |
| Breakout-driven markets | Volatility Squeeze | Captures explosive moves after low-volatility compression |

---

## July 2026 Revision: The Improvement Program

A validation-first improvement pass was run against the Ridge ML
strategy (the live bot's strategy). Every change was tuned only on a
2020–2023 train window and judged out-of-sample on 2024–2026 and
2006–2012 against a buy-and-hold benchmark (`validate_strategy.py`).
Full experiment log with tables: `doc/validation_baseline.md`.

### Shipped

| Change | Effect |
|--------|--------|
| **Volatility-scaled entry threshold** (`vol_threshold_k=0.15`) | Entries require conviction proportional to trailing 20-bar vol. Bull: +295% vs +269% with **half the trades** (110 vs 222). Crisis 2008: −2.5% vs −9.1%. The single biggest win. |
| **Fair-share allocation cap** (NAV/n per symbol) | Removes first-come-first-served sizing that alphabetically favored early symbols and starved the rest (the live 6-symbol bot ran at $230 free cash). Crisis DD improves to −11.6%; exposed that the prior crisis outperformance was partly "GLD sorts first" luck. |
| **Live guardrails** | Drawdown circuit breaker (default 15%, halts new entries, exits allowed) + per-symbol rolling hit-rate kill switch (<45% over 20 calls). |
| **Once-per-bar signal evaluation** | Fixed duplicate-order churn from multiple daily scheduler ticks re-evaluating the same candle. |
| **Warmup fast path** | Live tick pre-warm: 15.7s → 3ms (one model fit per tick instead of ~9,500). |

### Falsified (tried, measured, rejected)

| Experiment | Why it failed |
|-----------|---------------|
| Feature standardization + unpenalized intercept (textbook ridge fix) | Crisis flipped +28% → −22%. Hit rates are ~50% everywhere; the model's real edge is over-shrinkage acting as a high-conviction trend filter, which the intercept destroyed. |
| Regime hysteresis (SMA dead band) | OOS the crisis got worse (delayed bear exits cost more than saved whipsaw); vol-scaled threshold already suppresses crossing churn. |

### Honest bottom line

The Ridge strategy is a **risk-reduction** strategy, not a
return-maximization one: it lags buy-and-hold in raw return in both
periods but wins on drawdown everywhere and on Sharpe in both periods
under the shipped configuration. Its directional accuracy is ~50%; its
value comes from trading rarely, with conviction, inside a trend
regime — and from stepping aside in bear markets.

---

## Reproducing These Results

### Bull Market Test (2020–2026)
```bash
cd /path/to/antos
python3 compare_strategies.py
```

### Crisis Test (2006–2012)
```bash
# First download crisis-era data
python3 download_data.py  # (modify dates to 2006-2012)

# Run the crisis comparison
python3 scratch/run_crisis_backtest.py
```

### Interactive Dashboard
```bash
uvicorn api.server:app --port 8000 --reload
# Open http://localhost:8000 → select strategy → run backtest
```
