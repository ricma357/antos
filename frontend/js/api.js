const API_BASE = '/api';

async function fetchJSON(url, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${url}`, {
            headers: { 'Content-Type': 'application/json' },
            ...options
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'API request failed');
        }
        
        return data;
    } catch (error) {
        showToast(error.message, 'error');
        throw error;
    }
}

export const api = {
    getSymbols: () => fetchJSON('/symbols'),
    getStrategies: () => fetchJSON('/strategies'),
    runBacktest: (payload) => fetchJSON('/backtest/', {
        method: 'POST',
        body: JSON.stringify(payload)
    }),
    getBotStatus: () => fetchJSON('/bot/status'),
    startBot: (payload) => fetchJSON('/bot/start', {
        method: 'POST',
        body: JSON.stringify(payload)
    }),
    stopBot: () => fetchJSON('/bot/stop', { method: 'POST' }),
    resetBot: () => fetchJSON('/bot/reset', { method: 'POST' }),
    triggerBotTick: () => fetchJSON('/bot/tick', { method: 'POST' }),
    getBotJournal: (limit = 100) => fetchJSON(`/bot/journal?limit=${limit}`),
    startScheduler: (intervalSeconds) => fetchJSON('/bot/scheduler/start', {
        method: 'POST',
        body: JSON.stringify({ interval_seconds: intervalSeconds })
    }),
    stopScheduler: () => fetchJSON('/bot/scheduler/stop', { method: 'POST' })
};

// Global Toast System
export function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
