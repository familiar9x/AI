# SSL Certificates

## Required Files

Place your SSL certificate files here:

```
certs/
  ├── fullchain.pem    # Full certificate chain (certificate + intermediate CA)
  ├── privkey.pem      # Private key
  └── README.md        # This file
```

## Certificate Formats

### If you have `.pem` files:
```bash
cp /path/to/your/fullchain.pem ./fullchain.pem
cp /path/to/your/privkey.pem ./privkey.pem
chmod 644 fullchain.pem
chmod 600 privkey.pem
```

### If you have `.crt` and `.key` files:
```bash
# Copy and rename
cp /path/to/your/certificate.crt ./fullchain.pem
cp /path/to/your/private.key ./privkey.pem
chmod 644 fullchain.pem
chmod 600 privkey.pem
```

### If you have separate certificate and CA chain:
```bash
# Combine into fullchain
cat certificate.crt intermediate.crt > fullchain.pem
cp private.key privkey.pem
chmod 644 fullchain.pem
chmod 600 privkey.pem
```

## Generate Self-Signed Certificate (Development Only)

For testing/development purposes:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/C=VN/ST=HCM/L=HCMC/O=Company/CN=rag.company.local"

chmod 644 fullchain.pem
chmod 600 privkey.pem
```

**Warning**: Self-signed certificates will show browser warnings. Use real certificates for production.

## Verify Certificate

```bash
# Check certificate expiration
openssl x509 -in fullchain.pem -noout -enddate

# Check certificate details
openssl x509 -in fullchain.pem -noout -text

# Verify private key matches certificate
openssl x509 -noout -modulus -in fullchain.pem | openssl md5
openssl rsa -noout -modulus -in privkey.pem | openssl md5
# Both MD5 hashes should match
```

## After Adding Certificates

Restart the nginx container:

```bash
docker-compose restart nginx
```

Or restart the entire stack:

```bash
docker-compose down
docker-compose up -d
```

## Troubleshooting

### "No such file or directory" error
- Make sure files are named exactly `fullchain.pem` and `privkey.pem`
- Check file permissions (644 for cert, 600 for key)

### "Permission denied" error
```bash
sudo chown $USER:$USER fullchain.pem privkey.pem
chmod 644 fullchain.pem
chmod 600 privkey.pem
```

### Browser shows "Certificate Invalid"
- Verify certificate CN/SAN matches your domain
- Check certificate has not expired
- Make sure fullchain includes intermediate CA certificates

### Test HTTPS
```bash
curl -k https://localhost/api/healthz
openssl s_client -connect localhost:443 -servername rag.company.local
```
