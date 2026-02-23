# Private RAG System v3

Hệ thống RAG (Retrieval-Augmented Generation) hoàn toàn private, chạy 100% local trong mạng nội bộ.

## ✨ Tính năng v3 (Latest)

- **🔐 Enterprise SSO**: Keycloak OIDC/OAuth2 authentication
- **👥 AD Group Authorization**: Control access theo AD groups
- **🔒 JWT Verification**: Backend verify JWT tokens thật
- **🌐 Nginx Reverse Proxy**: Unified HTTPS entry point
- **🎫 oauth2-proxy**: Transparent SSO cho UI và API

## ✨ Tính năng v2

- **📄 Page-level citations**: Trích dẫn chính xác `[file.pdf | page X]`
- **⚡ OCR cache**: Cache kết quả OCR theo hash, ingest lại cực nhanh
- **🎯 Incremental ingest**: Ingest từng file/folder riêng lẻ, không cần quét toàn bộ
- **🔍 Per-page indexing**: Mỗi trang PDF là một đơn vị độc lập

## Kiến trúc

```
Docs (pdf/docx/md/txt)
   ↓ (ingest + chunk)
Embedding model (local)  ─────→  Vector DB (Qdrant)
   ↓                                 ↑
Query text → embed → retrieve topK ───┘
   ↓
LLM server (local, vLLM) → generate answer + citations
   ↓
Backend API (FastAPI)  + (optional) Redis cache
   ↓
Web UI (OpenWebUI) hoặc UI tối giản
```

## Stack công nghệ

- **LLM serving**: vLLM (OpenAI-compatible API)
- **Embedding**: sentence-transformers (bge-m3)
- **Vector DB**: Qdrant
- **API**: FastAPI
- **UI**: Open WebUI
- **Auth**: Keycloak OIDC (v3) with oauth2-proxy
- **Reverse Proxy**: Nginx with HTTPS
- **OCR**: Tesseract + pdf2image (xử lý PDF scan)

## Yêu cầu hệ thống

- Docker & Docker Compose
- NVIDIA GPU (cho vLLM)
- NVIDIA Container Toolkit
- Tối thiểu 16GB RAM (32GB+ khuyến nghị)
- 20GB+ dung lượng đĩa cho models

## Cài đặt NVIDIA Container Toolkit

```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

## Tải model LLM

Tải model Qwen2.5-7B-Instruct (hoặc model khác) vào thư mục `models/`:

```bash
# Sử dụng huggingface-cli
pip install huggingface-hub

huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir ./models/Qwen2.5-7B-Instruct

# Hoặc tải thủ công từ https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
```

## Cấu hình

### Quick Start (v2 - No SSO)

1. Chỉnh sửa file `.env`:

```bash
# Thay đổi API key (quan trọng!)
API_KEY=your_secure_random_key_here

# Có thể điều chỉnh embedding model
EMBED_MODEL=sentence-transformers/bge-m3

# Điều chỉnh RAG parameters
CHUNK_SIZE=900
CHUNK_OVERLAP=150
TOP_K=6

# OCR language: eng (English), vie (Vietnamese), hoặc eng+vie
OCR_LANG=eng+vie
```

2. Comment out oauth2-proxy và nginx trong `docker-compose.yml` nếu không dùng SSO

### Enterprise Setup (v3 - With SSO)

**Prerequisites:**
- Keycloak server đã setup (external)
- SSL certificates
- DNS records

**Configuration:**

1. Setup Keycloak (xem [V3_SSO_GUIDE.md](docs/V3_SSO_GUIDE.md)):
   - Create realm
   - Create client `rag-proxy`
   - Create groups: `rag-admins`, `rag-users`
   - Configure group mapper

2. Generate secrets:
```bash
# Cookie secret
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

3. Update `.env` với OIDC config (xem `.env` file)

4. Setup SSL certificates:
```bash
cd nginx/certs
# Copy hoặc generate certificates
# fullchain.pem, privkey.pem
```

5. Update `nginx/conf.d/default.conf` với server name của bạn

2. Nếu dùng model khác, cập nhật `docker-compose.yml`:

```yaml
vllm:
  command: >
    --model /models/your-model-name
    --host 0.0.0.0
    --port 8000
    --dtype auto
    --max-model-len 8192
```

## Khởi động hệ thống

### v2 Mode (No SSO)

```bash
# Build và start tất cả services
docker-compose up -d

# Xem logs
docker-compose logs -f

# Kiểm tra trạng thái
docker-compose ps
```

**Access:**
- UI: http://localhost:3000
- API: http://localhost:8080
- Qdrant: http://localhost:6333

### v3 Mode (With SSO)

```bash
# Build và start
docker-compose up -d --build

# Check services
docker-compose ps

# Monitor logs
docker-compose logs -f nginx oauth2-proxy backend
```

**Access:**
- UI: https://rag.company.local (redirects to Keycloak login)
- API: https://rag.company.local/api
- Qdrant: http://localhost:6333 (internal only)

## Sử dụng

### 1. Thêm tài liệu

Đặt các file tài liệu vào thư mục `docs/`:

```bash
cp /path/to/your/documents/*.pdf docs/
cp /path/to/your/documents/*.docx docs/
```

**Lưu ý về PDF scan:**
- Hệ thống tự động phát hiện PDF scan (ít text) và dùng OCR
- PDF scan sẽ xử lý chậm hơn (OCR tốn CPU)
- Hỗ trợ tiếng Việt: đặt `OCR_LANG=vie` trong `.env`
- Chất lượng OCR phụ thuộc vào độ phân giải scan (khuyến nghị ≥250 DPI)

### 2. Ingest tài liệu vào vector database

**✨ v2: Incremental Ingest**

```bash
# Ingest toàn bộ docs/
curl -X POST "http://localhost:8080/admin/ingest" \
  -H "Authorization: Bearer your_secure_random_key_here"

# Ingest một file cụ thể
curl -X POST "http://localhost:8080/admin/ingest?path=handbook.pdf" \
  -H "Authorization: Bearer your_secure_random_key_here"

# Ingest một folder con
curl -X POST "http://localhost:8080/admin/ingest?path=policies/" \
  -H "Authorization: Bearer your_secure_random_key_here"

# Ingest file với đường dẫn tuyệt đối (trong container)
curl -X POST "http://localhost:8080/admin/ingest?path=/app/docs/reports/2024.pdf" \
  -H "Authorization: Bearer your_secure_random_key_here"
```

**Chạy trực tiếp trong container:**

```bash
# Toàn bộ
docker exec -it rag-backend python ingest.py

# Một file
docker exec -it rag-backend python ingest.py handbook.pdf

# Một folder
docker exec -it rag-backend python ingest.py policies/
```

**💡 Lợi ích incremental ingest:**
- Cập nhật nhanh khi thêm tài liệu mới
- Không cần re-index toàn bộ
- OCR cache giữ lại → ingest lại file cũ cực nhanh
- Hữu ích khi có hàng nghìn tài liệu

### 3. Truy cập Web UI

Mở trình duyệt và truy cập:

```
http://localhost:3000
```

OpenWebUI sẽ tự động kết nối với backend RAG của bạn.

### 4. Test API trực tiếp

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_secure_random_key_here" \
  -d '{
    "model": "Qwen2.5-7B-Instruct",
    "messages": [
      {"role": "user", "content": "Câu hỏi của bạn ở đây"}
    ],
    "temperature": 0.2,
    "max_tokens": 512
  }'
```

**✨ v2: Response sẽ có `rag_meta` với page numbers:**

```json
{
  "choices": [...],
  "rag_meta": {
    "request_id": "abc123",
    "retrieved": [
      {
        "source": "/app/docs/handbook.pdf",
        "page_number": 15,
        "chunk_index": 2,
        "score": 0.87
      },
      ...
    ],
    "latency_ms": 234
  }
}
```

## Services và Ports

- **Qdrant**: http://localhost:6333 (Vector database admin UI)
- **vLLM**: http://localhost:8000 (LLM inference API)
- **Backend**: http://localhost:8080 (RAG API)
- **OpenWebUI**: http://localhost:3000 (Web interface)

## Health checks

```bash
# Backend health
curl http://localhost:8080/healthz

# vLLM health
curl http://localhost:8000/health

# Qdrant health
curl http://localhost:6333/healthz
```

## Quản lý

### Dừng hệ thống

```bash
docker-compose down
```

### Xóa tất cả data (bao gồm vector database)

```bash
docker-compose down -v
```

### Restart một service

```bash
docker-compose restart backend
docker-compose restart vllm
```

### Xem logs của một service

```bash
docker-compose logs -f backend
docker-compose logs -f vllm
```

## Troubleshooting

### GPU không được nhận diện

```bash
# Kiểm tra NVIDIA driver
nvidia-smi

# Kiểm tra Docker có thấy GPU không
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### vLLM không start được

- Kiểm tra GPU memory: model cần ít nhất 8GB VRAM
- Giảm `--max-model-len` trong docker-compose.yml
- Thử model nhỏ hơn (ví dụ: Qwen2.5-3B)

### Backend không kết nối được Qdrant/vLLM

- Đợi vài phút để các service khởi động hoàn toàn
- Kiểm tra logs: `docker-compose logs qdrant vllm`
- Kiểm tra network: `docker network inspect private-rag_default`

### Embedding model download chậm

Embedding model sẽ tự động download lần đầu tiên. Để tăng tốc:

```bash
# Pre-download embedding model
docker exec -it rag-backend python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/bge-m3')"
```

### OCR không hoạt động hoặc kết quả kém

**PDF không được OCR:**
- Kiểm tra PDF có ít hơn 200 ký tự text không (ngưỡng trigger OCR)
- Xem logs: `docker-compose logs backend | grep OCR`

**Kết quả OCR kém chất lượng:**
- PDF scan có độ phân giải thấp (< 200 DPI)
- Chữ trong PDF bị méo, mờ
- Giải pháp: re-scan tài liệu với DPI cao hơn (≥250 DPI)

**OCR tiếng Việt không đúng:**
- Đảm bảo đã set `OCR_LANG=vie` trong `.env`
- Rebuild backend: `docker-compose up -d --build backend`
- Tesseract language pack đã được cài trong Dockerfile

**OCR quá chậm:**
- OCR tốn CPU, bình thường với PDF scan nhiều trang
- Xem xét tăng CPU limits trong docker-compose nếu cần
- Có thể pre-process PDFs offline trước khi deploy

## Tối ưu hóa

### Tăng performance

1. **Tăng số lượng retrieve chunks**:
   ```bash
   # Trong .env
   TOP_K=10
   ```

2. **Điều chỉnh chunk size**:
   ```bash
   CHUNK_SIZE=1200
   CHUNK_OVERLAP=200
   ```

3. **Enable quantization cho vLLM**:
   ```yaml
   # Trong docker-compose.yml
   command: >
     --model /models/Qwen2.5-7B-Instruct
     --quantization awq
   ```

### Giảm memory usage

1. Dùng model nhỏ hơn
2. Giảm `--max-model-len`
3. Enable CPU offload (nếu RAM nhiều hơn VRAM)

## Production checklist

- [ ] Đổi `API_KEY` thành giá trị ngẫu nhiên mạnh
- [ ] Setup HTTPS reverse proxy (nginx/traefik)
- [ ] Enable rate limiting
- [ ] Setup monitoring (Prometheus + Grafana)
- [ ] Setup backup cho Qdrant data
- [ ] Configure log rotation
- [ ] Setup alerting
- [ ] Document disaster recovery procedure
- [ ] Regular security updates

## Nâng cấp tương lai

- [ ] Redis cache cho frequently asked questions
- [ ] OAuth/SSO integration
- [ ] Multi-user support với user quotas
- [ ] Advanced RAG: hybrid search (dense + sparse)
- [ ] Re-ranking model
- [ ] Query expansion/rewriting
- [ ] Feedback loop để improve results
- [ ] A/B testing framework

## License

Internal use only.

## Support

Contact your internal DevOps/ML team for support.
