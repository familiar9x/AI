#!/bin/bash
# Setup HTTPS certificates for Private RAG

set -e

CERT_DIR="./certs"
DOMAIN="rag.company.local"

echo "=== Private RAG HTTPS Certificate Setup ==="
echo ""

# Check if certificates already exist
if [ -f "$CERT_DIR/fullchain.pem" ] && [ -f "$CERT_DIR/privkey.pem" ]; then
    echo "✓ Certificates already exist in $CERT_DIR/"
    echo ""
    echo "Certificate details:"
    openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -subject -issuer -dates
    echo ""
    read -p "Do you want to replace them? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing certificates."
        exit 0
    fi
fi

echo "Select certificate option:"
echo "1) Use existing certificate files (recommended for production)"
echo "2) Generate self-signed certificate (development only)"
echo ""
read -p "Enter option (1 or 2): " option

case $option in
    1)
        echo ""
        echo "Please provide paths to your certificate files:"
        echo ""
        read -p "Path to certificate file (fullchain.pem or .crt): " cert_file
        read -p "Path to private key file (privkey.pem or .key): " key_file
        
        if [ ! -f "$cert_file" ]; then
            echo "Error: Certificate file not found: $cert_file"
            exit 1
        fi
        
        if [ ! -f "$key_file" ]; then
            echo "Error: Private key file not found: $key_file"
            exit 1
        fi
        
        # Verify certificate
        echo ""
        echo "Verifying certificate..."
        if ! openssl x509 -in "$cert_file" -noout -text > /dev/null 2>&1; then
            echo "Error: Invalid certificate file"
            exit 1
        fi
        
        if ! openssl rsa -in "$key_file" -check -noout > /dev/null 2>&1; then
            echo "Error: Invalid private key file"
            exit 1
        fi
        
        # Check if key matches certificate
        cert_modulus=$(openssl x509 -noout -modulus -in "$cert_file" | openssl md5)
        key_modulus=$(openssl rsa -noout -modulus -in "$key_file" | openssl md5)
        
        if [ "$cert_modulus" != "$key_modulus" ]; then
            echo "Error: Private key does not match certificate"
            exit 1
        fi
        
        echo "✓ Certificate and key are valid and match"
        echo ""
        
        # Copy files
        mkdir -p "$CERT_DIR"
        cp "$cert_file" "$CERT_DIR/fullchain.pem"
        cp "$key_file" "$CERT_DIR/privkey.pem"
        
        chmod 644 "$CERT_DIR/fullchain.pem"
        chmod 600 "$CERT_DIR/privkey.pem"
        
        echo "✓ Certificates copied to $CERT_DIR/"
        ;;
        
    2)
        echo ""
        echo "⚠️  WARNING: Self-signed certificates are for DEVELOPMENT ONLY"
        echo "   Browsers will show security warnings"
        echo ""
        read -p "Continue? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Cancelled."
            exit 0
        fi
        
        read -p "Enter domain name [$DOMAIN]: " input_domain
        DOMAIN=${input_domain:-$DOMAIN}
        
        echo ""
        echo "Generating self-signed certificate for $DOMAIN..."
        mkdir -p "$CERT_DIR"
        
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$CERT_DIR/privkey.pem" \
            -out "$CERT_DIR/fullchain.pem" \
            -subj "/C=VN/ST=HCM/L=HCMC/O=Company/CN=$DOMAIN"
        
        chmod 644 "$CERT_DIR/fullchain.pem"
        chmod 600 "$CERT_DIR/privkey.pem"
        
        echo "✓ Self-signed certificate generated"
        ;;
        
    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo ""
echo "=== Certificate Information ==="
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -text | grep -A2 "Subject:"
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -text | grep -A2 "Validity"
echo ""

echo "=== Next Steps ==="
echo "1. Update your domain in .env file:"
echo "   OAUTH2_PROXY_REDIRECT_URL=https://$DOMAIN/oauth2/callback"
echo ""
echo "2. Start the services:"
echo "   docker-compose up -d"
echo ""
echo "3. Access your RAG system:"
echo "   https://$DOMAIN"
echo ""
echo "4. Test HTTPS:"
echo "   curl -k https://localhost/api/healthz"
echo "   openssl s_client -connect localhost:443 -servername $DOMAIN"
echo ""
