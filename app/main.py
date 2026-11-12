import base64
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import observability
from app.aws import presign_put
from app.config import settings
from app.db import audit, q
from app.graph import chat
from app.guardrails import classify_input
from app.memory import list_messages, load_history, save_turn
from worker.ingest import process_s3_key

HERE = Path(__file__).parent
ALLOWED_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
                 ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
SENSITIVE = re.compile(r"\b(delete|export|send to|update policy)\b", re.IGNORECASE)


@asynccontextmanager
async def lifespan(_):
    observability.initialize()
    yield


app = FastAPI(title="Atlas Enterprise AI", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


@app.middleware("http")
async def password_gate(request: Request, call_next):
    """HTTP Basic auth on everything but health checks, when APP_PASSWORD is set. Not per-user auth."""
    if settings.app_password and not request.url.path.startswith("/health"):
        try:
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            password = base64.b64decode(token).decode().partition(":")[2] if scheme.lower() == "basic" else ""
        except ValueError:
            password = ""
        if not secrets.compare_digest(password.encode(), settings.app_password.encode()):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="atlas"'})
    return await call_next(request)


def principal() -> dict:
    # Auth is out of scope: a fixed demo principal. Replace this one function with real token parsing.
    return {"tenant": "novacore", "sub": "demo-user", "groups": ["all-staff", "admins"], "admin": True}


def admin(p: dict = Depends(principal)) -> dict:
    if not p["admin"]:
        raise HTTPException(403, "admin only")
    return p


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=180)


class CompleteIn(BaseModel):
    document_id: UUID


class ChatIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: UUID | None = None


class FeedbackIn(BaseModel):
    document_id: UUID | None = None
    rating: int = Field(ge=-1, le=1)
    note: str = Field("", max_length=2000)


class DecisionIn(BaseModel):
    approve: bool


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        q("select 1")
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {type(e).__name__}")
    return {"status": "ok"}


@app.post("/api/documents/uploads")
def create_upload(body: UploadIn, p: dict = Depends(principal)):
    name = Path(body.filename).name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(400, f"unsupported file type; allowed: {', '.join(ALLOWED_TYPES)}")
    doc_id = uuid4()
    key = f"tenants/{p['tenant']}/incoming/{doc_id}/v1{ext}"
    q("""insert into documents (id, tenant_id, title, owner_sub, allowed_groups, s3_key)
         values (%s, %s, %s, %s, %s, %s)""", (doc_id, p["tenant"], name, p["sub"], ["all-staff"], key))
    audit(p["sub"], p["tenant"], "upload_requested", document_id=str(doc_id), filename=name)
    headers = {"Content-Type": ALLOWED_TYPES[ext]}
    return {"document_id": doc_id, "upload_url": presign_put(key, headers["Content-Type"]), "headers": headers}


@app.post("/api/documents/complete")
def complete_upload(body: CompleteIn, p: dict = Depends(principal)):
    doc = q("select s3_key from documents where id = %s and tenant_id = %s", (body.document_id, p["tenant"]), one=True)
    if not doc:
        raise HTTPException(404, "document not found")
    try:
        # ponytail: ingestion runs inline in the request; move to the atlas-ingest SQS queue when files get big
        return {"status": process_s3_key(doc["s3_key"])}
    except Exception as e:
        raise HTTPException(502, f"ingestion failed: {e}")


@app.get("/api/documents")
def list_documents(p: dict = Depends(principal)):
    return q("""select id, title, status, chunk_count, error, created_at from documents
                where tenant_id = %s and (allowed_groups && %s or owner_sub = %s)
                order by created_at desc limit 100""", (p["tenant"], p["groups"], p["sub"]))


@app.post("/api/chat")
def chat_route(body: ChatIn, p: dict = Depends(principal)):
    conv = str(body.conversation_id or uuid4())
    if rule := classify_input(body.question):
        audit(p["sub"], p["tenant"], "guardrail_input_blocked", rule=rule)
        raise HTTPException(400, "Request blocked by input guardrail.")
    if settings.hitl_enabled and SENSITIVE.search(body.question):
        row = q("insert into approvals (tenant_id, requester, question) values (%s, %s, %s) returning id",
                (p["tenant"], p["sub"], body.question), one=True)
        audit(p["sub"], p["tenant"], "approval_requested", approval_id=str(row["id"]))
        return {"status": "pending_approval", "approval_id": row["id"], "conversation_id": conv, "sources": [],
                "answer": "This request needs human approval. It has been sent to an admin for review."}
    result = chat(body.question, load_history(p, conv, settings.memory_turns), p)
    save_turn(p, conv, body.question, result["answer"])
    if result["status"] == "guardrail_blocked":
        audit(p["sub"], p["tenant"], "guardrail_output_blocked", conversation_id=conv)
    return {"answer": result["answer"], "sources": result.get("sources", []),
            "status": result["status"], "conversation_id": conv}


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: UUID, p: dict = Depends(principal)):
    return list_messages(p, str(conversation_id))


@app.post("/api/feedback")
def feedback(body: FeedbackIn, p: dict = Depends(principal)):
    q("insert into feedback (tenant_id, actor, document_id, rating, note) values (%s, %s, %s, %s, %s)",
      (p["tenant"], p["sub"], body.document_id, body.rating, body.note))
    return {"status": "ok"}


@app.get("/api/approvals")
def approvals(p: dict = Depends(admin)):
    return q("""select id, requester, question, status, reviewer, reviewed_at, created_at from approvals
                where tenant_id = %s order by status <> 'pending', created_at desc limit 100""", (p["tenant"],))


@app.post("/api/approvals/{approval_id}/decision")
def decide(approval_id: UUID, body: DecisionIn, p: dict = Depends(admin)):
    status = "approved" if body.approve else "rejected"
    row = q("""update approvals set status = %s, reviewer = %s, reviewed_at = now()
               where id = %s and tenant_id = %s and status = 'pending' returning id, status""",
            (status, p["sub"], approval_id, p["tenant"]), one=True)
    if not row:
        raise HTTPException(409, "approval not found or already decided")
    audit(p["sub"], p["tenant"], "approval_decided", approval_id=str(approval_id), status=status)
    # Recording the decision only; executing the action belongs to a separate, audited system.
    return {**row, "executed": False}


@app.get("/api/admin/metrics")
def metrics(p: dict = Depends(admin)):
    docs = q("select status, count(*)::int as n from documents where tenant_id = %s group by status", (p["tenant"],))
    fb = q("select rating, count(*)::int as n from feedback where tenant_id = %s group by rating", (p["tenant"],))
    return {"documents": {r["status"]: r["n"] for r in docs},
            "feedback": {{1: "up", 0: "neutral", -1: "down"}[r["rating"]]: r["n"] for r in fb}}


@app.get("/api/admin/guardrails")
def guardrail_stats(p: dict = Depends(admin)):
    rows = q("""select action, count(*)::int as n from audit_events where tenant_id = %s
                and action in ('guardrail_input_blocked', 'guardrail_output_blocked') group by action""", (p["tenant"],))
    return {"input_blocked": 0, "output_blocked": 0,
            **{r["action"].removeprefix("guardrail_").removesuffix("_blocked") + "_blocked": r["n"] for r in rows}}
