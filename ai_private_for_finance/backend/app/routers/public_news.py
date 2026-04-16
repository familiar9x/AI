from fastapi import APIRouter, HTTPException
from app.services.vector import embed_text, search_news
from app.services.cache import cache_get, cache_set

router = APIRouter(prefix="/public/news", tags=["public-news"])


@router.get("/search")
async def search(q: str, k: int = 8):
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="q is required")

    cache_key = f"news:search:{hash(q)}:{k}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        vec = await embed_text(q)
        hits = search_news(vec, limit=int(k))
        resp = {"q": q, "count": len(hits), "items": hits}
        cache_set(cache_key, resp, ttl_seconds=60)
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"search failed: {e}")
