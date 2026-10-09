"""Server-side provenance for KB-4: which tenant owns a file and how much the generator
should trust it. Both come from config/ingestion_sources.yaml, keyed by where the file sits
under data/, never from the file itself: a file's front-matter or sidecar could otherwise
put itself in another tenant's results (tenant_id is the L5 isolation boundary) or label
itself "verified" in the L6 context.

The most specific matching path wins (a file, or a folder on a "/" boundary); files no
entry covers get `defaults`. The file is validated at load and a bad entry fails the
build, like rbac_policy.yaml.
"""
import re
from functools import lru_cache
from pathlib import Path

import yaml

from config.settings import CONFIG_DIR

SOURCES_YAML = CONFIG_DIR / "ingestion_sources.yaml"
TRUST_LEVELS = ("external", "internal", "verified")
FILE_CONTROLLED_KEYS = ("tenant_id", "trust")    # ignored when a file sets them
_TENANT_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_BUILTIN_DEFAULTS = {"tenant_id": "default", "trust": "internal"}


class SourcePolicyError(ValueError):
    pass


def _check(entry: dict, where: str) -> dict:
    tenant, trust = str(entry["tenant_id"]), str(entry["trust"])
    if not _TENANT_ID.fullmatch(tenant):
        raise SourcePolicyError(f"{where}: invalid tenant_id {tenant!r}")
    if trust not in TRUST_LEVELS:
        raise SourcePolicyError(f"{where}: trust {trust!r} is not one of {', '.join(TRUST_LEVELS)}")
    return {"tenant_id": tenant, "trust": trust}


def validate_sources(raw) -> dict:
    """Parsed YAML -> {"defaults": {...}, "sources": {path: {...}}}. Raises on bad entries."""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise SourcePolicyError("ingestion sources must be a mapping")
    defaults = _check({**_BUILTIN_DEFAULTS, **(raw.get("defaults") or {})}, "defaults")
    sources = {}
    for i, entry in enumerate(raw.get("sources") or []):
        if not isinstance(entry, dict) or not str(entry.get("path", "")).strip("/ "):
            raise SourcePolicyError(f"sources[{i}]: needs a non-empty path")
        path = str(entry["path"]).strip().strip("/")
        if ".." in Path(path).parts:
            raise SourcePolicyError(f"sources[{i}]: path {path!r} may not contain '..'")
        if path in sources:
            raise SourcePolicyError(f"sources[{i}]: duplicate path {path!r}")
        sources[path] = _check({**defaults, **entry}, f"sources[{i}] ({path})")
    return {"defaults": defaults, "sources": sources}


@lru_cache(maxsize=1)
def load_sources(path: Path = SOURCES_YAML) -> dict:
    if not Path(path).exists():
        return validate_sources({})
    return validate_sources(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def provenance_for(rel_path: str, sources: dict | None = None) -> dict:
    """{"tenant_id", "trust"} for a file at data/<rel_path>."""
    sources = sources or load_sources()
    rel_path = rel_path.strip("/")
    matches = [p for p in sources["sources"] if rel_path == p or rel_path.startswith(p + "/")]
    if not matches:
        return dict(sources["defaults"])
    return dict(sources["sources"][max(matches, key=len)])
