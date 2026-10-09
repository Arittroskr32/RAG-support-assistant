"""(Re)build KB-4 from data/. Safe to re-run any time data/ changes: the collection is
dropped and rebuilt, so edited and deleted files never leave stale chunks behind.

Document text and titles are first cleaned of invisible characters (security.text_sanitiser),
so the stored, scanned and embedded text is what the generator will see.

Every chunk is scanned for indirect prompt injection before it is indexed: L2 (including
the extended "ignore previous instructions" patterns, which are a strong signal inside a
*document*), L2b (KB-6 narrative archetypes) and, with --with-l3, the fine-tuned guardrail.
Flagged chunks are stored with quarantined=True, which L5 always filters out, and listed
in logs/quarantine_report.jsonl for review.

    python -m ingestion.build_kb4 [--with-l3] [--no-scan] [--no-sanitise]
"""
import argparse
import json
from collections import Counter

from config.settings import DATA_DIR, LOGS_DIR, get_thresholds
from ingestion.chunkers import chunk_document
from ingestion.loaders import load_documents
from ingestion.metadata_tagger import tag_chunk
from knowledge_bases.kb_manager import kb
from security import l2_pattern_filter, l2b_narrative_guard
from security.text_sanitiser import sanitise_text

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


def collect_chunks(data_dir=DATA_DIR, skipped: list | None = None, formats: Counter | None = None,
                   sanitise: bool = True, sources: dict | None = None,
                   ignored: list | None = None) -> list[dict]:
    chunks = []
    for doc in load_documents(data_dir, skipped, sources):
        if formats is not None:
            formats[doc["format"]] += 1
        if ignored is not None and doc["ignored_metadata"]:
            ignored.append((doc["source_doc_id"], doc["ignored_metadata"]))
        text, title = doc["text"], doc["title"]
        if sanitise:
            text, title = sanitise_text(text), sanitise_text(title)
        for i, raw in enumerate(chunk_document(text, doc["document_type"], title)):
            chunks.append(tag_chunk(raw, doc["document_type"], doc["source_doc_id"], index=i,
                                    tenant_id=doc["tenant_id"], title=title, trust=doc["trust"],
                                    clearance_override=doc["clearance_override"]))
    return chunks


def build(data_dir=DATA_DIR, scan: bool = True, with_l3: bool = False, sanitise: bool = True,
          sources: dict | None = None):
    cfg = get_thresholds()
    skipped, formats, ignored = [], Counter(), []
    chunks = collect_chunks(data_dir, skipped, formats, sanitise, sources=sources, ignored=ignored)
    for rel, reason in skipped:
        print(f"  skipped data/{rel}: {reason}")
    for rel, keys in ignored:
        print(f"  ignored {', '.join(keys)} in data/{rel} (set in config/ingestion_sources.yaml)")
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
    files = ", ".join(f"{n} {fmt}" for fmt, n in sorted(formats.items()))
    print(f"KB-4 rebuilt with {len(chunks)} chunks from {sum(formats.values())} files ({files}) in {data_dir} "
          f"({len(quarantined)} quarantined — see {QUARANTINE_REPORT.relative_to(QUARANTINE_REPORT.parents[1])}).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-l3", action="store_true", help="also scan chunks with the fine-tuned guardrail (slow)")
    ap.add_argument("--no-scan", action="store_true", help="skip ingestion-time injection scanning (ablation)")
    ap.add_argument("--no-sanitise", action="store_true", help="keep invisible characters in documents (ablation)")
    args = ap.parse_args()
    build(scan=not args.no_scan, with_l3=args.with_l3, sanitise=not args.no_sanitise)
