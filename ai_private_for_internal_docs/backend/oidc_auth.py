from __future__ import annotations
import os
import time
import requests
from fastapi import HTTPException

from jose import jwt
from jose.exceptions import JWTError

OIDC_ISSUER = os.environ.get("BACKEND_OIDC_ISSUER", "").rstrip("/")
OIDC_AUDIENCE = os.environ.get("BACKEND_OIDC_AUDIENCE", "")
JWKS_URL = f"{OIDC_ISSUER}/protocol/openid-connect/certs" if OIDC_ISSUER else ""

_jwks = None
_jwks_ts = 0

def _get_jwks():
    global _jwks, _jwks_ts
    if not JWKS_URL:
        raise RuntimeError("OIDC not configured")
    # refresh every 10 minutes
    if _jwks is None or (time.time() - _jwks_ts) > 600:
        _jwks = requests.get(JWKS_URL, timeout=10).json()
        _jwks_ts = time.time()
    return _jwks

def get_principal(authorization: str | None):
    """
    Verify JWT Bearer token and return principal info.
    
    Returns:
        {
            "sub": str,
            "email": str,
            "groups": list[str],  # AD groups from token
            "roles": list[str],   # Keycloak roles
            "claims": dict        # Full claims
        }
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    jwks = _get_jwks()

    try:
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER,
            options={"verify_at_hash": False},
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # groups claim: must be list of strings (AD group names)
    groups = claims.get("groups", []) or []
    if not isinstance(groups, list):
        groups = []

    # optional admin check via roles claim if you map it
    roles = (claims.get("realm_access", {}) or {}).get("roles", []) or []
    if not isinstance(roles, list):
        roles = []

    return {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "groups": groups,
        "roles": roles,
        "claims": claims,
    }

def require_group(principal: dict, allowed_groups: list[str]) -> bool:
    """
    Check if principal has any of the allowed groups.
    
    Usage:
        principal = get_principal(authorization)
        if not require_group(principal, ["rag-admins", "rag-users"]):
            raise HTTPException(403, "Forbidden")
    """
    user_groups = set(principal.get("groups", []))
    return bool(user_groups.intersection(allowed_groups))

def require_role(principal: dict, allowed_roles: list[str]) -> bool:
    """
    Check if principal has any of the allowed roles.
    
    Usage:
        principal = get_principal(authorization)
        if not require_role(principal, ["admin"]):
            raise HTTPException(403, "Forbidden")
    """
    user_roles = set(principal.get("roles", []))
    return bool(user_roles.intersection(allowed_roles))
