# 🚀 Quick Start - Cache System v2

## Cài đặt nhanh (5 phút)

### Bước 1: Cập nhật .env

```bash
# Thêm vào file .env
echo "REDIS_URL=redis://redis:6379/0" >> .env
echo "DEFAULT_CACHE_TTL_DAYS=30" >> .env
echo "BAD_MARK_TTL_DAYS=365" >> .env
```

### Bước 2: Deploy

```bash
# Rebuild backend với dependencies mới (redis)
docker-compose build backend

# Start tất cả services
docker-compose up -d

# Kiểm tra services
docker-compose ps
```

### Bước 3: Verify

```bash
# Test health check
curl http://localhost:8080/healthz

# Kết quả mong đợi:
# {"ok": true, "redis": true}
```

---

## 🎯 Test nhanh

### Test 1: Cache Hit/Miss

```bash
# Request đầu tiên - cache MISS
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Quy trình nghỉ phép là gì?"}
    ]
  }' | jq '.rag_meta.cache'

# Output: {"hit": false, "bypassed": false}
# Latency: ~1-3 giây

# Request thứ hai - cache HIT  
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Quy trình nghỉ phép là gì?"}
    ]
  }' | jq '.rag_meta.cache'

# Output: {"hit": true, "bypassed": false}
# Latency: ~10-50ms (nhanh hơn 20-100x!)
```

### Test 2: Feedback Flow

```bash
# Lấy request_id từ response trên
REQUEST_ID="abc123"  # Thay bằng request_id thật

# Mở feedback UI trong browser
open "http://localhost:8080/feedback/ui?request_id=$REQUEST_ID"

# Hoặc dùng API
curl -X POST http://localhost:8080/feedback/bad \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"request_id\": \"$REQUEST_ID\",
    \"reason\": \"Thông tin không chính xác\"
  }"

# Output: 
# {
#   "ok": true,
#   "message": "Đã ghi nhận phản hồi. Lần sau sẽ không dùng cache và gọi AI lại."
# }
```

### Test 3: Bypass sau feedback

```bash
# Hỏi lại câu hỏi vừa report bad
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Quy trình nghỉ phép là gì?"}
    ]
  }' | jq '.rag_meta.cache'

# Output: {"hit": false, "bypassed": true}
# System đã bypass cache và gọi LLM lại!
```

---

## 🔍 Monitoring

### Redis CLI

```bash
# Vào Redis CLI
docker exec -it redis redis-cli

# Check corpus version
GET corpus_version

# List all answer caches
KEYS ans:*

# List all bad marks
KEYS bad:*

# List recent requests (expire sau 1h)
KEYS recent:*

# Total keys
DBSIZE

# Memory usage
INFO memory
```

### Admin API

```bash
# Cache statistics (cần admin token)
curl http://localhost:8080/admin/cache/stats \
  -H "Authorization: Bearer ADMIN_TOKEN"

# Output:
# {
#   "corpus_version": 1,
#   "redis": {
#     "used_memory_human": "1.2M",
#     "total_keys": 150,
#     "uptime_in_days": 5
#   }
# }
```

---

## 🎨 Frontend Integration

### Response có feedback_url

```javascript
// Gọi API
const response = await fetch('/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ' + token,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    messages: [{role: 'user', content: question}]
  })
});

const data = await response.json();

// Lấy feedback URL
const feedbackUrl = data.rag_meta.feedback_url;
// → "/feedback/ui?request_id=abc123"

// Hiển thị link cho user
console.log('Feedback URL:', feedbackUrl);
```

### Show feedback link

```html
<!-- HTML Example -->
<div class="answer-footer">
  <a href="${feedbackUrl}" target="_blank" class="feedback-link">
    ❌ Không hài lòng với câu trả lời này?
  </a>
</div>
```

```javascript
// React Example
function Answer({ data }) {
  return (
    <div>
      <div>{data.choices[0].message.content}</div>
      {data.rag_meta?.feedback_url && (
        <a 
          href={data.rag_meta.feedback_url}
          target="_blank"
          className="text-red-500 hover:underline"
        >
          ❌ Không hài lòng với câu trả lời này?
        </a>
      )}
    </div>
  );
}
```

---

## 🔧 Troubleshooting

### Redis không connect được?

```bash
# Check Redis running
docker ps | grep redis

# Check Redis logs
docker logs redis

# Test connection
docker exec -it redis redis-cli ping
# Should return: PONG

# Check REDIS_URL in backend
docker exec -it rag-backend env | grep REDIS
```

### Cache không hoạt động?

```bash
# Check backend logs
docker logs rag-backend --tail 50

# Test healthz endpoint
curl http://localhost:8080/healthz
# Should return: {"ok": true, "redis": true}

# Check if cache functions work
docker exec -it redis redis-cli
> SET test_key "test_value"
> GET test_key
> DEL test_key
```

### Feedback không work?

```bash
# Recent key có tồn tại không? (chỉ giữ 1h)
docker exec -it redis redis-cli
> KEYS recent:*
> GET recent:abc123

# Nếu không có → request_id đã expire
# User phải feedback trong vòng 1 giờ sau khi nhận response
```

---

## 📊 Expected Performance

| Metric | Before Cache | With Cache |
|--------|-------------|------------|
| **Latency** | 1-3s | 10-50ms |
| **LLM Calls** | 100% | 20-40% |
| **Cost** | Baseline | -60-80% |
| **User Satisfaction** | N/A | Feedback loop |

---

## ✅ Checklist

- [ ] .env có `REDIS_URL`
- [ ] Redis service running (`docker ps | grep redis`)
- [ ] Backend rebuilt với redis dependency
- [ ] `/healthz` returns `redis: true`
- [ ] Test cache hit/miss works
- [ ] Feedback UI accessible
- [ ] POST /feedback/bad works
- [ ] Bypass after feedback works

---

## 📚 Đọc thêm

- [CACHE_GUIDE.md](docs/CACHE_GUIDE.md) - Hướng dẫn chi tiết
- [CACHE_IMPLEMENTATION.md](CACHE_IMPLEMENTATION.md) - Technical summary
- [.env.cache.example](.env.cache.example) - Config template

---

## 🎉 Done!

Cache system v2 đã sẵn sàng. Features:

✅ Automatic caching (30 days)  
✅ User feedback UI  
✅ Bad answer bypass  
✅ Group-based isolation  
✅ Auto corpus invalidation  

Enjoy! 🚀
