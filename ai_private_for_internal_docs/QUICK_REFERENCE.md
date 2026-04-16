# Quick Reference - HTTPS Commands

## Setup Certificate (First Time)
```bash
./setup-https.sh
```

## Deploy
```bash
./deploy.sh
```

## Manual Commands

### Start/Stop
```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Restart specific service
docker-compose restart nginx
```

### Logs
```bash
# All logs
docker-compose logs -f

# Nginx only
docker-compose logs -f nginx

# Last 100 lines
docker-compose logs --tail=100
```

### Health Checks
```bash
# Backend
curl http://localhost:8080/healthz

# HTTPS
curl -k https://localhost/api/healthz

# vLLM
curl http://localhost:8000/health

# Qdrant
curl http://localhost:6333/healthz
```

### Certificate Management
```bash
# View certificate info
openssl x509 -in certs/fullchain.pem -noout -text

# Check expiration
openssl x509 -in certs/fullchain.pem -noout -enddate

# Verify key matches cert
openssl x509 -noout -modulus -in certs/fullchain.pem | openssl md5
openssl rsa -noout -modulus -in certs/privkey.pem | openssl md5

# Test SSL connection
openssl s_client -connect localhost:443 -servername rag.company.local
```

### Nginx
```bash
# Test config
docker-compose exec nginx nginx -t

# Reload config (no downtime)
docker-compose exec nginx nginx -s reload

# View current config
docker-compose exec nginx cat /etc/nginx/nginx.conf
docker-compose exec nginx cat /etc/nginx/conf.d/default.conf

# Check rate limiting
docker-compose logs nginx | grep "limiting requests"
```

### Testing
```bash
# Test HTTP → HTTPS redirect
curl -I http://localhost/

# Test rate limiting
for i in {1..50}; do curl -k https://localhost/api/healthz & done; wait

# Test with authentication
TOKEN="your-jwt-token"
curl -H "Authorization: Bearer $TOKEN" https://localhost/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"Hello"}]}'
```

### Troubleshooting
```bash
# Check ports in use
sudo netstat -tlnp | grep -E ":(80|443)"

# Check firewall
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Docker stats
docker stats --no-stream

# Disk usage
docker system df
du -sh ./*

# Container inspection
docker-compose exec nginx ls -la /etc/nginx/certs/
docker-compose exec backend env | grep OIDC
```

## Common Issues

### Certificate Error
```bash
# Regenerate self-signed
./setup-https.sh
# Choose option 2

# Or manually
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/privkey.pem -out certs/fullchain.pem \
  -subj "/C=VN/ST=HCM/O=Company/CN=rag.company.local"

docker-compose restart nginx
```

### 502 Bad Gateway
```bash
# Check backend
docker-compose logs backend
docker-compose restart backend

# Check connectivity
docker-compose exec nginx curl http://backend:8080/healthz
```

### Rate Limited (429)
```bash
# Edit nginx/nginx.conf
# Increase rate: 30r/s → 50r/s

# Restart nginx
docker-compose restart nginx
```

### Out of Memory
```bash
# Check memory
docker stats

# Reduce vLLM memory
# Edit docker-compose.yml: add --gpu-memory-utilization 0.8
docker-compose up -d vllm
```

## Quick Deployment Flow

### Development
```bash
# 1. Generate self-signed cert
./setup-https.sh  # Option 2

# 2. Update .env
nano .env

# 3. Deploy
./deploy.sh

# 4. Test
curl -k https://localhost/api/healthz
```

### Production
```bash
# 1. Copy real certificates
./setup-https.sh  # Option 1
# Enter paths to your cert files

# 2. Update .env with real domain
nano .env
# Update: OAUTH2_PROXY_REDIRECT_URL=https://rag.yourcompany.com/oauth2/callback

# 3. Deploy
./deploy.sh

# 4. Test
curl https://rag.yourcompany.com/api/healthz
```

## Files to Backup
```bash
# Essential files
tar czf rag-backup.tar.gz \
  .env \
  certs/ \
  docs/ \
  nginx/
```

## Monitoring
```bash
# Watch logs
watch -n 2 'docker-compose ps'

# Certificate expiry
openssl x509 -in certs/fullchain.pem -noout -enddate

# Nginx access log
docker-compose logs nginx | tail -20

# API usage
docker-compose logs backend | grep "POST /v1/chat/completions"
```
