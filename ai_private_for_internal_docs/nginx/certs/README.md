# SSL Certificates

Place your SSL certificates here:

```
nginx/certs/
  fullchain.pem  # Full certificate chain
  privkey.pem    # Private key
```

## Generate Self-Signed Certificates (Development Only)

```bash
cd nginx/certs

# Generate self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/C=VN/ST=HCM/L=HCMC/O=Company/CN=rag.company.local"
```

## Production Certificates

Use Let's Encrypt or your corporate CA:

```bash
# Let's Encrypt (example)
certbot certonly --standalone -d rag.company.local
cp /etc/letsencrypt/live/rag.company.local/fullchain.pem nginx/certs/
cp /etc/letsencrypt/live/rag.company.local/privkey.pem nginx/certs/
```

## Permissions

```bash
chmod 600 nginx/certs/privkey.pem
chmod 644 nginx/certs/fullchain.pem
```

## DNS Setup

Add to your DNS or `/etc/hosts`:

```
10.0.0.100  rag.company.local
```
