"""FastAPI entry point — serves the JSON API and the chat UI in frontend/.

    uvicorn api.main:app            # then open http://localhost:8000

- Identity (user, role, tenant) comes from the X-API-Key header via api/auth.py. The
  request body only carries the query; extra fields such as "role" are rejected (422).
- Client IP comes from the connection (X-Forwarded-For only when TRUST_X_FORWARDED_FOR=true).
- The rate-limit session key is derived server-side (user id, or IP for anonymous callers).
- Every response carries a strict Content-Security-Policy: the UI renders model output, so
  scripts may only come from this server (frontend/vendor), never inline or from elsewhere.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from api.auth import authenticate
from config.settings import API_SETTINGS, MODEL_SETTINGS, PROJECT_ROOT, get_thresholds
from generation.l7_generation import active_model_label
from pipeline.orchestrator import handle_request

MAX_QUERY_CHARS = get_thresholds().max_query_chars
FRONTEND_DIR = PROJECT_ROOT / "frontend"

SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                                "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # Revalidate every time (ETag makes it cheap): users get UI fixes immediately and
    # answers are never served from a shared cache.
    "Cache-Control": "no-cache",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load heavy models at startup instead of on the first request.
    from knowledge_bases.kb_manager import kb
    kb.embed("warm-up")
    if get_thresholds().enable_l3 and os.getenv("WARMUP_GUARDRAIL", "true").lower() == "true":
        from security.l3_llm_guardrail import get_guardrail
        get_guardrail()
    yield


app = FastAPI(title="Secure RAG Support Assistant", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


def client_ip(request: Request) -> str:
    if API_SETTINGS.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _identity_or_401(x_api_key):
    identity = authenticate(x_api_key)
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return identity


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/info")
def info():
    """Non-sensitive display info for the UI."""
    return {"model": active_model_label(), "backend": MODEL_SETTINGS.generation_backend,
            "max_query_chars": MAX_QUERY_CHARS, "allow_anonymous": API_SETTINGS.allow_anonymous}


@app.get("/whoami")
def whoami(x_api_key: str | None = Header(default=None)):
    identity = _identity_or_401(x_api_key)
    return {"user_id": identity.user_id, "role": identity.role, "tenant_id": identity.tenant_id,
            "authenticated": identity.authenticated}


@app.post("/chat")
def chat(req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)):
    identity = _identity_or_401(x_api_key)
    ip = client_ip(request)
    session_id = f"user:{identity.user_id}" if identity.authenticated else f"ip:{ip}"
    cfg = get_thresholds()
    result = handle_request(query=req.query, user_id=identity.user_id, role=identity.role, ip=ip,
                            session_id=session_id, tenant_id=identity.tenant_id, cfg=cfg)
    return JSONResponse(status_code=result.status_code, content=result.public(cfg.expose_block_layer))


# The chat UI (mounted last so the API routes above take precedence).
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
