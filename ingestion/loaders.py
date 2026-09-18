"""Walks data/ and yields documents.

Layout: data/<document_type>/**/<file>. The top-level folder is the document_type (its
clearance comes from knowledge_bases/rbac_policy.yaml). A folder may hold any mix of:

    .md .markdown .txt   text as-is (Markdown headings drive chunking)
    .pdf                 text layer, one "## Page N" section per page (scanned PDFs without
                         a text layer are skipped with a warning: they would need OCR)
    .csv .tsv            one record per row, written as "column: value" lines
    .json                a list of objects -> one record each; a single object -> one record
    .jsonl               one record per line
    .docx                Word: headings -> sections, list items -> "- ", tables -> records
    .xlsx .xlsm .xls     Excel: every sheet (a section each when there are several); the first
                         non-empty row is the header, every other row a "column: value" record
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
from datetime import date, datetime, time
from pathlib import Path

import yaml

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = {"security_datasets"}
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".csv", ".tsv", ".json", ".jsonl", ".docx", ".xlsx", ".xlsm", ".xls"}
# Older binary formats: tell the user how to make them readable instead of just "unsupported".
CONVERT_HINTS = {".doc": "save it as .docx", ".ppt": "save it as .pdf", ".pptx": "save it as .pdf",
                 ".odt": "save it as .docx", ".ods": "save it as .xlsx", ".rtf": "save it as .docx"}
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


# ------------------------------------------------------------------ tables (Excel / Word)

def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value).strip()


def rows_to_text(rows) -> str:
    """Table rows -> records. The first non-empty row is the header (blank or repeated names
    are made unique); a table with only one row is kept as plain text."""
    rows = [[_cell_text(c) for c in row] for row in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    if len(rows) == 1:
        return " | ".join(c for c in rows[0] if c)
    header, seen = [], {}
    for i, name in enumerate(rows[0], 1):
        name = name or f"column {i}"
        seen[name] = seen.get(name, 0) + 1
        header.append(name if seen[name] == 1 else f"{name} {seen[name]}")
    width = max(len(r) for r in rows)
    header += [f"column {i}" for i in range(len(header) + 1, width + 1)]
    return records_to_text({header[i]: v for i, v in enumerate(r) if v} for r in rows[1:])


def _join_sections(sections: list[tuple[str, str]]) -> str:
    """[(name, text)] -> text, with a "## name" heading only when there's more than one."""
    sections = [(n, t) for n, t in sections if t.strip()]
    if len(sections) == 1:
        return sections[0][1]
    return "\n\n".join(f"## {n}\n\n{t}" for n, t in sections)


def _read_xlsx(path: Path) -> tuple[str, dict]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)   # data_only: formula results, not formulas
    try:
        sections = [(ws.title, rows_to_text(ws.iter_rows(values_only=True))) for ws in wb.worksheets]
        title = (wb.properties.title or "").strip()
    finally:
        wb.close()
    return _join_sections(sections), ({"title": title} if title else {})


def _read_xls(path: Path) -> tuple[str, dict]:
    import xlrd

    book = xlrd.open_workbook(str(path))

    def value(sheet, r, c):
        cell = sheet.cell(r, c)
        if cell.ctype == xlrd.XL_CELL_DATE:
            return xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
        return cell.value

    sections = [(sh.name, rows_to_text([value(sh, r, c) for c in range(sh.ncols)] for r in range(sh.nrows)))
                for sh in book.sheets()]
    return _join_sections(sections), {}


def _read_docx(path: Path) -> tuple[str, dict]:
    import docx
    from docx.table import Table

    document = docx.Document(str(path))
    parts = []
    for block in document.iter_inner_content():          # paragraphs and tables in document order
        if isinstance(block, Table):
            parts.append(rows_to_text([cell.text for cell in row.cells] for row in block.rows))
            continue
        text = block.text.strip()
        if not text:
            continue
        style = block.style.name if block.style is not None else ""
        heading = re.match(r"Heading (\d)", style)
        if style == "Title":
            text = f"# {text}"
        elif heading:
            text = f"{'#' * min(int(heading.group(1)) + 1, 6)} {text}"
        elif style.startswith("List"):
            text = f"- {text}"
        parts.append(text)
    title = (document.core_properties.title or "").strip()
    return "\n\n".join(p for p in parts if p), ({"title": title} if title else {})


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
    elif suffix in (".pdf", ".docx", ".xlsx", ".xlsm", ".xls"):
        reader = {".pdf": _read_pdf, ".docx": _read_docx, ".xls": _read_xls}.get(suffix, _read_xlsx)
        text, file_meta = reader(path)
        meta = {**file_meta, **meta}         # an explicit sidecar title beats the file's own
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
            suffix = file_path.suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                hint = f" ({CONVERT_HINTS[suffix]})" if suffix in CONVERT_HINTS else ""
                skipped.append((rel, f"unsupported type {file_path.suffix or '(none)'}{hint}"))
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
