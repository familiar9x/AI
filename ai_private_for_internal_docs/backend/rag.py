from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import hashlib

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from sentence_transformers import SentenceTransformer

@dataclass
class RagConfig:
    qdrant_url: str
    collection: str
    embed_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int

def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    # simple char-based chunking (v1). Later you can switch to token-based chunking.
    chunks = []
    i = 0
    n = len(text)
    step = max(1, chunk_size - overlap)
    while i < n:
        chunk = text[i:i+chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        i += step
    return chunks

def stable_id(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

class RagStore:
    def __init__(self, cfg: RagConfig):
        self.cfg = cfg
        self.client = QdrantClient(url=cfg.qdrant_url)
        self.embedder = SentenceTransformer(cfg.embed_model)

        self._ensure_collection()

    def _ensure_collection(self):
        dim = self.embedder.get_sentence_embedding_dimension()
        existing = [c.name for c in self.client.get_collections().collections]
        if self.cfg.collection not in existing:
            self.client.create_collection(
                collection_name=self.cfg.collection,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )

    def embed(self, texts: List[str]) -> np.ndarray:
        vecs = self.embedder.encode(texts, normalize_embeddings=True)
        return np.array(vecs, dtype=np.float32)

    def upsert_chunked(self, source_path: str, text: str, page_number: Optional[int] = None, meta: Optional[Dict[str, Any]] = None) -> int:
        chunks = chunk_text(text, self.cfg.chunk_size, self.cfg.chunk_overlap)
        if not chunks:
            return 0

        vecs = self.embed(chunks)

        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
            pid = stable_id(f"{source_path}::p{page_number}::c{i}::{chunk[:120]}")
            payload = {
                "source": source_path,
                "page_number": page_number,
                "chunk_index": i,
                "text": chunk,
            }
            if meta:
                payload.update(meta)
            points.append(qm.PointStruct(
                id=pid,
                vector=vec.tolist(),
                payload=payload
            ))

        self.client.upsert(collection_name=self.cfg.collection, points=points)
        return len(points)

    def search(self, query: str, top_k: Optional[int] = None, allowed_groups: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        k = top_k or self.cfg.top_k
        qv = self.embed([query])[0].tolist()
        
        # Build filter for group-based access control
        query_filter = None
        if allowed_groups:
            # Match documents with doc_group in allowed_groups, OR no doc_group (public)
            query_filter = qm.Filter(
                should=[
                    # Has doc_group and it's in allowed_groups
                    qm.FieldCondition(
                        key="doc_group",
                        match=qm.MatchAny(any=allowed_groups)
                    ),
                    # OR doesn't have doc_group (public docs)
                    qm.IsNullCondition(is_null=qm.PayloadField(key="doc_group"))
                ]
            )
        
        hits = self.client.search(
            collection_name=self.cfg.collection,
            query_vector=qv,
            limit=k,
            query_filter=query_filter,
            with_payload=True,
        )
        out = []
        for h in hits:
            p = h.payload or {}
            out.append({
                "score": float(h.score),
                "source": p.get("source"),
                "page_number": p.get("page_number"),
                "chunk_index": p.get("chunk_index"),
                "text": p.get("text"),
                "doc_group": p.get("doc_group"),
            })
        return out
