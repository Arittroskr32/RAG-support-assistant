"""FastAPI entry point — serves the JSON API and the chat UI in frontend/.

    uvicorn api.main:app            # then open http://localhost:8000

- Identity (user, role, tenant) comes from the X-API-Key header (api/auth.py) or, without a
  key, from the browser session cookie (api/accounts.py: register/sign in, role from
  config/role_assignments.json). The request body only carries the query; extra fields such
  as "role" are rejected (422).
- Client IP comes from the connection (X-Forwarded-For only when TRUST_X_FORWARDED_FOR=true).
- The rate-limit session key is derived server-side (user id, or IP for anonymous callers).
- Every response carries a strict Content-Security-Policy: the UI renders model output, so
  scripts may only come from this server (frontend/vendor), never inline or from elsewhere.
"""
import os
from contextlib import asynccontextmanager

from fastapi import Cookie, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from api import accounts, chat_history
from api.auth import ANONYMOUS, authenticate
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


def _identity_or_401(x_api_key, session_cookie=None):
    """X-API-Key wins (scripts, evals); otherwise the browser session; otherwise anonymous."""
    if not x_api_key and session_cookie:
        email = accounts.email_from_session_token(session_cookie)
        if email:
            return accounts.identity_for(email)
    identity = authenticate(x_api_key)
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return identity


def _whoami_body(identity):
    return {"user_id": identity.user_id, "role": identity.role, "tenant_id": identity.tenant_id,
            "authenticated": identity.authenticated, "via": identity.via}


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


def _require_json(request: Request):
    # A cross-site HTML form can't send application/json, so this blocks login CSRF.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(status_code=415, detail="Send JSON")


def _signed_in(email: str, request: Request, status_code: int = 200):
    response = JSONResponse(status_code=status_code, content=_whoami_body(accounts.identity_for(email)))
    response.set_cookie(accounts.COOKIE_NAME, accounts.make_session_token(email),
                        max_age=API_SETTINGS.session_ttl_s, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/info")
def info():
    """Non-sensitive display info for the UI."""
    return {"model": active_model_label(), "backend": MODEL_SETTINGS.generation_backend,
            "max_query_chars": MAX_QUERY_CHARS, "allow_anonymous": API_SETTINGS.allow_anonymous,
            "allow_registration": API_SETTINGS.allow_registration}


@app.get("/whoami")
def whoami(x_api_key: str | None = Header(default=None),
           rag_session: str | None = Cookie(default=None)):
    return _whoami_body(_identity_or_401(x_api_key, rag_session))


@app.post("/auth/register")
def register(creds: Credentials, request: Request):
    _require_json(request)
    try:
        email = accounts.register(creds.email, creds.password)
    except accounts.AccountError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    return _signed_in(email, request, status_code=201)


@app.post("/auth/login")
def login(creds: Credentials, request: Request):
    _require_json(request)
    try:
        email = accounts.login(creds.email, creds.password, client_ip(request))
    except accounts.AccountError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    return _signed_in(email, request)


@app.post("/auth/logout")
def logout(request: Request):
    _require_json(request)
    response = JSONResponse(content=_whoami_body(ANONYMOUS))
    response.delete_cookie(accounts.COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return response


class HistoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversations: list = Field(default_factory=list)


@app.get("/history")
def get_history(x_api_key: str | None = Header(default=None),
                rag_session: str | None = Cookie(default=None)):
    """The signed-in user's saved conversations. Anonymous callers get an empty list
    (their history lives only in the browser)."""
    identity = _identity_or_401(x_api_key, rag_session)
    if not identity.authenticated:
        return {"conversations": []}
    return {"conversations": chat_history.load(identity.user_id)}


@app.put("/history")
def put_history(body: HistoryBody, request: Request, x_api_key: str | None = Header(default=None),
                rag_session: str | None = Cookie(default=None)):
    """Replace the signed-in user's saved conversations. Requires an account; the user_id is
    taken server-side from the session/API key, so one user can only ever write their own."""
    _require_json(request)
    identity = _identity_or_401(x_api_key, rag_session)
    if not identity.authenticated:
        raise HTTPException(status_code=403, detail="Sign in to save your chat history.")
    try:
        saved = chat_history.save(identity.user_id, body.conversations)
    except ValueError:
        raise HTTPException(status_code=413, detail="Chat history is too large to save.") from None
    return {"conversations": saved}


@app.delete("/history")
def delete_history(x_api_key: str | None = Header(default=None),
                   rag_session: str | None = Cookie(default=None)):
    """Delete the signed-in user's saved conversations."""
    identity = _identity_or_401(x_api_key, rag_session)
    if identity.authenticated:
        chat_history.clear(identity.user_id)
    return {"conversations": []}


@app.post("/chat")
def chat(req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None),
         rag_session: str | None = Cookie(default=None)):
    identity = _identity_or_401(x_api_key, rag_session)
    ip = client_ip(request)
    session_id = f"user:{identity.user_id}" if identity.authenticated else f"ip:{ip}"
    cfg = get_thresholds()
    result = handle_request(query=req.query, user_id=identity.user_id, role=identity.role, ip=ip,
                            session_id=session_id, tenant_id=identity.tenant_id, cfg=cfg)
    return JSONResponse(status_code=result.status_code, content=result.public(cfg.expose_block_layer))


# The chat UI (mounted last so the API routes above take precedence).
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
