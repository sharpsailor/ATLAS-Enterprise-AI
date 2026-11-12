"""Untrusted document -> text, run in a child process the OS limits on memory, CPU and wall time.

Upload size is no bound on parsing cost: DOCX is a zip, PDF streams are compressed, and XML/DOM
building amplifies further. The format checks below fail fast on obvious abuse; the process limits
are what actually contain a hostile file, which then kills only the child, never the web server.
Kept free of app imports so the spawned child starts light.
"""
import io
import multiprocessing
import resource
import zipfile
from pathlib import Path

from docx import Document
from pypdf import PdfReader

MAX_UNZIPPED_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500
MAX_TEXT_CHARS = 2_000_000
PARSE_MEMORY_BYTES = 256 * 1024 * 1024  # child address space; libraries alone use ~45 MB
PARSE_CPU_SECONDS = 30
PARSE_TIMEOUT_SECONDS = 60
LIMIT_ERROR = "document parsing exceeded its time or memory limit"


def parse(filename: str, data: bytes) -> list[tuple[int, str]]:
    """(page number, text) pairs. Non-PDF formats are a single page 1. Call via parse_isolated."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > MAX_PAGES:
            raise ValueError(f"PDF has {len(reader.pages)} pages; limit is {MAX_PAGES}")
        pages, total = [], 0
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_TEXT_CHARS:
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


def _child(filename: str, data: bytes, conn, memory: int, cpu: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    try:
        conn.send((True, parse(filename, data)))
    except MemoryError:
        conn.send((False, LIMIT_ERROR))
    except Exception as e:
        conn.send((False, f"could not parse document: {type(e).__name__}: {e}"))


def parse_isolated(filename: str, data: bytes, memory: int = PARSE_MEMORY_BYTES,
                   cpu: int = PARSE_CPU_SECONDS, timeout: float = PARSE_TIMEOUT_SECONDS) -> list[tuple[int, str]]:
    # spawn, not fork: forking a threaded server can copy held locks into the child.
    ctx = multiprocessing.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(filename, data, send, memory, cpu), daemon=True)
    proc.start()
    send.close()
    try:
        if not recv.poll(timeout):
            raise ValueError(LIMIT_ERROR)
        ok, result = recv.recv()  # EOFError: child was killed (e.g. SIGXCPU) before replying
    except EOFError:
        raise ValueError(LIMIT_ERROR) from None
    finally:
        proc.kill()
        proc.join()
        recv.close()
    if not ok:
        raise ValueError(result)
    return result
