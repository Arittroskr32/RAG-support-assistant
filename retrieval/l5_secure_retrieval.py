"""L5: secure retrieval over KB-4.

- Hard pre-filter applied inside the vector search (never post-filtered):
  clearance_level <= user clearance, document_type in allowed types, tenant match, and
  quarantined == False (chunks flagged by ingestion-time scanning).
- Reuses the query embedding computed in L1 (no second encode).
- Drops results whose distance exceeds cfg.retrieval_max_distance (irrelevant context
  encourages hallucination); the orchestrator skips generation when nothing is left.
- Optionally re-scans retrieved chunks with L2 before they reach the generator.
- Every search is audit-logged (request id, user, role, tenant, scope, query hash,
  result ids, distances, dropped ids).
"""
from dataclasses import dataclass

from config.settings import get_thresholds
from knowledge_bases.kb_manager import kb
from security import l2_pattern_filter
from security.event_log import log_retrieval, query_fingerprint


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    metadata: dict
    distance: float


def build_where(scope, tenant_id: str) -> dict:
    conditions = [{"quarantined": {"$eq": False}}]
    if scope.rbac_enforced:
        conditions += [
            {"clearance_level": {"$lte": scope.clearance}},
            {"document_type": {"$in": list(scope.allowed_types)}},
            {"tenant_id": {"$eq": tenant_id}},
        ]
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def secure_search(query_emb: list[float], scope, tenant_id: str = "default", cfg=None,
                  user_id: str = "anon", request_id: str = "", query: str = "") -> list[RetrievedChunk]:
    cfg = cfg or get_thresholds()
    results: list[RetrievedChunk] = []
    if scope.allowed_types and kb.kb4_documents.count() > 0:
        res = kb.kb4_documents.query(query_embeddings=[query_emb], n_results=cfg.retrieval_top_k,
                                     where=build_where(scope, tenant_id),
                                     include=["documents", "metadatas", "distances"])
        for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
            results.append(RetrievedChunk(cid, doc, meta, dist))

    too_far = [r for r in results if r.distance > cfg.retrieval_max_distance]
    results = [r for r in results if r.distance <= cfg.retrieval_max_distance]
    rescan_dropped = []
    if cfg.enable_retrieval_rescan:
        rescan_dropped = [r for r in results if l2_pattern_filter.matches_known_injection(r.text, extended=True)]
        results = [r for r in results if r not in rescan_dropped]

    log_retrieval({
        "request_id": request_id, "user_id": user_id, "role": scope.role, "tenant_id": tenant_id,
        "clearance": scope.clearance, "allowed_types": scope.allowed_types, "intent": scope.intent,
        "rbac_enforced": scope.rbac_enforced, **query_fingerprint(query),
        "result_ids": [r.chunk_id for r in results],
        "distances": [round(r.distance, 4) for r in results],
        "dropped_irrelevant": [r.chunk_id for r in too_far],
        "dropped_rescan": [r.chunk_id for r in rescan_dropped],
    })
    return results
