"""Walks data/ and yields documents.

Layout: data/<document_type>/**/<file>. The top-level folder is the document_type (its
clearance comes from knowledge_bases/rbac_policy.yaml). A folder may hold any mix of:

    .md .markdown .txt   text as-is (Markdown headings drive chunking)
    .pdf                 text layer, one "## Page N" section per page (scanned PDFs without
                         a text layer are skipped with a warning: they would need OCR)
    .csv .tsv            one record per row, written as "column: value" lines
    .json                a list of objects -> one record each; a single object -> one record
    .jsonl               one record per line
Every format ends up as Markdown-like text, so chunking, the ingestion-time injection scan
and the RBAC tagging are the same for all of them. Records with question/answer fields
become "Q: ... / A: ..." pairs, so FAQ chunking keeps each pair together. Other files are
listed as skipped rather than silently ignored.

Per-file metadata overrides (all optional):

    ---
    title: Enterprise discount policy
    tenant_id: acme          # default: "default"
    clearance_level: 3       # may only RAISE the folder's clearance, never lower it
    trust: verified          # shown to the generator in L6; default "internal"
    ---
Text files take this as YAML front-matter at the top. Any file (e.g. a PDF or CSV) can use
a sidecar next to it instead: prices.csv -> prices.csv.meta.yaml (front-matter wins).
"""
import csv
import io
import json
import logging
import re
from pathlib import Path

import yaml

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = {"security_datasets"}
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".csv", ".tsv", ".json", ".jsonl"}
SIDECAR_SUFFIX = ".meta.yaml"
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_QUESTION_KEYS, _ANSWER_KEYS = ("question", "q", "query"), ("answer", "a", "response")


class UnreadableDocument(ValueError):
    """The file is a supported type but has no usable text (e.g. a scanned PDF)."""


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="ignore")


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


# ------------------------------------------------------------------ records (CSV / JSON)

def _flatten(value, prefix: str = "") -> list[tuple[str, str]]:
    """Nested JSON -> [("a.b", "value"), ("items.1.name", "x")]; empty values are dropped."""
    if isinstance(value, dict):
        return [kv for k, v in value.items() for kv in _flatten(v, f"{prefix}.{k}" if prefix else str(k))]
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            joined = ", ".join(str(v) for v in value if v not in (None, ""))
            return [(prefix, joined)] if joined else []
        return [kv for i, v in enumerate(value, 1) for kv in _flatten(v, f"{prefix}.{i}" if prefix else str(i))]
    if value is None or str(value).strip() == "":
        return []
    return [(prefix or "value", str(value).strip())]


def record_to_text(record) -> str:
    """One record as text. question/answer fields become a Q:/A: pair (other fields follow)."""
    if not isinstance(record, dict):
        return "\n".join(f"{k}: {v}" if k != "value" else v for k, v in _flatten(record))
    lower = {str(k).strip().lower(): k for k in record}
    q = next((lower[k] for k in _QUESTION_KEYS if k in lower), None)
    a = next((lower[k] for k in _ANSWER_KEYS if k in lower), None)
    lines = []
    if q is not None and a is not None and str(record[q]).strip():
        lines += [f"Q: {str(record[q]).strip()}", f"A: {str(record[a]).strip()}"]
        record = {k: v for k, v in record.items() if k not in (q, a)}
    lines += [f"{k}: {v}" for k, v in _flatten(record)]
    return "\n".join(lines)


def records_to_text(records) -> str:
    """Records separated by blank lines, so the chunker packs whole records together."""
    return "\n\n".join(t for t in (record_to_text(r) for r in records) if t.strip())


def _read_csv(path: Path) -> str:
    raw = load_text_file(path)
    if path.suffix.lower() == ".tsv":
        dialect = csv.excel_tab
    else:
        try:
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
    rows = csv.DictReader(io.StringIO(raw), dialect=dialect)
    return records_to_text({k.strip(): v for k, v in row.items() if k} for row in rows)


def _read_json(path: Path) -> str:
    data = json.loads(load_text_file(path))
    return records_to_text(data if isinstance(data, list) else [data])


def _read_jsonl(path: Path) -> str:
    records = []
    for n, line in enumerate(load_text_file(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("%s line %d is not valid JSON — skipped", path, n)
    return records_to_text(records)


# ------------------------------------------------------------------ PDF

def _read_pdf(path: Path) -> tuple[str, dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(i, (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages, 1)]
    pages = [(i, t) for i, t in pages if t]
    if not pages:
        raise UnreadableDocument("no text layer (scanned PDF? it would need OCR)")
    meta = {}
    title = (reader.metadata or {}).get("/Title") if reader.metadata else None
    if title and str(title).strip():
        meta["title"] = str(title).strip()
    return "\n\n".join(f"## Page {i}\n\n{t}" for i, t in pages), meta


# ------------------------------------------------------------------ dispatch

def read_document(path: Path) -> tuple[dict, str]:
    """(metadata, text) for one supported file. Metadata: sidecar < PDF info < front-matter."""
    suffix = path.suffix.lower()
    meta = {}
    sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
    if sidecar.exists():
        loaded = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            meta.update(loaded)
    if suffix in TEXT_SUFFIXES:
        front, text = parse_front_matter(load_text_file(path))
        meta.update(front)
    elif suffix == ".pdf":
        text, pdf_meta = _read_pdf(path)
        meta = {**pdf_meta, **meta}          # an explicit sidecar title beats the PDF's own
    elif suffix in (".csv", ".tsv"):
        text = _read_csv(path)
    elif suffix == ".json":
        text = _read_json(path)
    elif suffix == ".jsonl":
        text = _read_jsonl(path)
    else:
        raise ValueError(f"unsupported file type {suffix}")
    if not text.strip():
        raise UnreadableDocument("no text")
    return meta, text


def load_documents(data_dir=DATA_DIR, skipped: list | None = None):
    """Yields one dict per readable file. Files that are skipped (unsupported type, no text,
    parse error) are appended to `skipped` as (relative path, reason) when a list is given."""
    root = Path(data_dir)
    skipped = skipped if skipped is not None else []
    for doc_type_dir in sorted(root.iterdir()):
        if not doc_type_dir.is_dir() or doc_type_dir.name in EXCLUDED_DIRS or doc_type_dir.name.startswith("."):
            continue
        for file_path in sorted(doc_type_dir.rglob("*")):
            rel = file_path.relative_to(root).as_posix()
            if (not file_path.is_file() or any(p.startswith(".") for p in file_path.relative_to(root).parts)
                    or file_path.name.endswith(SIDECAR_SUFFIX)):
                continue
            if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                skipped.append((rel, f"unsupported type {file_path.suffix or '(none)'}"))
                continue
            try:
                meta, body = read_document(file_path)
            except Exception as e:   # one bad file must not stop the whole build
                skipped.append((rel, f"{type(e).__name__}: {e}"))
                continue
            yield {
                "text": body,
                "document_type": doc_type_dir.name,
                "source_doc_id": rel,                          # internal only (audit log)
                "format": file_path.suffix.lower().lstrip("."),
                "title": str(meta.get("title") or _title_from(body, file_path)),
                "tenant_id": str(meta.get("tenant_id", "default")),
                "clearance_override": meta.get("clearance_level"),
                "trust": str(meta.get("trust", "internal")),
            }
