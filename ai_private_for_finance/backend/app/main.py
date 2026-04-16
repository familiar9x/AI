from fastapi import FastAPI

from app.routers import public_financial, public_chat, public_news
from app.routers import internal_news, internal_health

app = FastAPI(title="Finance AI Internal API", version="0.3.0")

# Public API (safe-ish)
app.include_router(public_financial.router)
app.include_router(public_chat.router)
app.include_router(public_news.router)

# Internal API (admin/ops)
app.include_router(internal_news.router)
app.include_router(internal_health.router)
