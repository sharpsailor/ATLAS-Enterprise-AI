"""Ingestion: S3 object -> text -> chunks -> embeddings -> Pinecone, with status tracked in Postgres."""
import io
import zipfile
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from app import llm, vector
from app.aws import read_object
from app.db import audit, q
from app.observability import trace

CHUNK_SIZE, CHUNK_OVERLAP, EMBED_BATCH = 1200, 180, 32
# Upload size alone is no limit: DOCX is a zip and PDF streams are compressed, so cap what parsing expands to.
# (pypdf>=6 also caps each decompressed stream at 75 MB.)
# ponytail: caps run in-process; give ingestion its own memory/time-limited process if untrusted uploads grow
MAX_UNZIPPED_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500
MAX_TEXT_CHARS = 2_000_000


def parse(filename: str, data: bytes) -> list[tuple[int, str]]:
    """(page number, text) pairs. Non-PDF formats are a single page 1."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > MAX_PAGES:
            raise ValueError(f"PDF has {len(reader.pages)} pages; limit is {MAX_PAGES}")
        pages, total = [], 0
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_TEXT_CHARS:  # stop early instead of extracting everything first
                raise ValueError(f"document text exceeds {MAX_TEXT_CHARS} characters")
            pages.append((i, text))
        return pages
    if ext == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            # zipfile never inflates a member past its declared file_size, so this sum is a real bound.
            if sum(m.file_size for m in z.infolist()) > MAX_UNZIPPED_BYTES:
                raise ValueError(f"DOCX expands past {MAX_UNZIPPED_BYTES} bytes")
        pages = [(1, "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs))]
    else:
        pages = [(1, data.decode("utf-8", errors="replace"))]
    if len(pages[0][1]) > MAX_TEXT_CHARS:
        raise ValueError(f"document text exceeds {MAX_TEXT_CHARS} characters")
    return pages


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
