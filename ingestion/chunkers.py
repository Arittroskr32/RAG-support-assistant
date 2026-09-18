"""Type-aware chunking.

all-MiniLM-L6-v2 only embeds the first 256 word-pieces of a text, so chunks are kept
under ~180 words (~230-250 word-pieces) — anything longer would be partly invisible to
retrieval. Each chunk is prefixed with "<document title> > <section heading>" so it
carries its context into the embedding.
"""
import re

MAX_CHUNK_WORDS = 180
OVERLAP_WORDS = 30

_QA_START = re.compile(r"^\s*Q\s*[:.]", re.IGNORECASE | re.MULTILINE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def chunk_qa_pairs(text: str) -> list[str]:
    """One chunk per Q/A pair, split at each line starting with 'Q:' so multi-paragraph
    answers stay attached to their question. Falls back to blank-line blocks for FAQ
    files that don't use the Q:/A: convention."""
    starts = [m.start() for m in _QA_START.finditer(text)]
    if not starts:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        return [c for b in blocks for c in (_pack([b], MAX_CHUNK_WORDS) if len(b.split()) > MAX_CHUNK_WORDS else [b])]
    starts.append(len(text))
    pairs = [text[a:b].strip() for a, b in zip(starts, starts[1:])]
    preamble = text[:starts[0]].strip()
    out = []
    for pair in pairs:
        out.extend(chunk_words(pair) if len(pair.split()) > MAX_CHUNK_WORDS else [pair])
    return ([preamble] if preamble and not preamble.startswith("#") else []) + out


def chunk_words(text: str, chunk_size: int = MAX_CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    """Sliding word window — the last resort for a single over-long paragraph."""
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        chunks.append(" ".join(words[start:start + chunk_size]))
        if start + chunk_size >= len(words):
            break
        start += chunk_size - overlap
    return chunks


def _split_sections(text: str) -> list[tuple[str, str]]:
    """[(heading, body)] split on Markdown headings."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [("", text)]
    sections = []
    if text[:matches[0].start()].strip():
        sections.append(("", text[:matches[0].start()]))
    for m, nxt in zip(matches, matches[1:] + [None]):
        body = text[m.end():nxt.start() if nxt else len(text)]
        sections.append((m.group(2).strip(), body))
    return sections


def _pack(units: list[str], max_words: int) -> list[str]:
    """Greedily packs paragraphs/sentences into chunks of <= max_words."""
    chunks, current, count = [], [], 0
    for unit in units:
        n = len(unit.split())
        if n > max_words:
            if current:
                chunks.append("\n\n".join(current))
                current, count = [], 0
            sentences = _SENTENCE.split(unit)
            if len(sentences) > 1:
                chunks.extend(_pack(sentences, max_words))
            else:
                chunks.extend(chunk_words(unit, max_words))
            continue
        if count + n > max_words and current:
            chunks.append("\n\n".join(current))
            current, count = [], 0
        current.append(unit)
        count += n
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_markdown(text: str, max_words: int = MAX_CHUNK_WORDS) -> list[tuple[str, str]]:
    """Heading-aware: section -> paragraphs -> sentences -> words. Returns [(heading, chunk)]."""
    out = []
    for heading, body in _split_sections(text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        for chunk in _pack(paragraphs, max_words):
            out.append((heading, chunk))
    return out


def chunk_document(text: str, document_type: str, title: str = "") -> list[str]:
    """Returns chunk texts, each prefixed with its title/heading breadcrumb."""
    if document_type == "public_faq":
        pieces = [("", c) for c in chunk_qa_pairs(text)]
    else:
        pieces = chunk_markdown(text)
    chunks = []
    for heading, body in pieces:
        crumb = " > ".join(dict.fromkeys(x for x in (title, heading) if x))
        chunks.append(f"{crumb}\n{body}" if crumb else body)
    return chunks
