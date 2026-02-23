# Version 3 - Enterprise SSO with Keycloak

## What's New in v3

### 🔐 Enterprise Authentication & Authorization

- **SSO via Keycloak**: Single Sign-On với OIDC/OAuth2
- **JWT Verification**: Backend verify JWT tokens từ Keycloak
- **AD Group Integration**: Authorization dựa trên AD groups
- **oauth2-proxy**: Transparent SSO cho cả UI và API
- **Nginx Reverse Proxy**: Unified entry point với HTTPS

### 🎯 Key Features

1. **Centralized Authentication**: Keycloak external, không cần maintain user database
2. **Group-based AuthZ**: Control access theo AD groups (`rag-admins`, `rag-users`)
3. **Transparent SSO**: Users login một lần, access cả UI và API
4. **Secure by Default**: HTTPS only, JWT verification, cookie security

## Architecture v3

```
Users (Browser/API)
    ↓ HTTPS
Nginx (443) ───→ oauth2-proxy (SSO)
    │                    ↓ (verify with Keycloak)
    ├─→ / (UI) ─────→ OpenWebUI (protected)
    │                    ↓
    └─→ /api ───────→ Backend (JWT verify)
                         ↓
                    Qdrant + vLLM
```

**External:**
- Keycloak (keycloak.company.local) - OIDC Provider

**Internal Stack:**
- Nginx - Reverse proxy + auth_request
- oauth2-proxy - SSO middleware
- OpenWebUI - Chat interface
- Backend - RAG API with JWT verification
- Qdrant - Vector DB
- vLLM - LLM inference

## Prerequisites

### 1. Keycloak Setup

**Create Realm:**
```
Realm: internal-apps (hoặc tên của bạn)
```

**Create Client:**
```
Client ID: rag-proxy
Client Protocol: openid-connect
Access Type: confidential
Valid Redirect URIs: https://rag.company.local/oauth2/callback
Web Origins: https://rag.company.local
```

**Client Scopes:**
```
- email (default)
- profile (default)
- groups (add this)
```

**Group Mapper:**
```
Name: groups
Mapper Type: Group Membership
Token Claim Name: groups
Full group path: OFF
Add to ID token: ON
Add to access token: ON
Add to userinfo: ON
```

**Create Groups:**
```
- rag-admins (can ingest documents)
- rag-users (can query only)
```

**Assign Users to Groups:**
```
Users → Select user → Groups → Join Group
```

### 2. DNS Configuration

```bash
# Add to /etc/hosts or DNS server
10.0.0.100  rag.company.local
10.0.0.101  keycloak.company.local
```

### 3. SSL Certificates

```bash
cd nginx/certs

# Self-signed (development)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/C=VN/ST=HCM/L=HCMC/O=Company/CN=rag.company.local"

# Production: Use Let's Encrypt or corporate CA
```

## Configuration

### 1. Update .env

```bash
# ========== OIDC (Keycloak) ==========
OIDC_ISSUER=https://keycloak.company.local/realms/internal-apps
OIDC_AUDIENCE=rag-proxy

BACKEND_OIDC_ISSUER=https://keycloak.company.local/realms/internal-apps
BACKEND_OIDC_AUDIENCE=rag-proxy

# ========== oauth2-proxy ==========
OAUTH2_PROXY_PROVIDER=keycloak-oidc
OAUTH2_PROXY_OIDC_ISSUER_URL=https://keycloak.company.local/realms/internal-apps
OAUTH2_PROXY_CLIENT_ID=rag-proxy
OAUTH2_PROXY_CLIENT_SECRET=your-client-secret-from-keycloak
OAUTH2_PROXY_COOKIE_SECRET=<generate-this>
OAUTH2_PROXY_COOKIE_SECURE=true
OAUTH2_PROXY_COOKIE_SAMESITE=lax
OAUTH2_PROXY_EMAIL_DOMAINS=*

OAUTH2_PROXY_HTTP_ADDRESS=0.0.0.0:4180
OAUTH2_PROXY_PASS_ACCESS_TOKEN=true
OAUTH2_PROXY_SET_AUTHORIZATION_HEADER=true
OAUTH2_PROXY_SET_XAUTHREQUEST=true
```

**Generate Cookie Secret:**
```bash
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

### 2. Update OpenWebUI Base URL

In docker-compose.yml:
```yaml
openwebui:
  environment:
    - OPENAI_API_BASE_URL=https://rag.company.local/api/v1
```

### 3. Nginx Server Name

Update `nginx/conf.d/default.conf`:
```nginx
server_name rag.company.local;
```

## Deployment

```bash
cd /home/ansible/private-rag

# Build and start
docker-compose up -d --build

# Check logs
docker-compose logs -f oauth2-proxy
docker-compose logs -f nginx
docker-compose logs -f backend

# Verify services
curl -k https://rag.company.local/oauth2/ping
```

## Usage

### Web UI

1. Open browser: `https://rag.company.local`
2. Redirected to Keycloak login
3. Login with AD credentials
4. Redirected back to OpenWebUI
5. Start chatting!

### API Access

**Option 1: Browser session (cookie)**
```bash
# After login in browser, cookies are set
# API calls from same browser work automatically
```

**Option 2: Service account (JWT)**
```bash
# Get token from Keycloak
TOKEN=$(curl -X POST "https://keycloak.company.local/realms/internal-apps/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=rag-proxy" \
  -d "client_secret=YOUR_SECRET" \
  -d "grant_type=client_credentials" | jq -r .access_token)

# Call API
curl -X POST "https://rag.company.local/api/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen2.5-7B-Instruct",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Option 3: User token (interactive)**
```bash
# Use oauth2-proxy login flow, extract token from cookie
# Or implement OAuth2 Authorization Code flow in your app
```

## Authorization

### Group-based Access Control

**Edit `backend/app.py`:**

```python
@app.post("/admin/ingest")
def admin_ingest(...):
    principal = require_auth(authorization)
    
    # Require rag-admins group
    if OIDC_ENABLED and principal:
        if not require_group(principal, ["rag-admins"]):
            raise HTTPException(403, "Admin access required")
    
    # ... ingest logic
```

**Available helper functions:**

```python
from oidc_auth import get_principal, require_group, require_role

principal = get_principal(authorization)
# Returns: {
#   "sub": "...",
#   "email": "user@company.com",
#   "groups": ["rag-users", "rag-admins"],
#   "roles": ["user"],
#   "claims": {...}
# }

# Check groups
if require_group(principal, ["rag-admins"]):
    # User is admin
    pass

# Check roles
if require_role(principal, ["admin"]):
    # User has admin role
    pass
```

### Example Authorization Scenarios

**Scenario 1: Everyone can query, only admins can ingest**
```python
@app.post("/v1/chat/completions")
def chat(...):
    require_auth(authorization)  # Any authenticated user
    # ...

@app.post("/admin/ingest")
def ingest(...):
    principal = require_auth(authorization)
    if not require_group(principal, ["rag-admins"]):
        raise HTTPException(403, "Forbidden")
    # ...
```

**Scenario 2: Department-specific access**
```python
@app.post("/v1/chat/completions")
def chat(...):
    principal = require_auth(authorization)
    if not require_group(principal, ["dept-finance", "dept-hr"]):
        raise HTTPException(403, "Access limited to Finance/HR")
    # ...
```

## Troubleshooting

### 1. Keycloak Connection Failed

```bash
# Test from backend container
docker exec -it rag-backend curl -v https://keycloak.company.local/realms/internal-apps/.well-known/openid-configuration

# Check DNS
docker exec -it rag-backend nslookup keycloak.company.local

# Check SSL trust
docker exec -it rag-backend curl -k https://keycloak.company.local
```

**Fix: Add CA certificate**
```dockerfile
# backend/Dockerfile
COPY corporate-ca.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
```

### 2. JWT Verification Failed

```bash
# Check token claims
docker exec -it rag-backend python
>>> from oidc_auth import get_principal
>>> get_principal("Bearer YOUR_TOKEN")
# Should see claims

# Check JWKS endpoint
curl https://keycloak.company.local/realms/internal-apps/protocol/openid-connect/certs
```

**Common issues:**
- Audience mismatch: Check `OIDC_AUDIENCE` matches client ID
- Issuer mismatch: Check `OIDC_ISSUER` URL exactly matches token issuer
- Clock skew: Sync server time with NTP

### 3. oauth2-proxy Redirect Loop

```bash
# Check oauth2-proxy logs
docker-compose logs oauth2-proxy | grep -i error

# Verify redirect URIs in Keycloak
# Must match: https://rag.company.local/oauth2/callback

# Check cookie settings
# If behind another proxy, may need OAUTH2_PROXY_COOKIE_SECURE=false
```

### 4. Groups Not in Token

**Keycloak config:**
1. Client Scopes → groups → Mappers
2. Ensure "Group Membership" mapper exists
3. Check "Add to access token" is ON
4. Check "Full group path" is OFF
5. Regenerate token and verify

**Test token:**
```bash
TOKEN="YOUR_TOKEN"
echo $TOKEN | cut -d. -f2 | base64 -d | jq .groups
# Should show: ["rag-users", "rag-admins"]
```

### 5. Nginx 502 Bad Gateway

```bash
# Check all services running
docker-compose ps

# Check backend logs
docker-compose logs backend

# Test backend directly
curl http://localhost:8080/healthz

# Test oauth2-proxy
curl http://localhost:4180/ping
```

## Security Best Practices

### 1. Secrets Management

```bash
# Use Docker secrets or external secret store
# NOT in .env for production

# Example with Docker secrets:
docker secret create oauth2_client_secret client_secret.txt
```

### 2. Network Isolation

```yaml
# docker-compose.yml
services:
  backend:
    networks:
      - internal
      - external
  
  vllm:
    networks:
      - internal  # Only internal, not exposed
```

### 3. Rate Limiting

```nginx
# nginx/conf.d/default.conf
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

location /api/ {
    limit_req zone=api_limit burst=20 nodelay;
    # ...
}
```

### 4. Audit Logging

```python
# backend/app.py
@app.post("/v1/chat/completions")
def chat(...):
    principal = require_auth(authorization)
    
    # Log request with user identity
    logger.info(f"Query by {principal.get('email')} groups={principal.get('groups')}")
    
    # Add to response for audit trail
    data["rag_meta"]["user"] = {
        "email": principal.get("email"),
        "groups": principal.get("groups"),
    }
```

## Migration from v2 to v3

### 1. Add OIDC Configuration

Update `.env` with Keycloak settings.

### 2. Keep API Key as Fallback

v3 supports both OIDC and API key:
```python
# If OIDC not configured, falls back to API key
if OIDC_ENABLED:
    principal = get_principal(authorization)
else:
    require_auth(authorization)  # API key check
```

### 3. Test with Legacy Clients

```bash
# Legacy API key still works if OIDC not configured
curl -X POST "http://localhost:8080/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  ...
```

### 4. Gradual Rollout

1. Deploy v3 with OIDC disabled (no BACKEND_OIDC_ISSUER)
2. Test with API key
3. Configure Keycloak
4. Enable OIDC (set BACKEND_OIDC_ISSUER)
5. Test SSO login
6. Deprecate API key

## Production Checklist

- [ ] Keycloak configured with proper realm/client
- [ ] SSL certificates from trusted CA (not self-signed)
- [ ] DNS records for rag.company.local
- [ ] Cookie secret generated and secured
- [ ] Client secret secured (not in git)
- [ ] Groups/roles mapped in Keycloak
- [ ] Test user login flow
- [ ] Test API token flow
- [ ] Test authorization (group checks)
- [ ] Nginx rate limiting configured
- [ ] Audit logging enabled
- [ ] Monitoring setup (failed logins, token errors)
- [ ] Backup/restore procedure documented
- [ ] Incident response plan

## Advanced Topics

### Multi-Realm Support

```python
# Support multiple Keycloak realms
OIDC_ISSUERS = [
    "https://keycloak.company.local/realms/internal-apps",
    "https://keycloak.company.local/realms/partners",
]

# Verify against multiple issuers
def verify_token_multi_issuer(token):
    for issuer in OIDC_ISSUERS:
        try:
            return jwt.decode(token, jwks, issuer=issuer, ...)
        except:
            continue
    raise HTTPException(401, "Invalid token")
```

### Dynamic Group Sync

```python
# Sync Keycloak groups to local permissions
@app.on_event("startup")
async def sync_groups():
    # Fetch groups from Keycloak Admin API
    # Update local permissions/ACLs
    pass
```

### Custom Claims

```python
# Use custom claims from Keycloak
principal = get_principal(authorization)
department = principal["claims"].get("department")
cost_center = principal["claims"].get("cost_center")

# Filter documents by department
hits = store.search(query, filter={"department": department})
```

## Support

For v3 setup assistance:
- Check Keycloak documentation: https://www.keycloak.org/docs/
- oauth2-proxy docs: https://oauth2-proxy.github.io/oauth2-proxy/
- Open issue in this repo

## License

Internal use only.
