"""Stamps each chunk with its RBAC/tenant metadata. Clearance comes from
knowledge_bases/rbac_policy.yaml (the same source L4/L5 read), so they can't drift."""
import hashlib

from knowledge_bases.kb3_rbac import clearance_for_type


def make_chunk_id(source_doc_id: str, index: int, chunk_text: str) -> str:
    """Hash of path + position + full text: unique even when two chunks share a prefix."""
    return hashlib.sha256(f"{source_doc_id}\x00{index}\x00{chunk_text}".encode("utf-8")).hexdigest()[:24]


def tag_chunk(chunk_text: str, document_type: str, source_doc_id: str, index: int = 0,
              tenant_id: str = "default", title: str = "", trust: str = "internal",
              clearance_override=None) -> dict:
    clearance = clearance_for_type(document_type)
    if clearance_override is not None:
        clearance = max(clearance, int(clearance_override))   # front-matter may only raise it
    return {
        "chunk_id": make_chunk_id(source_doc_id, index, chunk_text),
        "chunk_text": chunk_text,
        "document_type": document_type,
        "clearance_level": clearance,
        "tenant_id": tenant_id,
        "source_doc_id": source_doc_id,
        "title": title or source_doc_id,
        "trust": trust,
        "quarantined": False,
        "quarantine_reason": "",
    }
