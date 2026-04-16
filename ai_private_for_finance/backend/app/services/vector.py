from __future__ import annotations
from typing import List, Dict, Any, Optional
import hashlib
import httpx

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings


def qdrant() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)


async def embed_text(text: str) -> List[float]:
    if settings.EMBED_PROVIDER.lower() != "ollama":
        raise RuntimeError("EMBED_PROVIDER is not enabled. Set EMBED_PROVIDER=ollama")

    url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
    payload = {"model": settings.OLLAMA_MODEL, "prompt": text}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

    emb = data.get("embedding")
    if not emb:
        raise RuntimeError("No embedding returned from Ollama")
    return emb


def ensure_news_collection(vector_size: int) -> None:
    client = qdrant()
    name = settings.QDRANT_COLLECTION_NEWS

    cols = [c.name for c in client.get_collections().collections]
    if name in cols:
        return

    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
    )


def _stable_id(text: str) -> int:
    # Qdrant point id can be int; use hash -> int range
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(h[:15], 16)


def upsert_news_items(items: List[Dict[str, Any]], vectors: List[List[float]]) -> int:
    client = qdrant()
    name = settings.QDRANT_COLLECTION_NEWS

    points: List[qm.PointStruct] = []
    for it, vec in zip(items, vectors):
        pid = _stable_id((it.get("link") or "") + (it.get("title") or ""))
        payload = {
            "title": it.get("title"),
            "link": it.get("link"),
            "published": it.get("published"),
            "summary": it.get("summary"),
            "sentiment": it.get("sentiment"),
            "topic": it.get("topic"),
            "tickers": it.get("tickers") or [],
        }
        points.append(qm.PointStruct(id=pid, vector=vec, payload=payload))

    client.upsert(collection_name=name, points=points)
    return len(points)


def search_news(query_vector: List[float], limit: int = 8) -> List[Dict[str, Any]]:
    client = qdrant()
    name = settings.QDRANT_COLLECTION_NEWS

    hits = client.search(collection_name=name, query_vector=query_vector, limit=limit, with_payload=True)
    out: List[Dict[str, Any]] = []
    for h in hits:
        p = h.payload or {}
        p["_score"] = float(h.score)
        out.append(p)
    return out
