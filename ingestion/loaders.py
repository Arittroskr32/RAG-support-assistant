"""Walks data/ and yields documents.

Layout: data/<document_type>/**/*.{md,txt}. The top-level folder is the document_type
(its clearance comes from knowledge_bases/rbac_policy.yaml). Optional YAML front-matter at
the top of a file overrides per-file metadata:

    ---
    title: Enterprise discount policy
    tenant_id: acme          # default: "default"
    clearance_level: 3       # may only RAISE the folder's clearance, never lower it
    trust: verified          # shown to the generator in L6; default "internal"
    ---
"""
import re
from pathlib import Path

import yaml

from config.settings import DATA_DIR

EXCLUDED_DIRS = {"security_datasets"}
SUPPORTED_SUFFIXES = {".md", ".txt"}
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[m.end():]


def _title_from(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


def load_documents(data_dir=DATA_DIR):
    root = Path(data_dir)
    for doc_type_dir in sorted(root.iterdir()):
        if not doc_type_dir.is_dir() or doc_type_dir.name in EXCLUDED_DIRS or doc_type_dir.name.startswith("."):
            continue
        for file_path in sorted(doc_type_dir.rglob("*")):
            if file_path.suffix.lower() not in SUPPORTED_SUFFIXES or file_path.name.startswith("."):
                continue
            meta, body = parse_front_matter(load_text_file(file_path))
            rel = file_path.relative_to(root).as_posix()
            yield {
                "text": body,
                "document_type": doc_type_dir.name,
                "source_doc_id": rel,                          # internal only (audit log)
                "title": str(meta.get("title") or _title_from(body, file_path)),
                "tenant_id": str(meta.get("tenant_id", "default")),
                "clearance_override": meta.get("clearance_level"),
                "trust": str(meta.get("trust", "internal")),
            }
