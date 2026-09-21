"""Per-user chat history, stored server-side so it is private to the account and follows
the user across browsers and devices.

- One JSON file per user under logs/chat_history/. The user_id (an email, or an API-key
  user id) is hashed into the filename, so the address never appears on disk and the name
  is always filesystem-safe.
- The role/tenant used to *answer* still comes from the pipeline; this module only stores
  the transcript the browser shows. It is only ever returned to the same authenticated
  user_id it was saved under, so one account can never read another's history.
- Writes are atomic (temp file + os.replace) and guarded by a lock, so a crash never leaves
  a half-written file and concurrent tabs can't corrupt each other.
"""
import hashlib
import json
import os
import threading

from config.settings import LOGS_DIR

HISTORY_DIR = LOGS_DIR / "chat_history"
MAX_CONVERSATIONS = 50
MAX_BYTES = 4_000_000   # ~4 MB of transcript per user is plenty; anything larger is rejected

_lock = threading.Lock()


def _path(user_id: str):
    digest = hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()[:32]
    return HISTORY_DIR / f"{digest}.json"


def load(user_id: str) -> list:
    """The user's saved conversations (newest first), or [] if they have none."""
    path = _path(user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def save(user_id: str, conversations) -> list:
    """Replace the user's stored conversations. Returns what was actually stored (capped)."""
    if not isinstance(conversations, list):
        conversations = []
    conversations = conversations[:MAX_CONVERSATIONS]
    payload = json.dumps(conversations, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise ValueError("history too large")
    with _lock:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = _path(user_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    return conversations


def clear(user_id: str) -> None:
    """Delete the user's stored history (used by 'Delete all chat history')."""
    with _lock:
        path = _path(user_id)
        if path.exists():
            path.unlink()
