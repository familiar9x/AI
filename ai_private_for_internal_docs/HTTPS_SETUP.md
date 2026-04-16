# HTTPS Setup Guide - Private RAG

## Tổng quan

Hệ thống đã được cấu hình sẵn HTTPS với:
- ✅ TLS 1.2/1.3 với cipher suite hiện đại
- ✅ HTTP/2 support
- ✅ Security headers (HSTS, CSP, X-Frame-Options, etc.)
- ✅ Rate limiting (API: 30r/s, Auth: 10r/s)
- ✅ HTTP → HTTPS redirect tự động
- ✅ WebSocket support cho OpenWebUI

## Bước 1: Chuẩn bị Certificate

### Option 1: Dùng certificate có sẵn (Production)

```bash
# Chạy script setup
./setup-https.sh

# Chọn option 1, nhập đường dẫn đến:
# - Certificate file (fullchain.pem hoặc .crt)
# - Private key file (privkey.pem hoặc .key)
```

Script sẽ tự động:
- Verify certificate hợp lệ
- Kiểm tra key khớp với cert
- Copy vào thư mục `certs/`
- Set đúng permissions (644 cho cert, 600 cho key)

### Option 2: Generate self-signed (Development only)

```bash
./setup-https.sh
# Chọn option 2
# ⚠️ Chỉ dùng cho testing, browser sẽ cảnh báo
```

### Manual setup

Nếu không muốn dùng script:

```bash
# Copy certificate files
cp /path/to/your/fullchain.pem ./certs/
cp /path/to/your/privkey.pem ./certs/

# Set permissions
chmod 644 ./certs/fullchain.pem
chmod 600 ./certs/privkey.pem

# Verify
openssl x509 -in ./certs/fullchain.pem -noout -text
```

## Bước 2: Cấu hình Domain

Update file `.env`:

```bash
# Thay thế domain của bạn
OAUTH2_PROXY_REDIRECT_URL=https://rag.yourcompany.com/oauth2/callback

# Nếu dùng domain khác với rag.company.local
```

**Quan trọng**: Domain trong certificate phải match với domain bạn dùng!

## Bước 3: DNS/Hosts

### Production
Add DNS record:
```
rag.yourcompany.com  A  10.0.0.100
```

### Development
Edit `/etc/hosts`:
```bash
sudo nano /etc/hosts

# Add:
127.0.0.1  rag.company.local
```

## Bước 4: Deploy

```bash
# Build và start
docker-compose up -d --build

# Check logs
docker-compose logs -f nginx

# Verify all services running
docker-compose ps
```

Expected output:
```
NAME            STATUS          PORTS
rag-nginx       Up             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
oauth2-proxy    Up             4180/tcp
openwebui       Up             3000/tcp
rag-backend     Up             8080/tcp
vllm            Up             8000/tcp
qdrant          Up             6333/tcp
redis           Up             6379/tcp
```

## Bước 5: Test

### Test HTTPS
```bash
# Basic health check
curl -k https://localhost/api/healthz

# Full HTTPS test
curl -v https://rag.company.local/api/healthz

# Check certificate
openssl s_client -connect localhost:443 -servername rag.company.local
```

### Test HTTP redirect
```bash
curl -I http://rag.company.local
# Should return: 301 Moved Permanently
# Location: https://rag.company.local/
```

### Test rate limiting
```bash
# Should get 429 after ~30 requests/second
for i in {1..50}; do 
  curl -k https://localhost/api/healthz &
done
wait
```

### Test browser
```
1. Open: https://rag.company.local
2. Should redirect to Keycloak login
3. Login with your AD credentials
4. Should load OpenWebUI interface
```

## Security Headers Check

Verify headers với browser DevTools hoặc:

```bash
curl -I -k https://localhost/

# Should see:
# Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
# X-Content-Type-Options: nosniff
# X-Frame-Options: SAMEORIGIN
# X-XSS-Protection: 1; mode=block
# Referrer-Policy: no-referrer-when-downgrade
# Content-Security-Policy: ...
```

## Troubleshooting

### 1. "NET::ERR_CERT_INVALID"

**Self-signed certificate**:
- Chrome/Edge: Type `thisisunsafe` on the warning page
- Firefox: Click "Advanced" → "Accept the Risk"

**Production certificate**:
- Check certificate CN/SAN matches domain
- Verify certificate chain is complete
- Check certificate not expired

```bash
openssl x509 -in certs/fullchain.pem -noout -text | grep -A1 "Subject Alternative Name"
openssl x509 -in certs/fullchain.pem -noout -dates
```

### 2. "502 Bad Gateway"

Backend chưa start:
```bash
docker-compose logs backend
docker-compose restart backend
```

### 3. "Connection Refused"

Nginx chưa start hoặc port bị block:
```bash
docker-compose logs nginx

# Check ports
sudo netstat -tlnp | grep -E ":(80|443)"

# Firewall
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

### 4. "Private key does not match certificate"

Certificate và key không khớp:
```bash
# Check modulus
openssl x509 -noout -modulus -in certs/fullchain.pem | openssl md5
openssl rsa -noout -modulus -in certs/privkey.pem | openssl md5
# Both should output same MD5
```

### 5. Nginx config error

Test config:
```bash
docker-compose exec nginx nginx -t

# If error, check logs:
docker-compose logs nginx

# Common issues:
# - Missing semicolon
# - Duplicate directives
# - Certificate file not found
```

### 6. Rate limit too strict

Edit [nginx/nginx.conf](nginx/nginx.conf):
```nginx
# Increase rate limit
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=50r/s;  # was 30r/s
```

Then reload:
```bash
docker-compose restart nginx
```

## Monitoring

### SSL Certificate Expiration

Setup cron job:
```bash
cat > check-cert-expiry.sh <<'EOF'
#!/bin/bash
DAYS_LEFT=$(openssl x509 -in /opt/rag/certs/fullchain.pem -noout -enddate | cut -d= -f2 | xargs -I{} date -d "{}" +%s | xargs -I{} echo $(( ({} - $(date +%s)) / 86400 )))

if [ $DAYS_LEFT -lt 30 ]; then
    echo "⚠️ SSL cert expires in $DAYS_LEFT days!" | mail -s "RAG SSL Alert" admin@company.com
fi
EOF

chmod +x check-cert-expiry.sh

# Run weekly
crontab -e
0 9 * * 1 /opt/rag/check-cert-expiry.sh
```

### Nginx Access Logs

```bash
# Follow logs
docker-compose logs -f nginx

# Rate limit events
docker-compose logs nginx | grep "limiting requests"

# SSL errors
docker-compose logs nginx | grep -i ssl
```

### Performance

```bash
# Test TLS handshake speed
openssl s_time -connect localhost:443 -www /api/healthz -new

# Check concurrent connections
docker-compose exec nginx netstat -an | grep :443 | wc -l
```

## Renew Certificate

### Corporate CA
```bash
# Get new cert from CA
# Copy to certs/
cp /path/to/new/fullchain.pem ./certs/
cp /path/to/new/privkey.pem ./certs/

# Reload nginx
docker-compose restart nginx
```

### Let's Encrypt (if using)
```bash
certbot renew
cp /etc/letsencrypt/live/rag.company.com/fullchain.pem ./certs/
cp /etc/letsencrypt/live/rag.company.com/privkey.pem ./certs/
docker-compose restart nginx
```

## Production Checklist

- [ ] Real SSL certificate installed (not self-signed)
- [ ] Certificate CN/SAN matches domain
- [ ] DNS record points to server
- [ ] Firewall allows 443/tcp
- [ ] HTTP redirects to HTTPS
- [ ] Security headers present
- [ ] Rate limiting configured
- [ ] Certificate expiry monitoring setup
- [ ] Backup certificates stored securely
- [ ] .env updated with correct domain

## Files Structure

```
ai_private_for_internal_docs/
├── certs/
│   ├── fullchain.pem          # ← Your certificate here
│   ├── privkey.pem            # ← Your private key here
│   └── README.md
├── nginx/
│   ├── nginx.conf             # Main nginx config with rate limits
│   └── conf.d/
│       └── default.conf       # HTTPS server block
├── docker-compose.yml          # Mounts certs volume
├── setup-https.sh             # Certificate setup script
└── HTTPS_SETUP.md             # This file
```

## Support

- Certificate issues: Check `openssl` commands in this guide
- Nginx errors: `docker-compose logs nginx`
- Rate limiting: Adjust `nginx/nginx.conf`
- Security headers: Modify `nginx/conf.d/default.conf`
