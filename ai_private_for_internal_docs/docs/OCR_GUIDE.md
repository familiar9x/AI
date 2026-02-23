# OCR Support - Xử lý PDF Scan

Hệ thống tự động phát hiện và xử lý PDF scan bằng OCR.

## Cơ chế hoạt động

1. **Thử extract text thông thường** (pypdf - nhanh)
2. **Nếu text < 200 ký tự** → coi như PDF scan
3. **Chuyển sang OCR** (pytesseract - chậm nhưng chính xác)

## Cấu hình OCR

### Ngôn ngữ

Trong file `.env`:

```bash
# English (mặc định)
OCR_LANG=eng

# Vietnamese
OCR_LANG=vie

# Cả hai ngôn ngữ
OCR_LANG=eng+vie
```

### Tesseract Language Packs đã cài

Backend Dockerfile đã cài sẵn:
- `tesseract-ocr` - Engine chính
- `tesseract-ocr-vie` - Vietnamese language pack

Nếu cần thêm ngôn ngữ khác, sửa `backend/Dockerfile`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-vie \
    tesseract-ocr-chi-sim \  # Chinese Simplified
    tesseract-ocr-jpn \      # Japanese
    && rm -rf /var/lib/apt/lists/*
```

## Hiệu suất

### Tốc độ xử lý

- **PDF text thông thường**: ~1-2 giây/file
- **PDF scan (OCR)**: ~5-30 giây/file (tùy số trang)

### Chất lượng OCR

Phụ thuộc vào:
- **DPI scan**: ≥250 DPI khuyến nghị
- **Độ nét**: Chữ rõ ràng, không mờ
- **Layout**: Đơn giản, không phức tạp
- **Font**: Standard fonts tốt hơn handwritten

## Best Practices

### Khi scan tài liệu

1. Scan ở **250-300 DPI**
2. Format: PDF (không nén quá mức)
3. Orientation: Đúng chiều (không bị nghiêng)
4. Contrast: Tốt (chữ đen, nền trắng)

### Ingest strategy

```bash
# Chia nhỏ batch nếu có nhiều PDF scan
# Tránh timeout khi ingest hàng trăm PDFs cùng lúc

# Batch 1
docker exec -it rag-backend python ingest.py

# Theo dõi progress
docker-compose logs -f backend | grep "INGEST"
```

### Tối ưu hóa

**Nếu có nhiều PDF scan (> 100 files):**

1. Tăng CPU resources cho backend container:
   ```yaml
   # Trong docker-compose.yml
   backend:
     ...
     deploy:
       resources:
         limits:
           cpus: '4.0'
   ```

2. Xem xét ingest offline (ngoài giờ làm việc)

3. Hoặc pre-convert PDF scan → text trước:
   ```bash
   # Script riêng để OCR trước
   for pdf in docs/*.pdf; do
     tesseract "$pdf" "${pdf%.pdf}" -l vie
   done
   ```

## Testing OCR

### Test thủ công

```python
# Trong container
docker exec -it rag-backend python

from pathlib import Path
from loaders import load_pdf

# Test một PDF
text = load_pdf(Path("/app/docs/your-scanned-file.pdf"))
print(f"Extracted {len(text)} characters")
print(text[:500])  # Print first 500 chars
```

### Debug OCR issues

```bash
# Check tesseract installed
docker exec -it rag-backend tesseract --version

# List available languages
docker exec -it rag-backend tesseract --list-langs

# Test OCR trực tiếp
docker exec -it rag-backend bash
cd /app/docs
# Convert PDF to images first
pdftoppm your-file.pdf output -png
# OCR the first page
tesseract output-1.png stdout -l vie
```

## Giới hạn

### Không hỗ trợ

- **Handwritten text** - Độ chính xác thấp
- **Complex layouts** - Tables, multi-column có thể bị lỗi
- **Low quality scans** - < 150 DPI
- **Rotated/skewed pages** - Cần preprocessing

### Workarounds

Cho complex documents:
1. Pre-process bằng tools khác (Adobe Acrobat, ABBYY)
2. Export sang format khác (DOCX với OCR tốt hơn)
3. Manual transcription cho phần quan trọng

## Monitoring

### Xem OCR activity

```bash
# Realtime logs
docker-compose logs -f backend | grep -E "OCR|pdf"

# Count OCR operations
docker-compose logs backend | grep -c "load_pdf_ocr"
```

### Performance metrics

Thêm logging chi tiết trong `backend/loaders.py` nếu cần:

```python
import time

def load_pdf(path: Path) -> str:
    start = time.time()
    text = load_pdf_text(path)
    
    if len(text) < 200:
        print(f"[OCR] Starting OCR for {path.name}...")
        ocr_start = time.time()
        text = load_pdf_ocr(path, lang=os.environ.get("OCR_LANG", "eng"))
        ocr_time = time.time() - ocr_start
        print(f"[OCR] Completed in {ocr_time:.2f}s, extracted {len(text)} chars")
    
    total_time = time.time() - start
    print(f"[PDF] {path.name}: {total_time:.2f}s, {len(text)} chars")
    return text
```
