let equityChart = null;
let drawdownChart = null;
let equitySeries = null;
let drawdownSeries = null;

let botEquityChart = null;
let botDrawdownChart = null;
let botEquitySeries = null;
let botDrawdownSeries = null;

const chartOptions = {
    layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#94a3b8',
        fontFamily: 'Inter, sans-serif',
    },
    grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
    },
    rightPriceScale: {
        borderVisible: false,
    },
    timeScale: {
        borderVisible: false,
        timeVisible: false,
    },
    crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
    },
    handleScroll: { vertTouchDrag: false },
};

/**
 * Sanitizes a time-series array for TradingView Lightweight Charts.
 * The library REQUIRES strictly ascending, unique timestamps.
 * Duplicate dates crash it silently with no error message.
 */
function sanitizeTimeSeries(data) {
    if (!data || data.length === 0) return [];
    
    // Sort by time string (YYYY-MM-DD sorts lexicographically)
    const sorted = [...data].sort((a, b) => a.time.localeCompare(b.time));
    
    // Deduplicate: keep the last entry per date
    const seen = new Map();
    for (const point of sorted) {
        seen.set(point.time, point);
    }
    
    return Array.from(seen.values());
}

export function renderCharts(equityData, drawdownData) {
    const equityContainer = document.getElementById('chart-equity');
    const drawdownContainer = document.getElementById('chart-drawdown');
    
    // Clear existing charts completely
    if (equityChart) { equityChart.remove(); equityChart = null; }
    if (drawdownChart) { drawdownChart.remove(); drawdownChart = null; }
    equityContainer.innerHTML = '';
    drawdownContainer.innerHTML = '';
    
    // Sanitize data before passing to LightweightCharts
    const cleanEquity = sanitizeTimeSeries(equityData);
    const cleanDrawdown = sanitizeTimeSeries(drawdownData);
    
    if (cleanEquity.length === 0) {
        equityContainer.innerHTML = '<p style="padding:40px;color:#94a3b8;text-align:center;">No equity data to display.</p>';
        return;
    }
    
    // Initialize Equity Chart
    equityChart = LightweightCharts.createChart(equityContainer, {
        ...chartOptions,
        width: equityContainer.clientWidth,
        height: 400,
    });
    equitySeries = equityChart.addAreaSeries({
        lineColor: '#3b82f6',
        topColor: 'rgba(59, 130, 246, 0.4)',
        bottomColor: 'rgba(59, 130, 246, 0.0)',
        lineWidth: 2,
    });
    equitySeries.setData(cleanEquity);
    
    // Initialize Drawdown Chart
    drawdownChart = LightweightCharts.createChart(drawdownContainer, {
        ...chartOptions,
        width: drawdownContainer.clientWidth,
        height: 250,
    });
    drawdownSeries = drawdownChart.addAreaSeries({
        lineColor: '#ef4444',
        topColor: 'rgba(239, 68, 68, 0.0)',
        bottomColor: 'rgba(239, 68, 68, 0.4)',
        lineWidth: 2,
        invertFilledArea: true,
    });
    drawdownSeries.setData(cleanDrawdown);
    
    // Auto-fit data to viewport
    equityChart.timeScale().fitContent();
    drawdownChart.timeScale().fitContent();
}

export function renderBotCharts(equityData, drawdownData) {
    const equityContainer = document.getElementById('chart-bot-equity');
    const drawdownContainer = document.getElementById('chart-bot-drawdown');
    
    // Clear existing charts completely
    if (botEquityChart) { botEquityChart.remove(); botEquityChart = null; }
    if (botDrawdownChart) { botDrawdownChart.remove(); botDrawdownChart = null; }
    equityContainer.innerHTML = '';
    drawdownContainer.innerHTML = '';
    
    const cleanEquity = sanitizeTimeSeries(equityData);
    const cleanDrawdown = sanitizeTimeSeries(drawdownData);
    
    if (cleanEquity.length === 0) {
        equityContainer.innerHTML = '<p style="padding:40px;color:#94a3b8;text-align:center;">No live bot equity data to display.</p>';
        return;
    }
    
    // Initialize Bot Equity Chart
    botEquityChart = LightweightCharts.createChart(equityContainer, {
        ...chartOptions,
        width: equityContainer.clientWidth,
        height: 400,
    });
    botEquitySeries = botEquityChart.addAreaSeries({
        lineColor: '#10b981',
        topColor: 'rgba(16, 185, 129, 0.4)',
        bottomColor: 'rgba(16, 185, 129, 0.0)',
        lineWidth: 2,
    });
    botEquitySeries.setData(cleanEquity);
    
    // Initialize Bot Drawdown Chart
    botDrawdownChart = LightweightCharts.createChart(drawdownContainer, {
        ...chartOptions,
        width: drawdownContainer.clientWidth,
        height: 250,
    });
    botDrawdownSeries = botDrawdownChart.addAreaSeries({
        lineColor: '#ef4444',
        topColor: 'rgba(239, 68, 68, 0.0)',
        bottomColor: 'rgba(239, 68, 68, 0.4)',
        lineWidth: 2,
        invertFilledArea: true,
    });
    botDrawdownSeries.setData(cleanDrawdown);
    
    // Auto-fit data to viewport
    botEquityChart.timeScale().fitContent();
    botDrawdownChart.timeScale().fitContent();
}

export function handleResize() {
    const eqContainer = document.getElementById('chart-equity');
    const ddContainer = document.getElementById('chart-drawdown');
    if (equityChart && eqContainer) equityChart.resize(eqContainer.clientWidth, 400);
    if (drawdownChart && ddContainer) drawdownChart.resize(ddContainer.clientWidth, 250);

    const botEqContainer = document.getElementById('chart-bot-equity');
    const botDdContainer = document.getElementById('chart-bot-drawdown');
    if (botEquityChart && botEqContainer) botEquityChart.resize(botEqContainer.clientWidth, 400);
    if (botDrawdownChart && botDdContainer) botDrawdownChart.resize(botDdContainer.clientWidth, 250);
}

window.addEventListener('resize', handleResize);
