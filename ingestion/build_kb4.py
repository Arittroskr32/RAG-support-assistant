"""(Re)build KB-4 from data/. Safe to re-run any time data/ changes: the collection is
dropped and rebuilt, so edited and deleted files never leave stale chunks behind.

Every chunk is scanned for indirect prompt injection before it is indexed: L2 (including
the extended "ignore previous instructions" patterns, which are a strong signal inside a
*document*), L2b (KB-6 narrative archetypes) and, with --with-l3, the fine-tuned guardrail.
Flagged chunks are stored with quarantined=True, which L5 always filters out, and listed
in logs/quarantine_report.jsonl for review.

    python -m ingestion.build_kb4 [--with-l3] [--no-scan]
"""
import argparse
import json

from config.settings import DATA_DIR, LOGS_DIR, get_thresholds
from ingestion.chunkers import chunk_document
from ingestion.loaders import load_documents
from ingestion.metadata_tagger import tag_chunk
from knowledge_bases.kb_manager import kb
from security import l2_pattern_filter, l2b_narrative_guard

QUARANTINE_REPORT = LOGS_DIR / "quarantine_report.jsonl"
METADATA_KEYS = ("document_type", "clearance_level", "tenant_id", "source_doc_id", "title", "trust",
                 "quarantined", "quarantine_reason")


def scan_chunk(text: str, cfg, with_l3: bool = False) -> str:
    """Returns a quarantine reason, or '' if the chunk looks clean."""
    pattern = l2_pattern_filter.match_injection(text, extended=True)
    if pattern:
        return f"L2:{pattern}"
    dist, archetype, category = l2b_narrative_guard.narrative_match(kb.embed_windows(text, cfg))
    if dist < cfg.narrative_match_threshold:
        return f"L2b:{archetype}({category}) d={dist:.3f}"
    if with_l3:
        from security import l3_llm_guardrail
        if l3_llm_guardrail.classify(text) == "unsafe":
            return "L3:unsafe"
    return ""


def collect_chunks(data_dir=DATA_DIR) -> list[dict]:
    chunks = []
    for doc in load_documents(data_dir):
        for i, raw in enumerate(chunk_document(doc["text"], doc["document_type"], doc["title"])):
            chunks.append(tag_chunk(raw, doc["document_type"], doc["source_doc_id"], index=i,
                                    tenant_id=doc["tenant_id"], title=doc["title"], trust=doc["trust"],
                                    clearance_override=doc["clearance_override"]))
    return chunks


def build(data_dir=DATA_DIR, scan: bool = True, with_l3: bool = False):
    cfg = get_thresholds()
    chunks = collect_chunks(data_dir)
    if not chunks:
        print("No documents found under", data_dir)
        return

    quarantined = []
    if scan:
        for c in chunks:
            reason = scan_chunk(c["chunk_text"], cfg, with_l3)
            if reason:
                c["quarantined"], c["quarantine_reason"] = True, reason
                quarantined.append(c)

    coll = kb.reset_collection("kb4_documents")
    kb.add_batched(coll, ids=[c["chunk_id"] for c in chunks], documents=[c["chunk_text"] for c in chunks],
                   embeddings=kb.embed([c["chunk_text"] for c in chunks]),
                   metadatas=[{k: c[k] for k in METADATA_KEYS} for c in chunks])

    QUARANTINE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(QUARANTINE_REPORT, "w", encoding="utf-8") as f:
        for c in quarantined:
            f.write(json.dumps({"chunk_id": c["chunk_id"], "source_doc_id": c["source_doc_id"],
                                "reason": c["quarantine_reason"], "text": c["chunk_text"][:300]}) + "\n")
    print(f"KB-4 rebuilt with {len(chunks)} chunks from {data_dir} "
          f"({len(quarantined)} quarantined — see {QUARANTINE_REPORT.relative_to(QUARANTINE_REPORT.parents[1])}).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-l3", action="store_true", help="also scan chunks with the fine-tuned guardrail (slow)")
    ap.add_argument("--no-scan", action="store_true", help="skip ingestion-time injection scanning (ablation)")
    args = ap.parse_args()
    build(scan=not args.no_scan, with_l3=args.with_l3)
