// Utility formatting
const fmtUSD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const fmtPct = new Intl.NumberFormat('en-US', { style: 'percent', minimumFractionDigits: 2 });

export function renderMetrics(metrics, dateStart, dateEnd) {
    const container = document.getElementById('metrics-container');
    
    const retClass = metrics.total_return_pct >= 0 ? 'profit' : 'loss';
    const sharpeClass = metrics.sharpe >= 1.0 ? 'profit' : (metrics.sharpe >= 0.5 ? '' : 'loss');
    
    // Human-readable Sharpe interpretation
    let sharpeLabel = 'Poor';
    if (metrics.sharpe >= 2.0) sharpeLabel = 'Excellent';
    else if (metrics.sharpe >= 1.0) sharpeLabel = 'Good';
    else if (metrics.sharpe >= 0.5) sharpeLabel = 'Acceptable';
    
    // Human-readable Drawdown interpretation
    let ddLabel = 'Minimal risk';
    const ddAbs = Math.abs(metrics.max_drawdown_pct);
    if (ddAbs >= 30) ddLabel = 'Severe — high risk';
    else if (ddAbs >= 15) ddLabel = 'Significant';
    else if (ddAbs >= 5) ddLabel = 'Moderate';
    
    container.innerHTML = `
        <div class="card metric-card">
            <div class="metric-label">Total Return</div>
            <div class="metric-value ${retClass}">${fmtPct.format(metrics.total_return_pct / 100)}</div>
            <div class="metric-sub">Cumulative gain/loss over period</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Annualized Return</div>
            <div class="metric-value ${metrics.ann_return_pct >= 0 ? 'profit' : 'loss'}">${fmtPct.format(metrics.ann_return_pct / 100)}</div>
            <div class="metric-sub">Yearly compound growth rate</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Sharpe Ratio</div>
            <div class="metric-value ${sharpeClass}">${metrics.sharpe.toFixed(2)}</div>
            <div class="metric-sub">${sharpeLabel} — risk-adjusted return</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Sortino Ratio</div>
            <div class="metric-value">${metrics.sortino.toFixed(2)}</div>
            <div class="metric-sub">Penalizes downside volatility only</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Max Drawdown</div>
            <div class="metric-value loss">${fmtPct.format(metrics.max_drawdown_pct / 100)}</div>
            <div class="metric-sub">${ddLabel} — worst peak-to-trough drop</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Executed Trades</div>
            <div class="metric-value">${metrics.num_trades}</div>
            <div class="metric-sub">Total buy + sell executions</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Initial Capital</div>
            <div class="metric-value">${fmtUSD.format(metrics.initial_balance)}</div>
            <div class="metric-sub">Starting portfolio value</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Final NAV</div>
            <div class="metric-value">${fmtUSD.format(metrics.final_balance)}</div>
            <div class="metric-sub">Net Asset Value at end of period</div>
        </div>
    `;
}

export function renderDateRange(dateStart, dateEnd) {
    const el = document.getElementById('results-date-range');
    if (el && dateStart && dateEnd) {
        el.textContent = `Simulation period: ${dateStart}  →  ${dateEnd}`;
    }
}

export function renderTradeLog(trades) {
    const tbody = document.getElementById('trade-table-body');
    
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#94a3b8;">No trades executed — the strategy did not generate any signals for the selected assets and parameters.</td></tr>';
        return;
    }
    
    tbody.innerHTML = trades.map(t => {
        const sideClass = t.direction === 'BUY' ? 'badge-buy' : 'badge-sell';
        return `
            <tr>
                <td>${t.timestamp}</td>
                <td><strong>${t.symbol}</strong></td>
                <td><span class="badge ${sideClass}">${t.direction}</span></td>
                <td class="text-right">${t.quantity}</td>
                <td class="text-right">${fmtUSD.format(t.fill_price)}</td>
                <td class="text-right">${fmtUSD.format(t.commission)}</td>
                <td class="text-right">${fmtUSD.format(t.nav_after)}</td>
            </tr>
        `;
    }).reverse().join(''); // Reverse to show newest first
}

export function buildStrategyForm(strategySchema) {
    const container = document.getElementById('strategy-params-container');
    container.innerHTML = '';
    
    // Remove any previous strategy description
    const oldDesc = container.parentElement.querySelector('.strategy-description');
    if (oldDesc) oldDesc.remove();

    // Show strategy description
    const descDiv = document.createElement('div');
    descDiv.className = 'strategy-description';
    descDiv.innerHTML = `<p>${strategySchema.description}</p>`;
    container.parentElement.insertBefore(descDiv, container);
    
    strategySchema.parameters.forEach(param => {
        const step = param.type === 'float' ? '0.01' : '1';
        
        container.innerHTML += `
            <div class="form-group">
                <label for="param-${param.name}">${param.name}</label>
                <input type="number" 
                       id="param-${param.name}" 
                       data-type="${param.type}"
                       value="${param.default}" 
                       step="${step}" 
                       required>
                <small class="hint">${param.description}</small>
            </div>
        `;
    });
}

export function renderBotMetrics(metrics, currentCash, currentNav) {
    const container = document.getElementById('bot-metrics-container');
    
    const retClass = metrics.total_return_pct >= 0 ? 'profit' : 'loss';
    const sharpeClass = metrics.sharpe >= 1.0 ? 'profit' : (metrics.sharpe >= 0.5 ? '' : 'loss');
    
    // Human-readable Sharpe interpretation
    let sharpeLabel = 'Poor';
    if (metrics.sharpe >= 2.0) sharpeLabel = 'Excellent';
    else if (metrics.sharpe >= 1.0) sharpeLabel = 'Good';
    else if (metrics.sharpe >= 0.5) sharpeLabel = 'Acceptable';

    container.innerHTML = `
        <div class="card metric-card">
            <div class="metric-label">Net Asset Value</div>
            <div class="metric-value">${fmtUSD.format(currentNav)}</div>
            <div class="metric-sub">Total portfolio net worth</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Cash Balance</div>
            <div class="metric-value">${fmtUSD.format(currentCash)}</div>
            <div class="metric-sub">Available purchasing power</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Total Return</div>
            <div class="metric-value ${retClass}">${fmtPct.format(metrics.total_return_pct / 100)}</div>
            <div class="metric-sub">Compound yield since start</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Win Rate</div>
            <div class="metric-value">${metrics.win_rate_pct.toFixed(1)}%</div>
            <div class="metric-sub">Percent of profitable closed trades</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Profit Factor</div>
            <div class="metric-value">${metrics.profit_factor.toFixed(2)}</div>
            <div class="metric-sub">Gross profit / Gross loss ratio</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Sharpe Ratio</div>
            <div class="metric-value ${sharpeClass}">${metrics.sharpe.toFixed(2)}</div>
            <div class="metric-sub">${sharpeLabel} — risk-adjusted return</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Max Drawdown</div>
            <div class="metric-value loss">${fmtPct.format(metrics.max_drawdown_pct / 100)}</div>
            <div class="metric-sub">Worst peak-to-trough drop</div>
        </div>
        <div class="card metric-card">
            <div class="metric-label">Executed Trades</div>
            <div class="metric-value">${metrics.num_trades}</div>
            <div class="metric-sub">Total transaction ledger count</div>
        </div>
    `;
}

export function renderBotInsights(insights) {
    const list = document.getElementById('bot-insights-list');
    list.innerHTML = insights.map(ins => `<li>${ins}</li>`).join('');
}

export function renderBotPositions(positions, closePrices) {
    const tbody = document.getElementById('bot-positions-body');
    const activeSymbols = Object.keys(positions).filter(sym => positions[sym].qty > 0);
    
    if (activeSymbols.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:16px;color:#94a3b8;">No active positions. Portfolio is 100% in Cash.</td></tr>';
        return;
    }
    
    tbody.innerHTML = activeSymbols.map(sym => {
        const pos = positions[sym];
        const close = closePrices[sym] || pos.avg_cost;
        const pnlPct = ((close - pos.avg_cost) / pos.avg_cost) * 100;
        const pnlUSD = (close - pos.avg_cost) * pos.qty;
        
        const pnlClass = pnlUSD >= 0 ? 'profit' : 'loss';
        const sign = pnlUSD >= 0 ? '+' : '';
        
        return `
            <tr>
                <td><strong>${sym}</strong></td>
                <td class="text-right">${pos.qty}</td>
                <td class="text-right">${fmtUSD.format(pos.avg_cost)}</td>
                <td class="text-right ${pnlClass}">${sign}${fmtUSD.format(pnlUSD)} (${sign}${pnlPct.toFixed(2)}%)</td>
            </tr>
        `;
    }).join('');
}

export function renderBotLedger(tradeLog) {
    const tbody = document.getElementById('bot-ledger-body');
    
    if (!tradeLog || tradeLog.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:16px;color:#94a3b8;">No trades executed yet.</td></tr>';
        return;
    }
    
    tbody.innerHTML = tradeLog.map(t => {
        const sideClass = t.direction === 'BUY' ? 'badge-buy' : 'badge-sell';
        const pnl = t.realized_pnl || 0.0;
        
        let pnlCell = '<span style="color:#94a3b8;">—</span>';
        if (t.direction === 'SELL') {
            const pnlClass = pnl >= 0 ? 'profit' : 'loss';
            const sign = pnl >= 0 ? '+' : '';
            pnlCell = `<span class="${pnlClass}">${sign}${fmtUSD.format(pnl)}</span>`;
        }
        
        return `
            <tr>
                <td><small>${t.timestamp}</small></td>
                <td><strong>${t.symbol}</strong></td>
                <td><span class="badge ${sideClass}">${t.direction}</span></td>
                <td class="text-right">${fmtUSD.format(t.price || t.fill_price)}</td>
                <td class="text-right">${pnlCell}</td>
            </tr>
        `;
    }).reverse().join('');
}

export function buildBotStrategyForm(strategySchema) {
    const container = document.getElementById('bot-strategy-params');
    container.innerHTML = '';
    
    // Remove any previous strategy description in bot section
    const oldDesc = container.parentElement.querySelector('.strategy-description');
    if (oldDesc) oldDesc.remove();

    // Show strategy description
    const descDiv = document.createElement('div');
    descDiv.className = 'strategy-description';
    descDiv.innerHTML = `<p>${strategySchema.description}</p>`;
    container.parentElement.insertBefore(descDiv, container);
    
    strategySchema.parameters.forEach(param => {
        const step = param.type === 'float' ? '0.01' : '1';
        
        container.innerHTML += `
            <div class="form-group">
                <label for="bot-param-${param.name}">${param.name}</label>
                <input type="number" 
                       id="bot-param-${param.name}" 
                       data-type="${param.type}"
                       value="${param.default}" 
                       step="${step}" 
                       required>
                <small class="hint">${param.description}</small>
            </div>
        `;
    });
}
