"""Ingestion: S3 object -> text -> chunks -> embeddings -> Pinecone, with status tracked in Postgres."""
import io
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from app import llm, vector
from app.aws import read_object
from app.db import audit, q
from app.observability import trace

CHUNK_SIZE, CHUNK_OVERLAP, EMBED_BATCH = 1200, 180, 32


def parse(filename: str, data: bytes) -> list[tuple[int, str]]:
    """(page number, text) pairs. Non-PDF formats are a single page 1."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return [(i, p.extract_text() or "") for i, p in enumerate(PdfReader(io.BytesIO(data)).pages, 1)]
    if ext == ".docx":
        return [(1, "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs))]
    return [(1, data.decode("utf-8", errors="replace"))]


def chunk(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = " ".join(text.split())
    step = size - overlap
    return [text[i:i + size] for i in range(0, max(len(text) - overlap, 1), step) if text[i:i + size].strip()]


@trace("process_s3_key")
def process_s3_key(s3_key: str) -> str:
    # Atomic claim: only one caller can move a document into 'processing'.
    doc = q("""update documents set status = 'processing', error = null, updated_at = now()
               where s3_key = %s and status in ('pending', 'failed') returning *""", (s3_key,), one=True)
    if not doc:
        row = q("select status from documents where s3_key = %s", (s3_key,), one=True)
        if not row:
            raise LookupError(f"no document for {s3_key}")
        return row["status"]
    try:
        pieces = [(page, c) for page, text in parse(doc["title"], read_object(s3_key)) for c in chunk(text)]
        if not pieces:
            raise ValueError("no extractable text (scanned PDFs need OCR)")
        vectors = []
        for b in range(0, len(pieces), EMBED_BATCH):
            batch = pieces[b:b + EMBED_BATCH]
            for j, ((page, text), values) in enumerate(zip(batch, llm.embed([t for _, t in batch])), b):
                vectors.append({"id": f"{doc['id']}:{j}", "values": values, "metadata": {
                    "document_id": str(doc["id"]), "title": doc["title"], "page": page, "text": text,
                    "owner_sub": doc["owner_sub"], "allowed_groups": doc["allowed_groups"]}})
        vector.upsert(doc["tenant_id"], vectors)
        q("update documents set status = 'ready', chunk_count = %s, updated_at = now() where id = %s",
          (len(vectors), doc["id"]))
        audit(doc["owner_sub"], doc["tenant_id"], "ingest_ready", document_id=str(doc["id"]), chunks=len(vectors))
        return "ready"
    except Exception as e:
        q("update documents set status = 'failed', error = %s, updated_at = now() where id = %s",
          (str(e)[:500], doc["id"]))
        raise
