from __future__ import annotations
import os
import time
import uuid
import json
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Query, Body, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from rag import RagConfig, RagStore
from cache import (
    get_answer, set_answer, is_bad, mark_bad, delete_answer, delete_bad,
    bump_corpus_version, corpus_version, recent_set, recent_get,
    scan_keys, key_ttl, get_json, delete_key, parse_cache_key, ping
)

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
    redis_ok = cache.ping()
    return {"ok": True, "redis": redis_ok}

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
    
    # Increment corpus version to invalidate all caches
    new_version = cache.bump_corpus_version()
    
    return {
        "ok": True, 
        "output": p.stdout[-4000:],
        "corpus_version": new_version
    }

@app.post("/v1/chat/completions")
def chat_completions(req: ChatReq, authorization: str | None = Header(default=None)):
    principal = require_auth(authorization)
    rid = str(uuid.uuid4())[:8]
    t0 = time.time()

    query = last_user_message(req.messages)
    
    # v3: Group-based filtering
    allowed_groups = []
    if OIDC_ENABLED and principal:
        allowed_groups = principal.get("groups", [])
    
    # 1️⃣ Check if marked as bad → bypass cache
    bypass = is_bad(query, allowed_groups)
    
    # 2️⃣ Try to get cached answer (if not bypassed)
    if not bypass:
        cached = get_answer(query, allowed_groups)
        if cached:
            # Return cached response with cache metadata
            cached["rag_meta"] = cached.get("rag_meta", {})
            cached["rag_meta"]["cache"] = {
                "hit": True, 
                "bypassed": False,
                "ttl_days": int(os.environ.get("DEFAULT_CACHE_TTL_DAYS", "30"))
            }
            cached["rag_meta"]["request_id"] = rid
            cached["rag_meta"]["feedback_url"] = f"/api/feedback/ui?request_id={rid}"
            
            # Store recent request for feedback tracking
            recent_set(rid, {
                "question": query,
                "groups": allowed_groups,
                "principal_sub": principal.get("sub") if principal else None,
                "principal_email": principal.get("email") if principal else None,
                "response": cached,
                "cached": True
            })
            
            return cached
    
    # 3️⃣ Cache miss or bypassed → call RAG + LLM
    hits = store.search(query, allowed_groups=allowed_groups if allowed_groups else None)
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
        "feedback_url": f"/api/feedback/ui?request_id={rid}",
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
        "cache": {"hit": False, "bypassed": bypass, "type": "default"}
    }
    
    # v3: Add user identity to metadata if OIDC
    if OIDC_ENABLED and principal:
        data["rag_meta"]["user"] = {
            "email": principal.get("email"),
            "groups": principal.get("groups", []),
        }
    
    # 4️⃣ Store in cache and recent tracking
    set_answer(query, allowed_groups, data)
    recent_set(rid, {
        "question": query,
        "groups": allowed_groups,
        "principal_sub": principal.get("sub") if principal else None,
        "principal_email": principal.get("email") if principal else None,
        "response": data,
        "cached": False
    })
    
    return data


@app.get("/feedback/ui", response_class=HTMLResponse)
def feedback_ui(request_id: str):
    """
    Simple feedback UI for users to report bad answers.
    Link is provided in rag_meta.feedback_url of each response.
    """
    return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Phản hồi câu trả lời</title>
        <style>
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            max-width: 600px;
            margin: 60px auto;
            padding: 20px;
            background: #f5f5f5;
          }}
          .card {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
          }}
          h2 {{
            color: #333;
            margin-top: 0;
          }}
          label {{
            display: block;
            margin: 15px 0 5px;
            font-weight: 500;
            color: #555;
          }}
          textarea {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-family: inherit;
            font-size: 14px;
            resize: vertical;
            box-sizing: border-box;
          }}
          button {{
            margin-top: 20px;
            padding: 12px 24px;
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
          }}
          button:hover {{
            background: #c82333;
          }}
          .info {{
            background: #fff3cd;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
            font-size: 14px;
            color: #856404;
          }}
          .rid {{
            font-size: 12px;
            color: #999;
            margin-top: 10px;
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h2>📝 Phản hồi câu trả lời</h2>
          <div class="info">
            ⚠️ Sau khi gửi phản hồi, câu trả lời này sẽ không được lưu cache nữa. 
            Lần sau hỏi lại sẽ gọi AI để tạo câu trả lời mới.
          </div>
          <form method="post" action="/api/feedback/bad">
            <input type="hidden" name="request_id" value="{request_id}" />
            
            <label for="reason">Lý do (tùy chọn):</label>
            <textarea 
              id="reason" 
              name="reason" 
              rows="5" 
              placeholder="Ví dụ: Thông tin không chính xác, thiếu chi tiết, không trả lời đúng câu hỏi..."
            ></textarea>
            
            <button type="submit">❌ Tôi không hài lòng với câu trả lời này</button>
          </form>
          <div class="rid">Request ID: {request_id}</div>
        </div>
      </body>
    </html>
    """


@app.post("/feedback/bad")
async def feedback_bad(request: Request, authorization: str | None = Header(default=None)):
    """
    Mark an answer as unsatisfactory/incorrect.
    Accepts HTML form data (application/x-www-form-urlencoded)
    This will:
    1. Mark the question as bad (bypass cache in future)
    2. Delete the cached answer
    """
    principal = require_auth(authorization)
    
    # Parse form data
    form = await request.form()
    request_id = str(form.get("request_id", "")).strip()
    reason = str(form.get("reason", "")).strip() or None
    
    # Retrieve the recent request data
    rec = recent_get(request_id)
    if not rec:
        return HTMLResponse(
            \"\"\"
            <html><body style="font-family: Arial; margin:40px;">
              <h3>❌ Request ID không tồn tại hoặc đã hết hạn</h3>
              <p>Request chỉ được lưu trong 24 giờ.</p>
              <a href="/">← Quay lại</a>
            </body></html>
            \"\"\",
            status_code=404
        )
    
    # Ensure scope match: user groups must match cache scope
    current_groups = []
    if OIDC_ENABLED and principal:
        current_groups = principal.get("groups", [])
    
    if sorted(rec.get("groups", [])) != sorted(current_groups):
        return HTMLResponse(
            \"\"\"
            <html><body style="font-family: Arial; margin:40px;">
              <h3>🚫 Không thể report: scope quyền không khớp</h3>
              <p>Bạn chỉ có thể report feedback cho các câu hỏi trong nhóm quyền của bạn.</p>
              <a href="/">← Quay lại</a>
            </body></html>
            \"\"\",
            status_code=403
        )
    
    # Mark as bad and delete cache
    mark_bad(rec["question"], rec["groups"], reason=reason)
    delete_answer(rec["question"], rec["groups"])
    
    return HTMLResponse(
        \"\"\"
        <html><body style="font-family: Arial; margin:40px;">
          <h3>✅ Đã ghi nhận phản hồi</h3>
          <p>Lần sau hệ thống sẽ bỏ qua cache cho câu hỏi này và generate lại.</p>
          <a href="/">← Quay lại</a>
        </body></html>
        \"\"\"
    )


@app.get("/admin/cache/stats")
def admin_cache_stats(
    authorization: str | None = Header(default=None),
):
    """
    Get cache statistics (admin only) - JSON API.
    """
    principal = require_auth(authorization)
    
    # v3: Strict admin-only check
    if OIDC_ENABLED and principal:
        if ADMIN_GROUP not in principal.get("groups", []):
            raise HTTPException(
                status_code=403, 
                detail=f"Forbidden: {ADMIN_GROUP} group required"
            )
    
    from cache import cache_stats
    return cache_stats()


# ========= Admin UI Endpoints =========

def require_admin(principal: dict):
    """Helper to check if user is in admin group"""
    if ADMIN_GROUP not in (principal.get("groups") or []):
        raise HTTPException(status_code=403, detail="Admin only")


@app.get("/admin/ui", response_class=HTMLResponse)
def admin_ui(authorization: str | None = Header(default=None), limit: int = 100):
    """
    Admin dashboard - view cache, bad marks, manage corpus version.
    Only accessible to users in ADMIN_GROUP.
    """
    principal = require_auth(authorization)
    require_admin(principal)

    ttl_days = int(os.environ.get("DEFAULT_CACHE_TTL_DAYS", "30"))
    cv = corpus_version()

    bad_keys = scan_keys("bad:*", limit=limit)
    ans_keys = scan_keys("ans:*", limit=limit)

    def li(key: str) -> str:
        ttl = key_ttl(key)
        ttl_str = f"{ttl}s" if ttl > 0 else ("no-expire" if ttl == -1 else "expired")
        prefix, ver, gh, qh = parse_cache_key(key)
        extra = ""
        if prefix == "bad":
            extra = f""" | <a href="/api/admin/clear_bad?key={key}" style="color: #28a745;">clear_bad</a>"""
        if prefix == "ans":
            extra = f""" | <a href="/api/admin/clear_pair?key={key}" style="color: #17a2b8;">clear_pair_bad</a> | <a href="/api/admin/override?key={key}" style="color: #ffc107;">override</a>"""
        return f"""<li style="margin: 8px 0;">
            <code style="background: #f0f0f0; padding: 2px 6px; border-radius: 3px;">{key}</code> 
            <span style="color: #666;">(ttl={ttl_str})</span>
            <a href="/api/admin/view?key={key}" style="margin: 0 8px;">view</a>
            <a href="/api/admin/delete?key={key}" style="color: #dc3545;">delete</a>
            {extra}
        </li>"""

    bad_list = "\n".join([li(k) for k in bad_keys]) or "<li style='color: #999;'>(none)</li>"
    ans_list = "\n".join([li(k) for k in ans_keys]) or "<li style='color: #999;'>(none)</li>"

    return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RAG Admin Panel</title>
        <style>
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
          }}
          .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
          }}
          h2 {{
            color: #333;
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
          }}
          h3 {{
            color: #555;
            margin-top: 30px;
          }}
          .info {{
            background: #e7f3ff;
            padding: 12px;
            border-radius: 4px;
            margin: 15px 0;
            border-left: 4px solid #007bff;
          }}
          .warning {{
            background: #fff3cd;
            padding: 12px;
            border-radius: 4px;
            margin: 15px 0;
            border-left: 4px solid #ffc107;
          }}
          ul {{
            list-style: none;
            padding: 0;
          }}
          button {{
            padding: 10px 16px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
          }}
          button:hover {{
            background: #0056b3;
          }}
          button.danger {{
            background: #dc3545;
          }}
          button.danger:hover {{
            background: #c82333;
          }}
          a {{
            color: #007bff;
            text-decoration: none;
          }}
          a:hover {{
            text-decoration: underline;
          }}
          hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 30px 0;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <h2>🛠️ RAG Admin Panel</h2>

          <div class="info">
            <strong>Signed in:</strong> {principal.get("email") or principal.get("sub")}<br/>
            <strong>Admin group:</strong> {ADMIN_GROUP}
          </div>

          <hr/>

          <h3>📦 Corpus Version</h3>
          <p>Current corpus_version = <strong style="font-size: 24px; color: #007bff;">{cv}</strong></p>
          <div class="warning">
            ⚠️ Bumping corpus version will invalidate ALL existing caches (ans:* and bad:* keys will use new version number).
          </div>
          <form method="post" action="/api/admin/bump">
            <button type="submit" class="danger">🔄 Bump corpus_version (invalidate all caches)</button>
          </form>

          <hr/>

          <h3>🚫 Bad marks (reported by users)</h3>
          <p>Showing up to {limit} keys. These questions will bypass cache.</p>
          <ul>{bad_list}</ul>

          <hr/>

          <h3>💾 Answer cache (default {ttl_days} days TTL)</h3>
          <p>Showing up to {limit} keys.</p>
          <ul>{ans_list}</ul>

          <hr/>
          
          <p style="color: #666; font-size: 14px;">
            💡 <strong>Tip:</strong> Cache keys include corpus_version. Bumping version makes old caches naturally ignored.
          </p>
        </div>
      </body>
    </html>
    """


@app.get("/admin/view", response_class=HTMLResponse)
def admin_view(key: str, authorization: str | None = Header(default=None)):
    """
    View details of a specific Redis key (admin only).
    """
    principal = require_auth(authorization)
    require_admin(principal)

    ttl = key_ttl(key)
    payload = get_json(key)

    pretty = "<i style='color: #999;'>(no json / empty)</i>"
    if payload is not None:
        import html, json
        pretty = f"<pre style='white-space: pre-wrap; background:#f6f6f6; padding:16px; border-radius:6px; overflow-x: auto; font-size: 13px;'>{html.escape(json.dumps(payload, ensure_ascii=False, indent=2))}</pre>"

    # Parse key structure
    key_type, ver, ghash, qhash = parse_cache_key(key)
    key_info = ""
    if key_type in ("ans", "bad"):
        key_info = f"""
        <div style="background: #f8f9fa; padding: 12px; border-radius: 4px; margin: 15px 0;">
          <strong>Key Structure:</strong><br/>
          Type: <code>{key_type}</code><br/>
          Corpus Version: <code>{ver}</code><br/>
          Groups Hash: <code>{ghash}</code><br/>
          Question Hash: <code>{qhash}</code>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>View Key - Admin</title>
        <style>
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
          }}
          .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
          }}
          h2 {{
            color: #333;
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
          }}
          code {{
            background: #f0f0f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 14px;
          }}
          a {{
            color: #007bff;
            text-decoration: none;
          }}
          a:hover {{
            text-decoration: underline;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <h2>🔍 View Redis Key</h2>
          <p><code style="font-size: 16px;">{key}</code></p>
          <p><strong>TTL:</strong> {ttl} seconds</p>
          <p><a href="/api/admin/ui">← Back to admin</a></p>
          
          {key_info}
          
          <h3>Payload:</h3>
          {pretty}
        </div>
      </body>
    </html>
    """


@app.get("/admin/delete", response_class=HTMLResponse)
def admin_delete(key: str, authorization: str | None = Header(default=None)):
    """
    Delete a specific Redis key (admin only).
    """
    principal = require_auth(authorization)
    require_admin(principal)

    delete_key(key)
    return HTMLResponse(f"""
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8"/>
          <title>Deleted - Admin</title>
          <style>
            body {{
              font-family: Arial, sans-serif;
              margin: 40px;
              background: #f5f5f5;
            }}
            .card {{
              background: white;
              padding: 30px;
              border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              max-width: 600px;
            }}
            h3 {{
              color: #28a745;
            }}
            code {{
              background: #f0f0f0;
              padding: 2px 6px;
              border-radius: 3px;
            }}
            a {{
              color: #007bff;
              text-decoration: none;
            }}
            a:hover {{
              text-decoration: underline;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h3>✅ Deleted Successfully</h3>
            <p><code>{key}</code></p>
            <p><a href="/api/admin/ui">← Back to admin panel</a></p>
          </div>
        </body>
      </html>
    """)


@app.post("/admin/bump", response_class=HTMLResponse)
async def admin_bump(request: Request, authorization: str | None = Header(default=None)):
    """
    Bump corpus version (admin only).
    This invalidates all existing caches.
    """
    principal = require_auth(authorization)
    require_admin(principal)

    new_v = bump_corpus_version()
    return HTMLResponse(f"""
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8"/>
          <title>Version Bumped - Admin</title>
          <style>
            body {{
              font-family: Arial, sans-serif;
              margin: 40px;
              background: #f5f5f5;
            }}
            .card {{
              background: white;
              padding: 30px;
              border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              max-width: 600px;
            }}
            h3 {{
              color: #007bff;
            }}
            .warning {{
              background: #fff3cd;
              padding: 12px;
              border-radius: 4px;
              margin: 15px 0;
              border-left: 4px solid #ffc107;
            }}
            a {{
              color: #007bff;
              text-decoration: none;
            }}
            a:hover {{
              text-decoration: underline;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h3>✅ Corpus version bumped</h3>
            <p>New corpus_version = <strong style="font-size: 28px; color: #007bff;">{new_v}</strong></p>
            <div class="warning">
              ⚠️ All old caches (with version {new_v - 1}) are now invalid and won't be used.
            </div>
            <p><a href="/api/admin/ui">← Back to admin panel</a></p>
          </div>
        </body>
      </html>
    """)


@app.get("/admin/clear_bad", response_class=HTMLResponse)
def admin_clear_bad(key: str, authorization: str | None = Header(default=None)):
    """
    Clear a bad mark (admin only).
    Allows the question to be cached again.
    """
    principal = require_auth(authorization)
    require_admin(principal)

    prefix, ver, gh, qh = parse_cache_key(key)
    if prefix != "bad":
        return HTMLResponse(
            """<html><body style="font-family: Arial; margin:30px;">
              <h3>❌ Invalid key (not bad:*)</h3>
              <p><a href="/api/admin/ui">← Back to admin</a></p>
            </body></html>""",
            status_code=400
        )

    delete_key(key)
    return HTMLResponse(f"""
      <html>
        <head>
          <meta charset="utf-8"/>
          <title>Cleared Bad Mark - Admin</title>
          <style>
            body {{
              font-family: Arial, sans-serif;
              margin: 40px;
              background: #f5f5f5;
            }}
            .card {{
              background: white;
              padding: 30px;
              border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              max-width: 600px;
            }}
            h3 {{
              color: #28a745;
            }}
            code {{
              background: #f0f0f0;
              padding: 2px 6px;
              border-radius: 3px;
            }}
            a {{
              color: #007bff;
              text-decoration: none;
            }}
            a:hover {{
              text-decoration: underline;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h3>✅ Cleared bad mark</h3>
            <p><code>{key}</code></p>
            <p>This question can now be cached again.</p>
            <p><a href="/api/admin/ui">← Back to admin panel</a></p>
          </div>
        </body>
      </html>
    """)


@app.get("/admin/clear_pair", response_class=HTMLResponse)
def admin_clear_pair(key: str, authorization: str | None = Header(default=None)):
    """
    Clear the corresponding bad mark for an answer key (admin only).
    """
    principal = require_auth(authorization)
    require_admin(principal)

    prefix, ver, gh, qh = parse_cache_key(key)
    if prefix != "ans":
        return HTMLResponse(
            """<html><body style="font-family: Arial; margin:30px;">
              <h3>❌ Invalid key (not ans:*)</h3>
              <p><a href="/api/admin/ui">← Back to admin</a></p>
            </body></html>""",
            status_code=400
        )

    bad_key = f"bad:{ver}:{gh}:{qh}"
    existed = key_ttl(bad_key) >= -1  # -1 = no expire, >= 0 = has TTL, -2 = doesn't exist
    delete_key(bad_key)
    
    status_msg = "existed and was cleared" if existed else "didn't exist (already clean)"
    
    return HTMLResponse(f"""
      <html>
        <head>
          <meta charset="utf-8"/>
          <title>Cleared Paired Bad - Admin</title>
          <style>
            body {{
              font-family: Arial, sans-serif;
              margin: 40px;
              background: #f5f5f5;
            }}
            .card {{
              background: white;
              padding: 30px;
              border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              max-width: 600px;
            }}
            h3 {{
              color: #17a2b8;
            }}
            code {{
              background: #f0f0f0;
              padding: 2px 6px;
              border-radius: 3px;
            }}
            a {{
              color: #007bff;
              text-decoration: none;
            }}
            a:hover {{
              text-decoration: underline;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h3>✅ Cleared paired bad mark</h3>
            <p>Answer key: <code>{key}</code></p>
            <p>Bad key: <code>{bad_key}</code></p>
            <p>Status: <strong>{status_msg}</strong></p>
            <p><a href="/api/admin/ui">← Back to admin panel</a></p>
          </div>
        </body>
      </html>
    """)


@app.get("/admin/override", response_class=HTMLResponse)
def admin_override_form(key: str, authorization: str | None = Header(default=None)):
    """
    Show form to override a cached answer (admin only).
    """
    principal = require_auth(authorization)
    require_admin(principal)

    prefix, ver, gh, qh = parse_cache_key(key)
    if prefix != "ans":
        return HTMLResponse(
            """<html><body style="font-family: Arial; margin:30px;">
              <h3>❌ Invalid key (not ans:*)</h3>
              <p><a href="/api/admin/ui">← Back to admin</a></p>
            </body></html>""",
            status_code=400
        )

    existing = get_json(key) or {}
    # Try to prefill with current assistant message content if exists
    try:
        cur = existing["choices"][0]["message"]["content"]
    except Exception:
        cur = ""

    import html
    cur_esc = html.escape(cur)
    key_esc = html.escape(key)

    return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Override Answer - Admin</title>
        <style>
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
          }}
          .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
          }}
          h2 {{
            color: #333;
            border-bottom: 2px solid #ffc107;
            padding-bottom: 10px;
          }}
          label {{
            display: block;
            margin: 15px 0 5px;
            font-weight: 500;
            color: #555;
          }}
          textarea {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            resize: vertical;
            box-sizing: border-box;
          }}
          input[type="text"] {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            box-sizing: border-box;
          }}
          button {{
            padding: 12px 24px;
            background: #ffc107;
            color: #333;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            margin-right: 10px;
          }}
          button:hover {{
            background: #ffb300;
          }}
          a {{
            color: #007bff;
            text-decoration: none;
            padding: 12px 24px;
            display: inline-block;
          }}
          a:hover {{
            text-decoration: underline;
          }}
          .warning {{
            background: #fff3cd;
            padding: 12px;
            border-radius: 4px;
            margin: 15px 0;
            border-left: 4px solid #ffc107;
            font-size: 14px;
            color: #856404;
          }}
          code {{
            background: #f0f0f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 13px;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <h2>🔧 Override cached answer</h2>
          <p><code>{key_esc}</code></p>
          
          <form method="post" action="/api/admin/override_save">
            <input type="hidden" name="key" value="{key_esc}" />
            
            <label for="content"><b>New answer content</b></label>
            <textarea id="content" name="content" rows="14">{cur_esc}</textarea>

            <label for="note">Optional note (admin reference)</label>
            <input type="text" id="note" name="note" placeholder="Why override / reference / ticket number..." />

            <div style="margin-top: 20px;">
              <button type="submit">💾 Save override</button>
              <a href="/api/admin/ui">Cancel</a>
            </div>
          </form>
          
          <div class="warning">
            ⚠️ <strong>What happens:</strong><br/>
            • Overwrites the cached response (ans:*)<br/>
            • Resets TTL to {int(os.environ.get('DEFAULT_CACHE_TTL_DAYS', '30'))} days<br/>
            • Clears the corresponding bad:* mark (if exists)<br/>
            • Adds admin_override metadata to rag_meta
          </div>
        </div>
      </body>
    </html>
    """


@app.post("/admin/override_save", response_class=HTMLResponse)
async def admin_override_save(request: Request, authorization: str | None = Header(default=None)):
    """
    Save overridden answer (admin only).
    """
    principal = require_auth(authorization)
    require_admin(principal)

    form = await request.form()
    key = str(form.get("key", "")).strip()
    content = str(form.get("content", "")).strip()
    note = str(form.get("note", "")).strip() or None

    prefix, ver, gh, qh = parse_cache_key(key)
    if prefix != "ans":
        return HTMLResponse(
            """<html><body style="font-family: Arial; margin:30px;">
              <h3>❌ Invalid key</h3>
              <p><a href="/api/admin/ui">← Back to admin</a></p>
            </body></html>""",
            status_code=400
        )

    payload = get_json(key) or {}

    # Overwrite assistant content in OpenAI-like structure
    if "choices" not in payload or not payload["choices"]:
        payload["choices"] = [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop"
            }
        ]
    else:
        payload.setdefault("choices", [{}])
        payload["choices"][0].setdefault("message", {})
        payload["choices"][0]["message"]["role"] = "assistant"
        payload["choices"][0]["message"]["content"] = content

    payload.setdefault("rag_meta", {})
    payload["rag_meta"]["admin_override"] = {
        "by": principal.get("email") or principal.get("sub"),
        "ts": int(time.time()),
        "note": note,
    }
    payload["rag_meta"]["cache"] = {"hit": True, "type": "override"}

    # Save back with TTL = DEFAULT_CACHE_TTL_DAYS
    ttl_days = int(os.environ.get("DEFAULT_CACHE_TTL_DAYS", "30"))
    delete_key(key)
    from cache import r as redis_client
    redis_client.set(key, json.dumps(payload, ensure_ascii=False))
    redis_client.expire(key, ttl_days * 86400)

    # Clear bad mark if exists for same ver/gh/qh
    bad = f"bad:{ver}:{gh}:{qh}"
    delete_key(bad)

    return HTMLResponse(f"""
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8"/>
          <title>Override Saved - Admin</title>
          <style>
            body {{
              font-family: Arial, sans-serif;
              margin: 40px;
              background: #f5f5f5;
            }}
            .card {{
              background: white;
              padding: 30px;
              border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              max-width: 600px;
            }}
            h3 {{
              color: #ffc107;
            }}
            code {{
              background: #f0f0f0;
              padding: 2px 6px;
              border-radius: 3px;
            }}
            a {{
              color: #007bff;
              text-decoration: none;
              margin: 0 10px;
            }}
            a:hover {{
              text-decoration: underline;
            }}
            .success {{
              background: #d4edda;
              padding: 12px;
              border-radius: 4px;
              margin: 15px 0;
              border-left: 4px solid #28a745;
              color: #155724;
            }}
          </style>
        </head>
        <body>
          <div class="card">
            <h3>✅ Override saved successfully</h3>
            <div class="success">
              <strong>Changes applied:</strong><br/>
              • Answer content updated<br/>
              • TTL reset to {ttl_days} days<br/>
              • Bad mark cleared: <code>{bad}</code><br/>
              • Admin override metadata added
            </div>
            <p>Saved to: <code>{key}</code></p>
            <p>
              <a href="/api/admin/view?key={key}">📄 View key</a>
              <a href="/api/admin/ui">← Back to admin panel</a>
            </p>
          </div>
        </body>
      </html>
    """)

