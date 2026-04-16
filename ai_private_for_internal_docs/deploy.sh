#!/bin/bash
# Quick deploy script for Private RAG with HTTPS

set -e

echo "=== Private RAG HTTPS Quick Deploy ==="
echo ""

# Check if certificates exist
if [ ! -f "./certs/fullchain.pem" ] || [ ! -f "./certs/privkey.pem" ]; then
    echo "❌ Certificates not found!"
    echo ""
    echo "Run setup script first:"
    echo "  ./setup-https.sh"
    echo ""
    exit 1
fi

echo "✓ Certificates found"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo ""
    echo "Copy from example:"
    echo "  cp .env.example .env"
    echo "  nano .env  # Update OIDC settings"
    echo ""
    exit 1
fi

echo "✓ .env file found"

# Check docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not installed"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not installed"
    exit 1
fi

echo "✓ Docker and Docker Compose installed"
echo ""

# Show certificate info
echo "Certificate details:"
openssl x509 -in ./certs/fullchain.pem -noout -subject -issuer -dates
echo ""

# Ask to continue
read -p "Continue with deployment? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "=== Building and starting services ==="
echo ""

# Build
echo "Building images..."
docker-compose build

# Start
echo ""
echo "Starting services..."
docker-compose up -d

# Wait for services
echo ""
echo "Waiting for services to start..."
sleep 10

# Check status
echo ""
echo "=== Service Status ==="
docker-compose ps

# Health checks
echo ""
echo "=== Health Checks ==="

# Backend
echo -n "Backend: "
if curl -sf http://localhost:8080/healthz > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "❌ FAILED"
fi

# HTTPS
echo -n "HTTPS: "
if curl -sf -k https://localhost/api/healthz > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "❌ FAILED"
fi

# vLLM (may take time to start)
echo -n "vLLM: "
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "⏳ Starting (may take 2-5 minutes)"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Access your RAG system:"
echo "  https://rag.company.local"
echo ""
echo "Or with IP:"
echo "  https://$(hostname -I | awk '{print $1}')"
echo ""
echo "View logs:"
echo "  docker-compose logs -f"
echo ""
echo "Stop services:"
echo "  docker-compose down"
echo ""
