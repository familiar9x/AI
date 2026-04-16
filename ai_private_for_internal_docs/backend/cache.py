"""
Cache layer với 2-tier system + Admin helpers (v3):
1. Answer Cache (ans:*) - stores LLM responses
2. Negative Feedback Store (bad:*) - marks bad answers to bypass cache
3. Admin helpers - scan, view, delete, parse keys
"""
from __future__ import annotations
import os, json, time, hashlib
from typing import List, Dict, Any, Optional, Tuple
import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_TTL = int(os.environ.get("DEFAULT_CACHE_TTL_DAYS", "30"))
BAD_TTL = int(os.environ.get("BAD_MARK_TTL_DAYS", "365"))

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def normalize_question(q: str) -> str:
    """Normalize question for consistent caching"""
    return " ".join((q or "").strip().lower().split())

def hash_str(s: str) -> str:
    """Generate stable hash for string"""
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

def groups_hash(groups: List[str]) -> str:
    """Generate stable hash for groups list"""
    cleaned = [g.strip() for g in groups if isinstance(g, str) and g.strip()]
    return hash_str(",".join(sorted(cleaned)))

def corpus_version() -> int:
    """Get current corpus version"""
    v = r.get("corpus_version")
    if not v:
        r.set("corpus_version", "1")
        return 1
    return int(v)

def bump_corpus_version() -> int:
    """Increment corpus version (call after document ingestion)"""
    return int(r.incr("corpus_version"))

def _qhash(question: str) -> str:
    """Internal: hash normalized question"""
    return hash_str(normalize_question(question))

def answer_key(question: str, groups: List[str]) -> str:
    """Generate cache key for answer"""
    return f"ans:{corpus_version()}:{groups_hash(groups)}:{_qhash(question)}"

def bad_key(question: str, groups: List[str]) -> str:
    """Generate cache key for negative feedback"""
    return f"bad:{corpus_version()}:{groups_hash(groups)}:{_qhash(question)}"

def get_answer(question: str, groups: List[str]) -> Optional[Dict[str, Any]]:
    """Get cached answer if exists"""
    val = r.get(answer_key(question, groups))
    return json.loads(val) if val else None

def set_answer(question: str, groups: List[str], payload: Dict[str, Any], ttl_days: int = DEFAULT_TTL) -> str:
    """Store answer in cache with TTL"""
    k = answer_key(question, groups)
    r.set(k, json.dumps(payload, ensure_ascii=False))
    r.expire(k, ttl_days * 86400)
    return k

def mark_bad(question: str, groups: List[str], reason: Optional[str] = None) -> str:
    """Mark answer as bad (user reported dissatisfaction)"""
    k = bad_key(question, groups)
    data = {"ts": int(time.time()), "reason": reason}
    r.set(k, json.dumps(data, ensure_ascii=False))
    r.expire(k, BAD_TTL * 86400)
    return k

def is_bad(question: str, groups: List[str]) -> bool:
    """Check if answer was marked as bad"""
    return r.exists(bad_key(question, groups)) == 1

def delete_answer(question: str, groups: List[str]):
    """Delete cached answer"""
    r.delete(answer_key(question, groups))

def delete_bad(question: str, groups: List[str]):
    """Delete bad mark (admin clear)"""
    r.delete(bad_key(question, groups))

# ========= Recent response store (to link request_id -> question/groups/response) =========
def recent_set(request_id: str, record: Dict[str, Any], ttl_sec: int = 86400):
    """Store recent request data for feedback tracking"""
    r.set(f"recent:{request_id}", json.dumps(record, ensure_ascii=False))
    r.expire(f"recent:{request_id}", ttl_sec)

def recent_get(request_id: str) -> Optional[Dict[str, Any]]:
    """Get recent request data"""
    val = r.get(f"recent:{request_id}")
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None

# ========= Admin listing helpers =========
def scan_keys(pattern: str, limit: int = 200) -> List[str]:
    """Scan Redis keys matching pattern (non-blocking SCAN)"""
    out = []
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor=cursor, match=pattern, count=200)
        out.extend(batch)
        if len(out) >= limit or cursor == 0:
            break
    return out[:limit]

def key_ttl(key: str) -> int:
    """Get TTL of key in seconds (-1: no ttl, -2: not exist)"""
    return int(r.ttl(key))

def get_json(key: str) -> Optional[Dict[str, Any]]:
    """Get JSON value from Redis key"""
    val = r.get(key)
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None

def delete_key(key: str):
    """Delete any Redis key"""
    r.delete(key)

def parse_cache_key(key: str) -> Tuple[str, str, str, str]:
    """
    Parse cache key structure:
    ans:<ver>:<groups_hash>:<qhash>
    bad:<ver>:<groups_hash>:<qhash>
    Returns: (type, version, groups_hash, qhash)
    """
    parts = key.split(":")
    if len(parts) != 4:
        return ("", "", "", "")
    return (parts[0], parts[1], parts[2], parts[3])

def ping() -> bool:
    """Test Redis connection"""
    try:
        return r.ping()
    except Exception:
        return False

def cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    info = r.info()
    return {
        "corpus_version": corpus_version(),
        "redis": {
            "used_memory_human": info.get("used_memory_human"),
            "total_keys": r.dbsize(),
            "uptime_in_days": info.get("uptime_in_days"),
        }
    }


