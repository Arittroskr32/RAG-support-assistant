"""Validates the rich blocks the generator may emit (after L8 has screened the full text).

- ```chart blocks: parsed as JSON and rebuilt from a strict whitelist (type, title, labels,
  datasets[label, data]). Nothing else survives — no chart.js options, callbacks or
  plugins — so model output can't smuggle behaviour into the browser. Invalid charts are
  replaced by a short note.
- ```mermaid blocks: size-limited; `%%{init}` directives and `click` handlers are removed
  (the UI also renders Mermaid with securityLevel "strict").
- Markdown tables are counted (the UI renders and sanitizes them).
- Small local models often drop the language tag (```\nflowchart TD) or put it on the next
  line (```\nmermaid\n...). Such blocks are labelled first, so they're validated like the rest.
"""
import json
import math
import re

CHART_TYPES = {"bar", "line", "pie", "doughnut"}
MAX_LABELS, MAX_DATASETS, MAX_LABEL_CHARS, MAX_MERMAID_CHARS = 50, 6, 80, 4000

_FENCE = re.compile(r"```[ \t]*(chart|mermaid)[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.MULTILINE)
_MERMAID_BAD = re.compile(r"^\s*(%%\{.*?\}%%|click\s.*)$", re.MULTILINE | re.IGNORECASE)
_FENCE_OPEN = re.compile(r"^(\s*)```[ \t]*([\w-]*)[ \t]*$")
_FENCE_CLOSE = re.compile(r"^\s*```\s*$")
_MERMAID_START = re.compile(r"^(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(-v2)?|erDiagram|"
                            r"gantt|journey|mindmap|timeline)\b")


def _guess_language(block: list[str]) -> tuple[str, list[str]]:
    """('mermaid' | 'chart' | '', block without a language line) for an untagged fence."""
    body = [l for l in block if l.strip()]
    if not body:
        return "", block
    first = body[0].strip()
    if first.lower() in ("mermaid", "chart"):
        return first.lower(), block[block.index(body[0]) + 1:]
    if _MERMAID_START.match(first):
        return "mermaid", block
    joined = "\n".join(body)
    if first.startswith("{") and '"datasets"' in joined:
        return "chart", block
    return "", block


def label_untagged_fences(text: str) -> str:
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        m = _FENCE_OPEN.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not _FENCE_CLOSE.match(lines[j]):
            j += 1
        block, opening = lines[i + 1:j], lines[i]
        if not m.group(2):
            lang, block = _guess_language(block)
            if lang:
                opening = f"{m.group(1)}```{lang}"
        out.append(opening)
        out.extend(block)
        if j < len(lines):
            out.append(lines[j])
        i = j + 1
    return "\n".join(out)


def _num(v):
    if isinstance(v, bool):
        raise ValueError("bool is not a number")
    if isinstance(v, str):
        v = float(v.replace(",", "").replace("$", "").replace("%", "").strip())
    v = float(v)
    if not math.isfinite(v):
        raise ValueError("non-finite")
    return int(v) if v.is_integer() else round(v, 6)


def _text(v, limit=MAX_LABEL_CHARS) -> str:
    return re.sub(r"[<>`]", "", str(v)).strip()[:limit]


def validate_chart(raw: str) -> dict:
    spec = json.loads(raw)
    if not isinstance(spec, dict):
        raise ValueError("chart must be a JSON object")
    ctype = str(spec.get("type", "bar")).lower()
    if ctype not in CHART_TYPES:
        raise ValueError(f"unsupported chart type {ctype!r}")
    labels = spec.get("labels")
    datasets = spec.get("datasets")
    if not isinstance(labels, list) or not 0 < len(labels) <= MAX_LABELS:
        raise ValueError("labels must be a non-empty list")
    if not isinstance(datasets, list) or not 0 < len(datasets) <= MAX_DATASETS:
        raise ValueError("datasets must be a non-empty list")
    clean_sets = []
    for ds in datasets:
        data = ds.get("data") if isinstance(ds, dict) else None
        if not isinstance(data, list) or len(data) != len(labels):
            raise ValueError("each dataset needs one number per label")
        clean_sets.append({"label": _text(ds.get("label", "")), "data": [_num(v) for v in data]})
    if ctype in ("pie", "doughnut"):
        clean_sets = clean_sets[:1]
    return {"type": ctype, "title": _text(spec.get("title", ""), 120),
            "labels": [_text(l) for l in labels], "datasets": clean_sets}


def clean_mermaid(src: str) -> str:
    src = _MERMAID_BAD.sub("", src).strip()
    if not src or len(src) > MAX_MERMAID_CHARS:
        raise ValueError("empty or oversized diagram")
    return src


def sanitize_rich_answer(text: str) -> tuple[str, dict]:
    """Returns (text with validated blocks, counts)."""
    text = label_untagged_fences(text)
    counts = {"charts": 0, "diagrams": 0, "tables": len(_TABLE_SEP.findall(text)), "dropped": 0}

    def _replace(m):
        kind, body = m.group(1).lower(), m.group(2)
        try:
            if kind == "chart":
                out = json.dumps(validate_chart(body), ensure_ascii=False)
                counts["charts"] += 1
            else:
                out = clean_mermaid(body)
                counts["diagrams"] += 1
            return f"```{kind}\n{out}\n```"
        except (ValueError, TypeError, json.JSONDecodeError):
            counts["dropped"] += 1
            return f"_({'chart' if kind == 'chart' else 'diagram'} omitted: the generated data was invalid)_"

    return _FENCE.sub(_replace, text), counts
