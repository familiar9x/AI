from __future__ import annotations
from pathlib import Path
import os
from typing import Optional

from loaders import load_documents, load_pdf_pages, load_txt, load_docx, load_md
from rag import RagConfig, RagStore

def infer_group_from_path(path: Path, base: Path) -> Optional[str]:
    """
    Infer doc_group from folder structure.
    Convention: docs/GROUP-NAME/... -> doc_group = "GROUP-NAME"
    
    Examples:
        /app/docs/OPS-TEAM/file.pdf -> "OPS-TEAM"
        /app/docs/FINANCE-READ/reports/2024.pdf -> "FINANCE-READ"
        /app/docs/file.pdf -> None (no group)
    """
    try:
        rel = path.relative_to(base)
        parts = rel.parts
        if len(parts) > 1:
            # First folder under docs/ is the group
            return parts[0]
        return None
    except ValueError:
        return None

def ingest_path(store: RagStore, path: Path) -> tuple[int, int]:
    """
    returns (docs_count, chunks_count)
    """
    docs_count = 0
    chunks_count = 0
    base = Path("/app/docs")

    if path.is_dir():
        docs = load_documents(path)
        for d in docs:
            if d.get("error"):
                print(f"[SKIP] {d['path']} error={d['error']}")
                continue

            # Infer doc_group from path
            doc_path = Path(d["path"])
            doc_group = infer_group_from_path(doc_path, base)

            # PDF page objects have page_number
            page_no = d.get("page_number")
            meta = {"mode": d.get("mode")} if d.get("mode") else {}
            if doc_group:
                meta["doc_group"] = doc_group

            n = store.upsert_chunked(d["path"], d["text"], page_number=page_no, meta=meta)
            docs_count += 1
            chunks_count += n
            group_info = f" group={doc_group}" if doc_group else ""
            if page_no:
                print(f"[INGEST] {d['path']} page={page_no}{group_info} chunks={n}")
            else:
                print(f"[INGEST] {d['path']}{group_info} chunks={n}")

        return docs_count, chunks_count

    # file
    suffix = path.suffix.lower()
    doc_group = infer_group_from_path(path, base)
    meta = {"doc_group": doc_group} if doc_group else {}
    
    if suffix == ".pdf":
        pages = load_pdf_pages(path)
        for p in pages:
            page_meta = {"mode": p.get("mode")}
            if doc_group:
                page_meta["doc_group"] = doc_group
            n = store.upsert_chunked(p["path"], p["text"], page_number=p["page_number"], meta=page_meta)
            docs_count += 1
            chunks_count += n
            group_info = f" group={doc_group}" if doc_group else ""
            print(f"[INGEST] {p['path']} page={p['page_number']}{group_info} chunks={n}")
        return docs_count, chunks_count

    # For non-pdf single file
    text = ""
    try:
        if suffix in [".txt", ".log"]:
            text = load_txt(path).strip()
        elif suffix == ".docx":
            text = load_docx(path).strip()
        elif suffix in [".md", ".markdown"]:
            text = load_md(path).strip()
    except Exception as e:
        print(f"[SKIP] {path} error={e}")
        return 0, 0

    if text:
        n = store.upsert_chunked(str(path), text, page_number=None, meta=meta)
        group_info = f" group={doc_group}" if doc_group else ""
        print(f"[INGEST] {path}{group_info} chunks={n}")
        return 1, n
    return 0, 0

def main(target: Optional[str] = None):
    cfg = RagConfig(
        qdrant_url=os.environ["QDRANT_URL"],
        collection=os.environ.get("QDRANT_COLLECTION", "internal_docs"),
        embed_model=os.environ.get("EMBED_MODEL", "sentence-transformers/bge-m3"),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "900")),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", "150")),
        top_k=int(os.environ.get("TOP_K", "6")),
    )
    store = RagStore(cfg)

    base = Path("/app/docs")
    path = Path(target) if target else base
    if not path.is_absolute():
        # allow relative paths inside /app/docs
        path = (base / path).resolve()

    docs, chunks = ingest_path(store, path)
    print(f"Done. ingested_units={docs}, chunks={chunks}, target={path}")

if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
