import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from api.routes import strategies, symbols, backtest, bot

app = FastAPI(title="Antos Trading API")

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(strategies.router, prefix="/api", tags=["strategies"])
app.include_router(symbols.router, prefix="/api", tags=["symbols"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(bot.router, prefix="/api/bot", tags=["bot"])

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "Antos API is running, but frontend directory is missing."}
