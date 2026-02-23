# Tài liệu nội bộ

Đặt các file tài liệu nội bộ của bạn vào thư mục này.

## Định dạng được hỗ trợ

- `.txt` - Text files
- `.pdf` - PDF documents
- `.docx` - Word documents
- `.md` / `.markdown` - Markdown files
- `.log` - Log files

## Ví dụ cấu trúc

```
docs/
  hướng-dẫn-nội-bộ.pdf
  quy-trình/
    quy-trình-1.docx
    quy-trình-2.md
  chính-sách/
    chính-sách-bảo-mật.pdf
    quy-định-nội-bộ.txt
```

## Sau khi thêm tài liệu

Chạy lệnh ingest để đưa tài liệu vào vector database:

```bash
curl -X POST http://localhost:8080/admin/ingest \
  -H "Authorization: Bearer change_me_long_random"
```

Hoặc từ bên trong container:

```bash
docker exec -it rag-backend python ingest.py
```
