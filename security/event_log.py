"""Append-only JSONL logs: security events (every request's outcome, which layer blocked
it, scores, per-layer latency) and the L5 retrieval audit.

Queries are stored as a SHA-256 hash plus a short prefix, never in full, so the log
itself doesn't become a store of user PII. Every record carries the request_id so a block,
its retrieval audit entry, and the API response can be correlated.
"""
import hashlib
import json
import threading
import time

from config.settings import LOGS_DIR

SECURITY_EVENTS_PATH = LOGS_DIR / "security_events.jsonl"
RETRIEVAL_AUDIT_PATH = LOGS_DIR / "retrieval_audit.jsonl"

_lock = threading.Lock()


def query_fingerprint(query: str) -> dict:
    return {"query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "query_prefix": query[:40]}


def _append(path, record: dict) -> None:
    record = {"ts": time.time(), **record}
    line = json.dumps(record, default=str)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def log_security_event(record: dict) -> None:
    _append(SECURITY_EVENTS_PATH, record)


def log_retrieval(record: dict) -> None:
    _append(RETRIEVAL_AUDIT_PATH, record)
