from fastapi import APIRouter, HTTPException
from app.config import settings
from app.services.news import load_sources, fetch_rss_items
from app.services.cache import cache_setnx
from app.services.vector import embed_text, ensure_news_collection, upsert_news_items

router = APIRouter(prefix="/internal/news", tags=["internal-news"])


@router.get("/fetch")
def fetch(limit_per_source: int = 20):
    sources = load_sources(settings.NEWS_SOURCES_PATH)
    items = fetch_rss_items(sources, limit_per_source=limit_per_source) if sources else []
    return {"count": len(items), "items": [it.__dict__ for it in items]}


@router.post("/ingest")
async def ingest(limit_per_source: int = 30):
    sources = load_sources(settings.NEWS_SOURCES_PATH)
    if not sources:
        return {"ingested": 0, "skipped": 0, "reason": "No news sources configured"}

    items = fetch_rss_items(sources, limit_per_source=limit_per_source)
    raw = [it.__dict__ for it in items]

    new_items = []
    skipped = 0
    for it in raw:
        k = f"news:seen:{it.get('link') or it.get('title')}"
        if cache_setnx(k, True, ttl_seconds=7 * 86400):
            new_items.append(it)
        else:
            skipped += 1

    if not new_items:
        return {"ingested": 0, "skipped": skipped}

    try:
        vectors = []
        for t in [f"{x.get('title','')}\n\n{x.get('summary','')}" for x in new_items]:
            vectors.append(await embed_text(t))

        ensure_news_collection(vector_size=len(vectors[0]))
        n = upsert_news_items(new_items, vectors)
        return {"ingested": n, "skipped": skipped}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")
