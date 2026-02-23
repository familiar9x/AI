from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import os

from pypdf import PdfReader
from docx import Document
import markdown as md

from utils import sha1_file, ensure_dir

def load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def load_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join([p.text for p in doc.paragraphs]).strip()

def load_md(path: Path) -> str:
    raw = load_txt(path)
    html = md.markdown(raw)
    import re
    return re.sub("<[^<]+?>", "", html).strip()

def _ocr_page_cached(pdf_path: Path, page_number_1based: int) -> str:
    """
    OCR 1 page, with cache.
    """
    from pdf2image import convert_from_path
    import pytesseract

    cache_dir = Path(os.environ.get("CACHE_DIR", "/app/.cache"))
    ocr_dir = ensure_dir(cache_dir / "ocr")

    pdf_hash = sha1_file(pdf_path)
    lang = os.environ.get("OCR_LANG", "eng")
    dpi = int(os.environ.get("OCR_DPI", "250"))

    cache_key = f"{pdf_hash}_p{page_number_1based}_dpi{dpi}_{lang.replace('+','-')}.txt"
    cache_file = ocr_dir / cache_key

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="ignore").strip()

    # pdf2image uses 1-based page indexing for first_page/last_page
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_number_1based,
        last_page=page_number_1based,
    )
    text = ""
    if images:
        text = pytesseract.image_to_string(images[0], lang=lang) or ""
    text = text.strip()

    cache_file.write_text(text, encoding="utf-8")
    return text

def load_pdf_pages(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Return list of {page_number, text}.
    page_number is 1-based for human citation.
    """
    reader = PdfReader(str(pdf_path))
    pages_out: List[Dict[str, Any]] = []

    # threshold for deciding a page is "scanned"
    min_chars = int(os.environ.get("PDF_TEXT_MIN_CHARS", "80"))

    for idx, page in enumerate(reader.pages):
        page_no = idx + 1
        extracted = (page.extract_text() or "").strip()

        # If extracted is too short => OCR this page
        if len(extracted) < min_chars:
            ocr_text = _ocr_page_cached(pdf_path, page_no)
            text = ocr_text.strip()
            mode = "ocr"
        else:
            text = extracted
            mode = "text"

        if text:
            pages_out.append({
                "path": str(pdf_path),
                "page_number": page_no,
                "text": text,
                "mode": mode,
            })
    return pages_out

def load_documents(docs_dir: Path) -> List[Dict[str, Any]]:
    """
    For non-PDF: returns doc objects with text.
    For PDF: returns per-page doc objects (text is page text).
    """
    out: List[Dict[str, Any]] = []
    for p in docs_dir.rglob("*"):
        if p.is_dir():
            continue
        suffix = p.suffix.lower()
        try:
            if suffix in [".txt", ".log"]:
                text = load_txt(p).strip()
                if text:
                    out.append({"path": str(p), "text": text})
            elif suffix == ".pdf":
                out.extend(load_pdf_pages(p))
            elif suffix == ".docx":
                text = load_docx(p).strip()
                if text:
                    out.append({"path": str(p), "text": text})
            elif suffix in [".md", ".markdown"]:
                text = load_md(p).strip()
                if text:
                    out.append({"path": str(p), "text": text})
            else:
                continue
        except Exception as e:
            out.append({"path": str(p), "text": "", "error": str(e)})
    return out
