import { api, showToast } from './api.js';
import { renderCharts, renderBotCharts, handleResize } from './charts.js';
import { 
    renderMetrics, 
    renderDateRange, 
    renderTradeLog, 
    buildStrategyForm,
    renderBotMetrics,
    renderBotInsights,
    renderBotPositions,
    renderBotLedger,
    buildBotStrategyForm
} from './components.js?v=2';

let availableStrategies = [];
let botPollTimer = null;

// --- Routing ---
function handleRoute() {
    const hash = window.location.hash || '#backtest';
    const viewId = `view-${hash.substring(1)}`;
    
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    
    const targetView = document.getElementById(viewId);
    const targetNav = document.querySelector(`.nav-item[href="${hash}"]`);
    
    if (targetView) targetView.classList.add('active');
    if (targetNav) targetNav.classList.add('active');
    
    // Trigger chart resize if navigating to results or bot views
    if (hash === '#results' || hash === '#bot') {
        setTimeout(handleResize, 100);
    }

    if (hash === '#bot') {
        updateBotUI();
    }
}

// --- Initialization ---
async function init() {
    window.addEventListener('hashchange', handleRoute);
    handleRoute(); // Set initial route
    
    // Wire up backtest form submission
    document.getElementById('backtest-form').addEventListener('submit', onRunBacktest);
    document.getElementById('strategy-select').addEventListener('change', onStrategyChange);
    
    // Save config on changes
    document.getElementById('backtest-form').addEventListener('input', saveBacktestConfig);
    document.getElementById('backtest-form').addEventListener('change', saveBacktestConfig);
    
    // Wire up clear results button
    const clearBtn = document.getElementById('btn-clear-results');
    if (clearBtn) {
        clearBtn.addEventListener('click', onClearResults);
    }
    
    // Wire up bot controls
    document.getElementById('bot-strategy-select').addEventListener('change', onBotStrategyChange);
    document.getElementById('bot-broker-select').addEventListener('change', onBotBrokerChange);
    document.getElementById('bot-config-form').addEventListener('submit', onStartBot);
    document.getElementById('btn-stop-bot').addEventListener('click', onStopBot);
    document.getElementById('btn-reset-bot').addEventListener('click', onResetBot);
    document.getElementById('btn-tick-bot').addEventListener('click', onTriggerBotTick);
    
    // Scheduler controls
    document.getElementById('btn-start-scheduler').addEventListener('click', onStartScheduler);
    document.getElementById('btn-stop-scheduler').addEventListener('click', onStopScheduler);
    
    try {
        // Load symbols
        const symbols = await api.getSymbols();
        document.getElementById('available-symbols-hint').textContent = `Available: ${symbols.join(', ')}`;
        
        // Load strategies
        availableStrategies = await api.getStrategies();
        
        // Populate Backtest strategies
        const select = document.getElementById('strategy-select');
        select.innerHTML = '<option value="" disabled selected>Select an algorithm...</option>';
        
        // Populate Bot strategies
        const botSelect = document.getElementById('bot-strategy-select');
        botSelect.innerHTML = '<option value="" disabled selected>Select strategy...</option>';

        availableStrategies.forEach(strat => {
            select.innerHTML += `<option value="${strat.id}">${strat.name}</option>`;
            botSelect.innerHTML += `<option value="${strat.id}">${strat.name}</option>`;
        });
        
        // Restore config and results from localStorage
        restoreBacktestConfig();
        restoreBacktestResult();
        
        // Initial bot check and auto-polling
        updateBotUI();
        botPollTimer = setInterval(updateBotUI, 3000); // Poll status every 3s
        
    } catch (e) {
        console.error("Initialization failed", e);
    }
}

// --- Event Handlers ---
function onStrategyChange(e) {
    const stratId = e.target.value;
    const strat = availableStrategies.find(s => s.id === stratId);
    
    // Remove any previous strategy description
    const oldDesc = document.querySelector('#view-backtest .strategy-description');
    if (oldDesc) oldDesc.remove();
    
    if (strat) {
        buildStrategyForm(strat);
    }
    
    saveBacktestConfig();
}

function onBotStrategyChange(e) {
    const stratId = e.target.value;
    const strat = availableStrategies.find(s => s.id === stratId);
    
    // Remove any previous strategy description
    const oldDesc = document.querySelector('#view-bot .strategy-description');
    if (oldDesc) oldDesc.remove();
    
    if (strat) {
        buildBotStrategyForm(strat);
    }
}

function onBotBrokerChange(e) {
    const broker = e.target.value;
    const credsFields = document.querySelectorAll('.alpaca-creds');
    credsFields.forEach(el => {
        if (broker === 'alpaca') {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    });
}

async function onRunBacktest(e) {
    e.preventDefault();
    
    const btn = document.getElementById('btn-run-backtest');
    const btnText = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.loader');
    
    const strategyId = document.getElementById('strategy-select').value;
    if (!strategyId) {
        showToast('Please select a strategy first', 'error');
        return;
    }
    
    const params = {};
    document.querySelectorAll('[id^="param-"]').forEach(input => {
        const name = input.id.replace('param-', '');
        params[name] = input.dataset.type === 'float' ? parseFloat(input.value) : parseInt(input.value, 10);
    });
    
    const payload = {
        strategy_id: strategyId,
        symbols: document.getElementById('env-symbols').value.split(',').map(s => s.trim()),
        initial_cash: parseFloat(document.getElementById('env-cash').value),
        commission_rate: parseFloat(document.getElementById('env-commission').value),
        slippage_rate: parseFloat(document.getElementById('env-slippage').value),
        params: params
    };
    
    try {
        btn.disabled = true;
        btnText.textContent = 'Running...';
        loader.classList.remove('hidden');
        
        const result = await api.runBacktest(payload);
        
        localStorage.setItem('last_backtest_result', JSON.stringify(result));
        
        document.getElementById('results-strategy-title').textContent = result.strategy_name;
        
        renderMetrics(result.metrics, result.date_start, result.date_end);
        renderDateRange(result.date_start, result.date_end);
        renderTradeLog(result.trade_log);
        
        showToast(`Backtest completed! ${result.trade_log.length} trades over ${result.date_start} → ${result.date_end}`);
        
        window.location.hash = '#results';
        handleRoute();
        
        renderCharts(result.equity_curve, result.drawdown_curve);
        
    } catch (error) {
        console.error(error);
    } finally {
        btn.disabled = false;
        btnText.textContent = 'Execute Backtest';
        loader.classList.add('hidden');
    }
}

// --- Live Bot Handlers ---

async function updateBotUI() {
    try {
        const state = await api.getBotStatus();
        
        const dot = document.querySelector('.status-dot');
        const text = document.getElementById('bot-status-text');
        
        const startBtn = document.getElementById('btn-start-bot');
        const stopBtn = document.getElementById('btn-stop-bot');
        const tickBtn = document.getElementById('btn-tick-bot');
        const resetBtn = document.getElementById('btn-reset-bot');
        const configInputs = document.getElementById('bot-config-inputs');
        const configParams = document.getElementById('bot-strategy-params');
        
        const liveCheckbox = document.getElementById('bot-live-mode');
        
        const brokerSelect = document.getElementById('bot-broker-select');
        const schedulerCard = document.getElementById('bot-scheduler-card');
        
        if (state.active) {
            dot.className = 'status-dot active';
            const modeLabel = state.live_mode ? 'LIVE DATA' : 'HISTORICAL DATA';
            text.textContent = `ACTIVE (${modeLabel}) | DATE: ${state.current_date || 'INITIALIZING'}`;
            
            startBtn.classList.add('hidden');
            stopBtn.classList.remove('hidden');
            tickBtn.classList.remove('hidden');
            configInputs.style.opacity = '0.5';
            configInputs.style.pointerEvents = 'none';
            configParams.style.opacity = '0.5';
            configParams.style.pointerEvents = 'none';
            if (liveCheckbox) {
                liveCheckbox.disabled = true;
                liveCheckbox.checked = state.live_mode;
            }
            if (brokerSelect) {
                brokerSelect.disabled = true;
                brokerSelect.value = state.broker_type || 'simulated';
            }
            
            // Show and render scheduler details
            if (schedulerCard) {
                schedulerCard.classList.remove('hidden');
                
                const schedDot = document.getElementById('scheduler-status-dot');
                const schedText = document.getElementById('scheduler-status-text');
                const startSchedBtn = document.getElementById('btn-start-scheduler');
                const stopSchedBtn = document.getElementById('btn-stop-scheduler');
                const schedIntervalInput = document.getElementById('scheduler-interval-input');
                
                if (state.scheduler_active) {
                    schedDot.className = 'status-dot active';
                    schedText.textContent = `SCHEDULER: RUNNING (Every ${state.scheduler_interval}s)`;
                    startSchedBtn.classList.add('hidden');
                    stopSchedBtn.classList.remove('hidden');
                    if (schedIntervalInput) {
                        schedIntervalInput.disabled = true;
                        schedIntervalInput.value = state.scheduler_interval;
                    }
                } else {
                    schedDot.className = 'status-dot inactive';
                    schedText.textContent = 'SCHEDULER: INACTIVE';
                    startSchedBtn.classList.remove('hidden');
                    stopSchedBtn.classList.add('hidden');
                    if (schedIntervalInput) schedIntervalInput.disabled = false;
                }
            }
        } else {
            dot.className = 'status-dot inactive';
            text.textContent = 'INACTIVE';
            
            startBtn.classList.remove('hidden');
            stopBtn.classList.add('hidden');
            tickBtn.classList.add('hidden');
            configInputs.style.opacity = '1';
            configInputs.style.pointerEvents = 'auto';
            configParams.style.opacity = '1';
            configParams.style.pointerEvents = 'auto';
            if (liveCheckbox) {
                liveCheckbox.disabled = false;
            }
            if (brokerSelect) {
                brokerSelect.disabled = false;
            }
            if (schedulerCard) {
                schedulerCard.classList.add('hidden');
            }
        }
        
        // Use the backend's equity curve last value as the single source of truth for NAV.
        // This ensures the metric card and the chart always show the same number.
        let currentNav = state.cash + Object.keys(state.positions).reduce((acc, sym) => acc + (state.positions[sym].qty * (state.last_prices ? state.last_prices[sym] : state.positions[sym].avg_cost)), 0);
        if (state.equity_curve && state.equity_curve.length > 0) {
            currentNav = state.equity_curve[state.equity_curve.length - 1].value;
        }

        renderBotInsights(state.insights);
        
        // Estimate close prices based on last_prices from backend (preferred) or trade fills
        const approxClosePrices = state.last_prices ? { ...state.last_prices } : {};
        if (Object.keys(approxClosePrices).length === 0) {
            state.trade_log.forEach(t => { approxClosePrices[t.symbol] = t.fill_price; });
        }
        
        renderBotPositions(state.positions, approxClosePrices);
        
        // Load SQL Trade Journal and merge metrics — only render metrics ONCE
        try {
            const journalData = await api.getBotJournal(100);
            renderBotLedger(journalData.trades);
            
            if (journalData.metrics && journalData.metrics.total_trades > 0) {
                state.metrics.win_rate_pct = journalData.metrics.win_rate_pct;
                state.metrics.profit_factor = journalData.metrics.profit_factor;
                state.metrics.num_trades = journalData.metrics.total_trades;
            }
        } catch (journalErr) {
            console.error("SQLite journal loading failed. Falling back to local state ledger.", journalErr);
            renderBotLedger(state.trade_log);
        }

        // Recalculate total return from the authoritative NAV
        if (state.initial_cash && state.initial_cash > 0) {
            state.metrics.total_return_pct = ((currentNav - state.initial_cash) / state.initial_cash) * 100;
        }

        // Single render of metrics — no more twitching
        renderBotMetrics(state.metrics, state.cash, currentNav);
        
        // Render TV charts
        if (state.equity_curve && state.equity_curve.length > 0) {
            const chartDataEquity = state.equity_curve.map(pt => ({ time: pt.time, value: pt.value }));
            const chartDataDD = state.equity_curve.map(pt => ({ time: pt.time, value: pt.drawdown * 100 }));
            renderBotCharts(chartDataEquity, chartDataDD);
        }
        
    } catch (e) {
        console.error("Failed to fetch bot status", e);
    }
}

async function onStartBot(e) {
    e.preventDefault();
    
    const strategyId = document.getElementById('bot-strategy-select').value;
    if (!strategyId) {
        showToast('Please select a strategy first', 'error');
        return;
    }
    
    const params = {};
    document.querySelectorAll('[id^="bot-param-"]').forEach(input => {
        const name = input.id.replace('bot-param-', '');
        params[name] = input.dataset.type === 'float' ? parseFloat(input.value) : parseInt(input.value, 10);
    });
    
    const payload = {
        strategy_id: strategyId,
        symbols: document.getElementById('bot-symbols').value.split(',').map(s => s.trim()),
        initial_cash: parseFloat(document.getElementById('bot-cash').value),
        commission_rate: 0.001,
        slippage_rate: 0.0005,
        params: params,
        live_mode: document.getElementById('bot-live-mode').checked,
        broker_type: document.getElementById('bot-broker-select').value,
        alpaca_api_key: document.getElementById('bot-alpaca-key').value || null,
        alpaca_api_secret: document.getElementById('bot-alpaca-secret').value || null,
        alpaca_base_url: null
    };
    
    try {
        await api.startBot(payload);
        showToast('Trading bot started successfully!');
        updateBotUI();
    } catch (e) {
        console.error(e);
    }
}

async function onStopBot() {
    try {
        await api.stopBot();
        showToast('Trading bot stopped.');
        updateBotUI();
    } catch (e) {
        console.error(e);
    }
}

async function onResetBot() {
    if (!confirm('Are you sure you want to delete all trading logs and reset bot state?')) return;
    try {
        await api.resetBot();
        showToast('Trading bot state cleared.');
        updateBotUI();
    } catch (e) {
        console.error(e);
    }
}

async function onTriggerBotTick() {
    try {
        const state = await api.triggerBotTick();
        showToast(`Market tick simulated. Date: ${state.current_date}`);
        updateBotUI();
    } catch (e) {
        console.error(e);
    }
}

async function onStartScheduler() {
    const intervalInput = document.getElementById('scheduler-interval-input');
    const interval = parseInt(intervalInput.value, 10);
    if (!interval || interval <= 0) {
        showToast('Please enter a valid positive interval in seconds.', 'error');
        return;
    }
    try {
        await api.startScheduler(interval);
        showToast(`Automated scheduler activated at ${interval}s interval.`);
        updateBotUI();
    } catch (e) {
        console.error(e);
    }
}

async function onStopScheduler() {
    try {
        await api.stopScheduler();
        showToast('Automated scheduler deactivated.');
        updateBotUI();
    } catch (e) {
        console.error(e);
    }
}

// --- LocalStorage Configuration & Results Persistence ---

function saveBacktestConfig() {
    const symbolsEl = document.getElementById('env-symbols');
    const cashEl = document.getElementById('env-cash');
    const commissionEl = document.getElementById('env-commission');
    const slippageEl = document.getElementById('env-slippage');
    const selectEl = document.getElementById('strategy-select');
    
    if (!symbolsEl || !cashEl || !commissionEl || !slippageEl || !selectEl) return;
    
    const config = {
        symbols: symbolsEl.value,
        cash: cashEl.value,
        commission: commissionEl.value,
        slippage: slippageEl.value,
        strategyId: selectEl.value,
        params: {}
    };
    
    document.querySelectorAll('[id^="param-"]').forEach(input => {
        const name = input.id.replace('param-', '');
        config.params[name] = input.value;
    });
    
    localStorage.setItem('backtest_config', JSON.stringify(config));
}

function restoreBacktestConfig() {
    try {
        const data = localStorage.getItem('backtest_config');
        if (!data) return;
        
        const config = JSON.parse(data);
        
        const symbolsEl = document.getElementById('env-symbols');
        const cashEl = document.getElementById('env-cash');
        const commissionEl = document.getElementById('env-commission');
        const slippageEl = document.getElementById('env-slippage');
        const selectEl = document.getElementById('strategy-select');
        
        if (config.symbols !== undefined && symbolsEl) symbolsEl.value = config.symbols;
        if (config.cash !== undefined && cashEl) cashEl.value = config.cash;
        if (config.commission !== undefined && commissionEl) commissionEl.value = config.commission;
        if (config.slippage !== undefined && slippageEl) slippageEl.value = config.slippage;
        
        if (config.strategyId && selectEl) {
            selectEl.value = config.strategyId;
            
            // Rebuild strategy parameters form
            const strat = availableStrategies.find(s => s.id === config.strategyId);
            if (strat) {
                // Remove old strategy description if any
                const oldDesc = document.querySelector('#view-backtest .strategy-description');
                if (oldDesc) oldDesc.remove();
                
                buildStrategyForm(strat);
                
                // Prefill strategy-specific parameter values
                if (config.params) {
                    Object.entries(config.params).forEach(([name, value]) => {
                        const input = document.getElementById(`param-${name}`);
                        if (input) {
                            input.value = value;
                        }
                    });
                }
            }
        }
    } catch (e) {
        console.error("Failed to restore backtest config", e);
    }
}

function restoreBacktestResult() {
    try {
        const data = localStorage.getItem('last_backtest_result');
        if (!data) return;
        
        const result = JSON.parse(data);
        
        const titleEl = document.getElementById('results-strategy-title');
        if (titleEl) titleEl.textContent = result.strategy_name;
        
        renderMetrics(result.metrics, result.date_start, result.date_end);
        renderDateRange(result.date_start, result.date_end);
        renderTradeLog(result.trade_log);
        renderCharts(result.equity_curve, result.drawdown_curve);
    } catch (e) {
        console.error("Failed to restore backtest result", e);
    }
}

function onClearResults() {
    localStorage.removeItem('last_backtest_result');
    
    const titleEl = document.getElementById('results-strategy-title');
    if (titleEl) titleEl.textContent = 'Performance Results';
    
    const dateRange = document.getElementById('results-date-range');
    if (dateRange) dateRange.textContent = '';
    
    const container = document.getElementById('metrics-container');
    if (container) container.innerHTML = '';
    
    const tbody = document.getElementById('trade-table-body');
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#94a3b8;">No results to display. Run a backtest first.</td></tr>';
    }
    
    renderCharts([], []);
    
    showToast('Backtest results cleared.');
    
    window.location.hash = '#backtest';
    handleRoute();
}

// Bootstrap
document.addEventListener('DOMContentLoaded', init);
