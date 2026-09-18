"""Server-side identity: API key -> (user_id, role, tenant_id).

Keys are stored only as SHA-256 hashes in config/api_keys.yaml (gitignored). Create one
with:  python -m api.create_api_key --user-id alice --role customer [--tenant-id acme]

The role and tenant used for RBAC always come from here — never from the request body.
"""
import hashlib
import hmac
import threading
from dataclasses import dataclass

import yaml

from config.settings import API_SETTINGS
from knowledge_bases.kb3_rbac import known_roles


@dataclass(frozen=True)
class Identity:
    user_id: str
    role: str
    tenant_id: str
    authenticated: bool
    via: str = "anonymous"   # "api_key" | "session" (browser account, api/accounts.py) | "anonymous"


ANONYMOUS = Identity(user_id="anonymous", role="public", tenant_id="default", authenticated=False)

_cache: dict = {"mtime": None, "by_hash": {}}
_lock = threading.Lock()


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def load_key_store(path=None) -> dict[str, Identity]:
    """Reloads automatically when the file changes (new keys work without a restart)."""
    path = path or API_SETTINGS.api_keys_file
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    with _lock:
        if _cache["mtime"] != mtime:
            raw = yaml.safe_load(path.read_text()) or {}
            roles = set(known_roles())
            by_hash = {}
            for entry in raw.get("users", []):
                if entry["role"] not in roles:
                    raise ValueError(f"{path}: user {entry['user_id']!r} has unknown role {entry['role']!r}")
                by_hash[entry["key_sha256"]] = Identity(entry["user_id"], entry["role"],
                                                        entry.get("tenant_id", "default"), True, "api_key")
            _cache.update(mtime=mtime, by_hash=by_hash)
        return _cache["by_hash"]


def authenticate(api_key: str | None) -> Identity | None:
    """Returns the Identity, ANONYMOUS when no key is given and anonymous access is
    allowed, or None when the caller must be rejected (401)."""
    if not api_key:
        return ANONYMOUS if API_SETTINGS.allow_anonymous else None
    candidate = hash_key(api_key)
    for stored_hash, identity in load_key_store().items():
        if hmac.compare_digest(candidate, stored_hash):
            return identity
    return None
