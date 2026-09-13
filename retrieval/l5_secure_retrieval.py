import json
import time
from pathlib import Path

from knowledge_bases.kb_manager import kb

AUDIT_LOG_PATH = Path("logs/retrieval_audit.jsonl")
AUDIT_LOG_PATH.parent.mkdir(exist_ok=True)


def secure_search(query: str, clearance: int, allowed_types: list, tenant_id="default", top_k=6, user_id="anon"):
    query_emb = kb.embed(query)[0]
    where_filter = {"$and": [
        {"clearance_level": {"$lte": clearance}},
        {"document_type": {"$in": allowed_types}},
        {"tenant_id": {"$eq": tenant_id}},
    ]}
    results = kb.kb4_documents.query(query_embeddings=[query_emb], n_results=top_k, where=where_filter)

    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps({"ts": time.time(), "user_id": user_id, "clearance": clearance,
                             "allowed_types": allowed_types,
                             "result_ids": results.get("ids", [[]])[0]}) + "\n")

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    return list(zip(docs, metas))

# NOTE: check the `where` filter syntax against the installed `chromadb` version — Chroma's
# operator support ($and, $in, $lte) has changed across releases; pin a version and verify
# with a quick unit test.
