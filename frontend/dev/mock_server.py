"""UI development server: serves frontend/ with the same security headers as api/main.py,
but answers /chat with canned responses — no models, GPU, ChromaDB or LLM needed.

    python -m frontend.dev.mock_server          # http://127.0.0.1:8765

Canned answers are picked by keyword: "diagram"/"steps", "table"/"compare", "chart",
"ignore" (a blocked request), "error" (a 503); anything else gets a plain answer.
Accounts are kept in memory: any email can register or sign in with any 8+ character
password; emails starting with "admin" get the admin role, everyone else is public.
"""
import json
import time

import uvicorn
from fastapi import Cookie, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from api.main import FRONTEND_DIR, SECURITY_HEADERS

app = FastAPI(title="Mock RAG UI server")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)


CHART = {"type": "bar", "title": "How long things last (days)", "labels": ["Free trial", "Reset link"],
         "datasets": [{"label": "Days", "data": [14, 1]}]}

ANSWERS = {
    "diagram": ("To reset your password, go to **Settings > Account > Reset Password** and follow the "
                "emailed link [c1]. The link expires after 24 hours [c1].\n\n"
                "```mermaid\nflowchart TD\n  A[Open Settings] --> B[Account]\n  B --> C[Reset Password]\n"
                "  C --> D[Check your email]\n  D --> E{Link older than 24h}\n  E -- No --> F[Set new password]\n"
                "  E -- Yes --> C\n```", {"c1": "General FAQ"}),
    "table": ("Here's how the plans compare [c1]:\n\n| Plan | For | Adds |\n|---|---|---|\n"
              "| Starter | Individuals | Core functionality |\n| Pro | Teams | Collaboration, higher usage limits |\n"
              "| Enterprise | Organizations | SSO, dedicated support, custom SLAs |\n\n"
              "All new accounts start with a **14-day free trial** [c2].", {"c1": "Product Overview", "c2": "General FAQ"}),
    "chart": ("The free trial lasts **14 days** and a password reset link is valid for **24 hours** (1 day) [c1].\n\n"
              "```chart\n" + json.dumps(CHART) + "\n```", {"c1": "General FAQ"}),
    "plain": ("Our support team is available **Monday to Friday, 9am–6pm** in your local time zone [c1]. "
              "You can email support@example.com or call 555-010-0199 [c1].", {"c1": "General FAQ"}),
}


def pick(q: str) -> str:
    q = q.lower()
    if "diagram" in q or "steps" in q:
        return "diagram"
    if "table" in q or "compare" in q:
        return "table"
    if "chart" in q:
        return "chart"
    return "plain"


@app.get("/info")
def info():
    return {"model": "llama3.1:8b (local, mock)", "backend": "local", "max_query_chars": 4000,
            "allow_anonymous": True, "allow_registration": True}


def _session_body(email):
    return {"user_id": email, "role": "admin" if email.startswith("admin") else "public",
            "tenant_id": "default", "authenticated": True, "via": "session"}


@app.get("/whoami")
def whoami(x_api_key: str | None = Header(default=None), rag_session: str | None = Cookie(default=None)):
    if x_api_key and x_api_key != "demo":
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    if x_api_key:
        return {"user_id": "demo-user", "role": "customer", "tenant_id": "default", "authenticated": True, "via": "api_key"}
    if rag_session:
        return _session_body(rag_session)
    return {"user_id": "anonymous", "role": "public", "tenant_id": "default", "authenticated": False, "via": "anonymous"}


class Credentials(BaseModel):
    email: str
    password: str


@app.post("/auth/register")
@app.post("/auth/login")
def mock_login(creds: Credentials):
    if "@" not in creds.email or len(creds.password) < 8:
        return JSONResponse(status_code=401, content={"detail": "Wrong email or password."})
    response = JSONResponse(content=_session_body(creds.email.lower()))
    response.set_cookie("rag_session", creds.email.lower(), httponly=True, samesite="strict")
    return response


@app.post("/auth/logout")
def mock_logout():
    response = JSONResponse(content={"user_id": "anonymous", "role": "public", "tenant_id": "default",
                                     "authenticated": False, "via": "anonymous"})
    response.delete_cookie("rag_session")
    return response


@app.post("/chat")
def chat(req: ChatRequest):
    time.sleep(0.6)
    q = req.query.lower()
    base = {"request_id": "mock", "latency_ms": 600}
    if "ignore" in q:
        return {**base, "response": "Sorry, I can't help with that request.", "sources": [], "citations": {}, "blocked": True}
    if "error" in q:
        return JSONResponse(status_code=503, content={**base, "response": "The assistant is temporarily unavailable. "
                            "Please try again, or ask to be connected to a human agent.", "sources": [],
                            "citations": {}, "blocked": True})
    text, cites = ANSWERS[pick(q)]
    return {**base, "response": text, "sources": list(dict.fromkeys(cites.values())), "citations": cites, "blocked": False}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
