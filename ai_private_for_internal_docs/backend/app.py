from __future__ import annotations
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from rag import RagConfig, RagStore

# v3: OIDC support
try:
    from oidc_auth import get_principal, require_group
    OIDC_ENABLED = bool(os.environ.get("BACKEND_OIDC_ISSUER"))
except Exception:
    OIDC_ENABLED = False

# Legacy API key (deprecated in v3, fallback only)
API_KEY = os.environ.get("API_KEY", "")

# Admin group for /admin/* endpoints
ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "RAG-ADMINS")

app = FastAPI(title="Private RAG Gateway")

cfg = RagConfig(
    qdrant_url=os.environ["QDRANT_URL"],
    collection=os.environ.get("QDRANT_COLLECTION", "internal_docs"),
    embed_model=os.environ.get("EMBED_MODEL", "sentence-transformers/bge-m3"),
    chunk_size=int(os.environ.get("CHUNK_SIZE", "900")),
    chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", "150")),
    top_k=int(os.environ.get("TOP_K", "6")),
)
store = RagStore(cfg)

LLM_BASE_URL = os.environ["LLM_BASE_URL"].rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

class ChatMsg(BaseModel):
    role: str
    content: str

class ChatReq(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMsg]
    temperature: Optional[float] = 0.2
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 512

def require_auth(authorization: str | None):
    """
    v3: OIDC JWT verification with fallback to API key.
    Returns principal dict if OIDC, None if API key.
    """
    if OIDC_ENABLED:
        # v3: Verify JWT
        principal = get_principal(authorization)
        # Optional: check groups
        # if not require_group(principal, ["rag-users", "rag-admins"]):
        #     raise HTTPException(status_code=403, detail="Forbidden: insufficient permissions")
        return principal
    else:
        # Legacy: API key
        if not API_KEY:
            return None
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != API_KEY:
            raise HTTPException(status_code=403, detail="Invalid API key")
        return None

def last_user_message(messages: List[ChatMsg]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return messages[-1].content if messages else ""

def build_system_prompt(context_chunks: List[Dict[str, Any]]) -> str:
    # Force citations with page numbers + strict JSON output
    parts = [
        "Bạn là trợ lý nội bộ. CHỈ trả lời dựa trên CONTEXT bên dưới.",
        "Nếu không đủ thông tin trong CONTEXT, trả lời đúng câu: 'Tôi không thấy thông tin này trong tài liệu nội bộ được cung cấp.'",
        "",
        "Luôn trả lời theo JSON format:",
        '{',
        '  "answer": "câu trả lời của bạn",',
        '  "citations": [',
        '    {"source": "tên file", "page": số_trang},',
        '    ...',
        '  ]',
        '}',
        "",
        "Nếu không có thông tin, citations = []",
        "",
        "CONTEXT:"
    ]
    for c in context_chunks:
        src = c.get("source")
        page = c.get("page_number")
        tag = f"{src} | page {page}" if page else f"{src}"
        parts.append(f"- ({tag}) {c.get('text','')}")
    return "\n".join(parts)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/admin/ingest")
def admin_ingest(
    authorization: str | None = Header(default=None),
    path: str | None = Query(default=None, description="relative to /app/docs or absolute path inside container"),
):
    principal = require_auth(authorization)
    
    # v3: Strict admin-only check
    if OIDC_ENABLED and principal:
        # Require ADMIN_GROUP for ingest
        if ADMIN_GROUP not in principal.get("groups", []):
            raise HTTPException(
                status_code=403, 
                detail=f"Forbidden: {ADMIN_GROUP} group required for ingest operations"
            )
    
    # Run ingest inside container (simple v1). In prod you'd do async worker.
    import subprocess

    cmd = ["python", "ingest.py"]
    if path:
        cmd.append(path)

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise HTTPException(status_code=500, detail=p.stderr[-2000:])
    return {"ok": True, "output": p.stdout[-4000:]}

@app.post("/v1/chat/completions")
def chat_completions(req: ChatReq, authorization: str | None = Header(default=None)):
    principal = require_auth(authorization)
    rid = str(uuid.uuid4())[:8]
    t0 = time.time()

    query = last_user_message(req.messages)
    
    # v3: Group-based filtering
    allowed_groups = None
    if OIDC_ENABLED and principal:
        allowed_groups = principal.get("groups", [])
    
    hits = store.search(query, allowed_groups=allowed_groups)

    system_prompt = build_system_prompt(hits)

    payload = {
        "model": (req.model or LLM_MODEL),
        "messages": [{"role": "system", "content": system_prompt}]
                    + [{"role": m.role, "content": m.content} for m in req.messages],
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
    }

    r = requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, timeout=120)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"LLM error {r.status_code}: {r.text[:500]}")

    data = r.json()
    # Add minimal timing info for debugging with page numbers
    data["rag_meta"] = {
        "request_id": rid,
        "retrieved": [
            {
                "source": h["source"],
                "page_number": h.get("page_number"),
                "chunk_index": h.get("chunk_index"),
                "score": h["score"],
                "doc_group": h.get("doc_group"),
            }
            for h in hits
        ],
        "latency_ms": int((time.time() - t0) * 1000),
    }
    
    # v3: Add user identity to metadata if OIDC
    if OIDC_ENABLED and principal:
        data["rag_meta"]["user"] = {
            "email": principal.get("email"),
            "groups": principal.get("groups", []),
        }
    
    return data
