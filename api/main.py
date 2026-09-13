from fastapi import FastAPI
from pydantic import BaseModel

from pipeline.orchestrator import handle_request

app = FastAPI(title="Secure RAG Support Assistant")


class ChatRequest(BaseModel):
    query: str
    user_id: str
    role: str = "public"
    tenant_id: str = "default"


@app.post("/chat")
def chat(req: ChatRequest, request_ip: str = "0.0.0.0", session_id: str = "session-1"):
    return handle_request(query=req.query, user_id=req.user_id, role=req.role,
                           ip=request_ip, session_id=session_id, tenant_id=req.tenant_id)
