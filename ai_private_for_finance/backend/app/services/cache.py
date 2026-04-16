import json
from typing import Any, Optional
import redis

from app.config import settings

_redis = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)

def cache_get(key: str) -> Optional[Any]:
    v = _redis.get(key)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return v

def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    _redis.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)

def cache_setnx(key: str, value: Any, ttl_seconds: int = 86400) -> bool:
    # returns True if set, False if existed
    ok = _redis.set(key, json.dumps(value, ensure_ascii=False), nx=True, ex=ttl_seconds)
    return bool(ok)
