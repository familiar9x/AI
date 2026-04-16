# 🎉 Admin UI + Cache v3 Implementation Summary

## ✅ What's New

Complete Admin UI và enhanced cache system với user feedback đã được triển khai!

---

## 📦 New Features

### 1. **Admin UI** (`/api/admin/ui`)
- 📊 Dashboard để quản lý cache system
- 👀 View all cached answers và bad marks
- 🗑️ Delete specific cache entries
- 🔄 Bump corpus version để invalidate all caches
- 🔍 View detailed JSON payloads
- 🔐 Protected by AD group (`RAG-ADMINS`)

### 2. **User Feedback UI** (`/api/feedback/ui`)
- 📝 Simple form để users report bad answers
- ✅ HTML form với textarea cho reason
- 🔗 Auto-included trong mỗi response (`rag_meta.feedback_url`)
- 🚫 Mark bad → bypass cache cho câu hỏi đó

### 3. **Enhanced Cache Module**
- 🎯 Admin helper functions: `scan_keys()`, `key_ttl()`, `parse_cache_key()`
- 💾 Extended recent tracking với principal info
- 🔧 `delete_bad()` function cho admin clear
- 📊 Comprehensive `cache_stats()` endpoint

---

## 🗂️ Files Changed/Created

### Modified Files

1. **backend/requirements.txt**
   - Updated: `redis==5.0.8`

2. **backend/cache.py**
   - Added admin helpers: `scan_keys()`, `key_ttl()`, `get_json()`, `delete_key()`, `parse_cache_key()`
   - Added `delete_bad()` for admin clearing
   - Extended `recent_set()` to store principal info
   - Improved `groups_hash()` with cleaning

3. **backend/app.py**
   - Added imports: `Request`, all cache admin functions
   - Updated `chat_completions()` với `/api/` prefix cho feedback_url
   - Enhanced `recent_set()` với principal_sub, principal_email
   - Replaced feedback endpoints với HTML form handling
   - **NEW**: Admin UI endpoints:
     - `GET /admin/ui` - Main dashboard
     - `GET /admin/view` - View key details
     - `GET /admin/delete` - Delete key
     - `POST /admin/bump` - Bump corpus version
   - Added `require_admin()` helper

4. **.env.cache.example**
   - Added: `ADMIN_GROUP=RAG-ADMINS`

### New Documentation Files

5. **docs/ADMIN_UI_GUIDE.md** (NEW)
   - Complete guide cho admin UI usage
   - Common tasks walkthrough
   - Security documentation
   - Troubleshooting guide

6. **ADMIN_CACHE_V3_SUMMARY.md** (this file)
   - Quick reference cho new features

---

## 🔑 Environment Variables

Add to your `.env`:

```bash
# Cache configuration
REDIS_URL=redis://redis:6379/0
DEFAULT_CACHE_TTL_DAYS=30
BAD_MARK_TTL_DAYS=365

# Admin access control
ADMIN_GROUP=RAG-ADMINS
```

---

## 🚀 Deployment

```bash
# 1. Update .env with new variables
cat >> .env << EOF
ADMIN_GROUP=RAG-ADMINS
EOF

# 2. Rebuild backend (new redis version + code changes)
docker-compose build backend

# 3. Restart services
docker-compose up -d

# 4. Verify
curl https://rag.company.local/api/admin/ui
# Should redirect to SSO login, then show admin dashboard
```

---

## 📡 New API Endpoints

### Admin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/ui` | GET | Main admin dashboard (HTML) |
| `/api/admin/view?key=<key>` | GET | View Redis key details (HTML) |
| `/api/admin/delete?key=<key>` | GET | Delete Redis key (HTML) |
| `/api/admin/bump` | POST | Bump corpus version (HTML) |
| `/api/admin/cache/stats` | GET | Get cache stats (JSON) |

### User Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/feedback/ui?request_id=<id>` | GET | Feedback form (HTML) |
| `/api/feedback/bad` | POST | Submit bad feedback (form data) |

---

## 🎯 User Flow

### Normal Query
```
1. User asks question via OpenWebUI
2. Backend checks cache
3. Response includes feedback_url
4. OpenWebUI can show "Không hài lòng?" link
```

### Feedback Flow
```
1. User clicks feedback_url
2. Opens /api/feedback/ui form
3. User fills reason (optional)
4. Submits → marks bad + deletes cache
5. Next query bypasses cache
```

### Admin Review Flow
```
1. Admin goes to /api/admin/ui
2. Views "Bad marks" section
3. Clicks "view" on bad key
4. Reviews reason & timestamp
5. Decides: keep or delete bad mark
```

---

## 🔐 Access Control

### Admin UI Access
- **Required:** User in `RAG-ADMINS` AD group
- **Flow:** 
  1. Nginx → oauth2-proxy (SSO)
  2. oauth2-proxy validates Keycloak session
  3. Forwards to backend with JWT
  4. Backend validates JWT + checks groups claim
  5. If `RAG-ADMINS` in groups → allow access
  6. Else → 403 Forbidden

### Regular User Access
- Any authenticated user can use chat API
- Group-based document filtering in RAG search
- Can submit feedback for their own queries only

---

## 📊 Cache Key Structure

```
ans:<version>:<groups_hash>:<question_hash>
bad:<version>:<groups_hash>:<question_hash>
recent:<request_id>
corpus_version
```

### Example
```
Question: "Quy trình nghỉ phép?"
Groups: ["HR-STAFF", "EMPLOYEES"]
Version: 1

Answer key:
ans:1:a1b2c3d4e5f6g7h8:x1y2z3w4v5u6t7s8
     └ version
        └ groups_hash (sorted groups SHA1)
                         └ question_hash (normalized question SHA1)
```

---

## 🧪 Testing

### Test Admin Access

```bash
# Test as regular user (should fail)
curl https://rag.company.local/api/admin/ui \
  -H "Cookie: _oauth2_proxy=<user_cookie>"
# → 403 Forbidden

# Test as admin (should succeed)
curl https://rag.company.local/api/admin/ui \
  -H "Cookie: _oauth2_proxy=<admin_cookie>"
# → HTML dashboard
```

### Test Feedback Flow

```bash
# 1. Ask question, get request_id
RESPONSE=$(curl -X POST https://rag.company.local/api/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"messages":[{"role":"user","content":"test"}]}')

REQUEST_ID=$(echo $RESPONSE | jq -r '.rag_meta.request_id')
FEEDBACK_URL=$(echo $RESPONSE | jq -r '.rag_meta.feedback_url')

# 2. Open feedback UI
open "https://rag.company.local$FEEDBACK_URL"

# 3. Submit feedback (or via curl)
curl -X POST https://rag.company.local/api/feedback/bad \
  -H "Cookie: _oauth2_proxy=<cookie>" \
  -d "request_id=$REQUEST_ID&reason=Wrong+info"

# 4. Ask same question again - should bypass cache
curl -X POST https://rag.company.local/api/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"messages":[{"role":"user","content":"test"}]}' \
  | jq '.rag_meta.cache'
# → {"hit": false, "bypassed": true}
```

### Test Admin Functions

```bash
# View all bad marks
open "https://rag.company.local/api/admin/ui"

# Bump corpus version
curl -X POST https://rag.company.local/api/admin/bump \
  -H "Cookie: _oauth2_proxy=<admin_cookie>"

# Check new version
curl https://rag.company.local/api/admin/cache/stats \
  -H "Cookie: _oauth2_proxy=<admin_cookie>" \
  | jq .corpus_version
```

---

## 🎨 UI Features

### Admin Dashboard
- **Clean design** with proper styling
- **Color-coded** sections
- **Clickable links** for all actions
- **Tooltips** and warnings
- **Responsive** layout

### Feedback Form
- **Simple textarea** for reason
- **Warning message** about cache invalidation
- **Clear action button**
- **Confirmation page** after submit

### View Key Page
- **JSON syntax highlighting** (via pre formatting)
- **Key structure parser** showing components
- **TTL display** in human-readable format
- **Back navigation** links

---

## 📚 Documentation

| File | Description |
|------|-------------|
| [docs/ADMIN_UI_GUIDE.md](docs/ADMIN_UI_GUIDE.md) | Complete admin UI manual |
| [docs/CACHE_GUIDE.md](docs/CACHE_GUIDE.md) | Cache system guide |
| [CACHE_IMPLEMENTATION.md](CACHE_IMPLEMENTATION.md) | Technical implementation details |
| [QUICKSTART_CACHE.md](QUICKSTART_CACHE.md) | Quick start guide |

---

## ✨ Benefits

### For Admins
✅ **Visibility** - See all cached data and bad marks  
✅ **Control** - Delete/clear caches manually  
✅ **Efficiency** - Bulk invalidation via version bump  
✅ **Insights** - Review user feedback reasons  

### For Users
✅ **Easy feedback** - Simple HTML form  
✅ **Automatic** - Feedback URL in every response  
✅ **Effective** - Bad answers won't be cached again  
✅ **Transparent** - Clear messaging about actions  

### For System
✅ **Smart caching** - Avoid serving bad answers  
✅ **Quality improvement** - User feedback loop  
✅ **Version control** - Corpus version tracking  
✅ **Scope isolation** - Group-based cache keys  

---

## 🚦 Status

**Current Version:** v3 with Admin UI  
**Redis Version:** 5.0.8  
**Status:** ✅ Production Ready  

**Components:**
- ✅ Cache module with admin helpers
- ✅ Feedback UI with form handling
- ✅ Admin UI dashboard
- ✅ Authentication & authorization
- ✅ Documentation complete

---

## 🎯 Next Steps (Optional)

Future enhancements could include:

- [ ] Admin analytics dashboard (cache hit rate, feedback trends)
- [ ] Batch operations (delete multiple keys)
- [ ] Export feedback data for analysis
- [ ] Admin override/edit cached answers
- [ ] Search/filter keys by pattern
- [ ] Approved cache tier (manually reviewed answers)

---

## 🆘 Support

### Quick Links
- Admin UI: `https://rag.company.local/api/admin/ui`
- Health check: `https://rag.company.local/api/healthz`
- Cache stats: `https://rag.company.local/api/admin/cache/stats`

### Troubleshooting
See [docs/ADMIN_UI_GUIDE.md](docs/ADMIN_UI_GUIDE.md) section "🚨 Troubleshooting"

### Redis CLI
```bash
docker exec -it redis redis-cli
```

---

## 🎉 Summary

Admin UI v3 is complete and ready to use!

**Access:** `https://rag.company.local/api/admin/ui`  
**Requires:** `RAG-ADMINS` group membership  
**Features:** View, delete, bump, review  

Simple. Powerful. Secure. 🚀
