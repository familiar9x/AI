# HTTPS Architecture Overview

## Network Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                         Internet / Users                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           │ HTTPS (443)
                           ▼
        ┌──────────────────────────────────────┐
        │         Nginx Reverse Proxy          │
        │  ┌────────────────────────────────┐  │
        │  │ • TLS 1.2/1.3 Termination     │  │
        │  │ • HTTP/2 Support               │  │
        │  │ • Security Headers             │  │
        │  │ • Rate Limiting (30r/s)        │  │
        │  │ • Gzip Compression             │  │
        │  │ • HTTP → HTTPS Redirect        │  │
        │  └────────────────────────────────┘  │
        └──────────┬───────────────────────────┘
                   │
        ┌──────────┼──────────────────────┐
        │          │                      │
        ▼          ▼                      ▼
   /oauth2/*    /api/*                  /
        │          │                      │
        ▼          │                      │
┌──────────────┐  │                      │
│ oauth2-proxy │  │                      │
│ ┌──────────┐ │  │                      │
│ │ Keycloak │ │  │                      │
│ │   OIDC   │ │  │                      │
│ │   Auth   │ │  │                      │
│ └────┬─────┘ │  │                      │
└──────┼───────┘  │                      │
       │          │                      │
       │ JWT      │ JWT                  │ JWT
       ▼          ▼                      ▼
    ┌─────────────────────────┐   ┌──────────────┐
    │    Backend API          │   │  OpenWebUI   │
    │  ┌──────────────────┐   │   │              │
    │  │ JWT Verification │   │   │              │
    │  │ Group Filtering  │   │   │              │
    │  └────┬─────────────┘   │   │              │
    └───────┼─────────────────┘   └──────────────┘
            │
    ┌───────┼──────────┐
    │       │          │
    ▼       ▼          ▼
┌────────┐ ┌────┐  ┌──────┐
│Qdrant  │ │vLLM│  │Redis │
│Vector  │ │LLM │  │Cache │
│  DB    │ │    │  │      │
└────────┘ └────┘  └──────┘
```

## Security Layers

```
Layer 1: Network
├── Firewall: Only 443/tcp exposed
├── DDoS: Rate limiting (30r/s API, 10r/s auth)
└── TLS: 1.2/1.3 with modern ciphers

Layer 2: Transport
├── HTTPS: Certificate validation
├── HSTS: Force HTTPS for 1 year
└── HTTP/2: Encrypted multiplexing

Layer 3: Application
├── OAuth2: Keycloak SSO
├── JWT: Token verification
└── Groups: AD-based authorization

Layer 4: API
├── Rate Limit: 30 req/s per IP
├── Timeout: 300s for long operations
└── CORS: Controlled origins

Layer 5: Headers
├── CSP: Content Security Policy
├── X-Frame-Options: SAMEORIGIN
├── X-Content-Type-Options: nosniff
├── X-XSS-Protection: Enabled
└── Referrer-Policy: no-referrer-when-downgrade
```

## Request Flow Example

```
1. User opens https://rag.company.local
   │
   ├─▶ HTTP → HTTPS redirect (if HTTP)
   │
2. Nginx receives HTTPS request
   │
   ├─▶ TLS handshake (TLSv1.3)
   ├─▶ Rate limit check (pass)
   │
3. Nginx checks authentication
   │
   ├─▶ auth_request → /oauth2/auth
   │
4. oauth2-proxy validates session
   │
   ├─▶ No session? → Redirect to Keycloak
   ├─▶ Valid session? → Extract JWT token
   │
5. Keycloak login (if needed)
   │
   ├─▶ User enters AD credentials
   ├─▶ Keycloak validates with LDAP
   ├─▶ Returns JWT with groups
   │
6. oauth2-proxy callback
   │
   ├─▶ Store session cookie
   ├─▶ Redirect back to original URL
   │
7. Nginx forwards to backend
   │
   ├─▶ Set Authorization: Bearer <JWT>
   ├─▶ Set X-Forwarded-Proto: https
   │
8. Backend verifies JWT
   │
   ├─▶ Verify signature with Keycloak JWKS
   ├─▶ Check expiration
   ├─▶ Extract user groups
   │
9. Backend processes request
   │
   ├─▶ Search Qdrant (filtered by groups)
   ├─▶ Generate answer with vLLM
   ├─▶ Return JSON response
   │
10. Nginx returns to client
    │
    ├─▶ Add security headers
    ├─▶ Compress with gzip
    └─▶ Send response
```

## Certificate Flow

```
Development:
┌────────────────┐
│  setup-https.sh│
└───────┬────────┘
        │
        ├─▶ Option 1: Use existing cert
        │   └─▶ Copy to certs/
        │
        └─▶ Option 2: Generate self-signed
            └─▶ openssl req -x509 ...

Production:
┌──────────────────┐
│ Corporate CA     │ or  ┌──────────────┐
│ Certificate      │     │ Let's Encrypt│
└─────────┬────────┘     └──────┬───────┘
          │                     │
          └───────────┬─────────┘
                      ▼
              ┌──────────────┐
              │ certs/       │
              │ ├─fullchain  │
              │ └─privkey    │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ Nginx        │
              │ Mounts certs │
              └──────────────┘
```

## Rate Limiting Logic

```
┌─────────────────────────────────────┐
│ Request from IP 10.0.0.100          │
└─────────────┬───────────────────────┘
              │
              ▼
    ┌──────────────────────┐
    │ Check zone: api_limit│
    │ Rate: 30r/s          │
    │ Burst: 60            │
    └─────────┬────────────┘
              │
    ┌─────────┼─────────────┐
    │         │             │
    ▼         ▼             ▼
  <30r/s   30-60r/s      >60r/s
    │         │             │
    │         │             │
  PASS   PASS (burst)   429 REJECT
    │         │
    └─────┬───┘
          ▼
    ┌──────────────┐
    │ Forward to   │
    │ backend      │
    └──────────────┘
```

## File Organization

```
ai_private_for_internal_docs/
│
├── 🔐 HTTPS Setup
│   ├── certs/                    # SSL certificates
│   │   ├── fullchain.pem         # Certificate chain
│   │   ├── privkey.pem           # Private key
│   │   └── README.md             # Setup guide
│   ├── setup-https.sh            # Interactive setup
│   ├── deploy.sh                 # Quick deployment
│   ├── HTTPS_SETUP.md            # Full documentation
│   └── QUICK_REFERENCE.md        # Command cheatsheet
│
├── 🌐 Nginx Configuration
│   ├── nginx/nginx.conf          # Main config + rate limits
│   └── nginx/conf.d/
│       └── default.conf          # HTTPS server + security
│
├── 🔑 Authentication
│   ├── .env                      # OIDC configuration
│   └── docs/
│       ├── V3_SSO_GUIDE.md       # SSO setup
│       └── KEYCLOAK_SETUP.md     # Keycloak config
│
├── 🐳 Container Stack
│   └── docker-compose.yml        # Full stack definition
│
└── 📚 Documentation
    ├── README.md                 # Main guide
    ├── CHANGELOG_HTTPS.md        # This version changes
    └── docs/
        ├── DEPLOYMENT_RUNBOOK.md # Production deployment
        ├── V2_UPGRADE_GUIDE.md   # v1→v2 upgrade
        └── OCR_GUIDE.md          # OCR configuration
```

## Component Communication

```
┌────────────────────────────────────────────────────────────┐
│                    Docker Network: app-network              │
│                                                             │
│  nginx:443 ◄─┐                                             │
│              │                                              │
│              ├─▶ oauth2-proxy:4180                         │
│              │                                              │
│              ├─▶ openwebui:8080                            │
│              │                                              │
│              └─▶ backend:8080 ◄─┬─▶ qdrant:6333           │
│                                  │                          │
│                                  ├─▶ vllm:8000             │
│                                  │                          │
│                                  └─▶ redis:6379            │
│                                                             │
└────────────────────────────────────────────────────────────┘

External:
  Keycloak OIDC Server (keycloak.company.local)
```

## Performance Characteristics

```
┌─────────────────────────┬──────────────┬────────────────┐
│ Component               │ Latency      │ Bottleneck     │
├─────────────────────────┼──────────────┼────────────────┤
│ TLS Handshake           │ 1-2ms        │ CPU            │
│ HTTPS Request           │ <1ms         │ Network        │
│ Rate Limit Check        │ <0.1ms       │ Memory         │
│ OAuth2 Auth Check       │ 1-5ms        │ Redis/Session  │
│ JWT Verification        │ 1-3ms        │ CPU            │
│ Qdrant Search           │ 10-50ms      │ Vector DB      │
│ vLLM Generation         │ 500-2000ms   │ GPU            │
│ Total (cache hit)       │ 10-20ms      │ -              │
│ Total (LLM needed)      │ 600-2100ms   │ LLM Generation │
└─────────────────────────┴──────────────┴────────────────┘
```

## Deployment Workflow

```
1. Prepare
   ├─▶ ./setup-https.sh
   │   └─▶ Install certificates
   │
   ├─▶ Edit .env
   │   ├─▶ OIDC config
   │   └─▶ Domain settings
   │
   └─▶ DNS/hosts setup

2. Deploy
   └─▶ ./deploy.sh
       ├─▶ docker-compose build
       ├─▶ docker-compose up -d
       └─▶ Health checks

3. Verify
   ├─▶ HTTPS working
   ├─▶ Certificate valid
   ├─▶ Security headers present
   ├─▶ Rate limiting active
   ├─▶ SSO login works
   └─▶ API accessible

4. Monitor
   ├─▶ docker-compose logs -f
   ├─▶ Certificate expiry
   ├─▶ Rate limit events
   └─▶ Error logs
```

---

**Legend:**
- 🔐 Security-related
- 🌐 Network/proxy
- 🔑 Authentication
- 🐳 Container infrastructure
- 📚 Documentation
