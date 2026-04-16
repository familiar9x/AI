from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.financial import build_financial_summary
from app.services.cache import cache_get, cache_set

router = APIRouter(prefix="/public/financial", tags=["public-financial"])


@router.get("/summary/{ticker}")
async def summary(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper()
    cache_key = f"fin:summary:{ticker}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        res = await build_financial_summary(db, ticker)
        payload = {
            "ticker": res.ticker,
            "latest_period_end": res.latest_period_end,
            "metrics_latest": res.metrics_latest,
            "deltas": res.deltas,
            "red_flags": res.red_flags,
            "narrative": res.narrative,
            "disclaimer": "Thông tin chỉ mang tính tham khảo, không phải khuyến nghị đầu tư."
        }
        cache_set(cache_key, payload, ttl_seconds=300)
        return payload
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
