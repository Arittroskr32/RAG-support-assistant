"""L6: wraps retrieved chunks as clearly-delimited DATA for the generator.

- Delimiters carry a random per-request nonce (<document-3f9a1c ...>), so text inside a
  chunk — or the user's question — can't forge or close a block: the attacker can't
  guess the tag name.
- Any tag-like text resembling a delimiter (<document…>, </user_question…>, legacy
  [DOCUMENT]/[/DOCUMENT]) is stripped from chunk text and the user question anyway.
- The trust label comes from chunk metadata (front-matter `trust:`), not a constant.
"""
import re
import secrets
from dataclasses import dataclass, field

_TAG_LIKE = re.compile(r"</?\s*(?:documents?|user_question)[^>]*>|\[/?\s*document\b[^\]]*\]", re.IGNORECASE)


def new_nonce() -> str:
    return secrets.token_hex(4)


def sanitize(text: str) -> str:
    return _TAG_LIKE.sub("[removed-tag]", text)


def _attr(value: str) -> str:
    return sanitize(str(value)).replace('"', "'").replace("\n", " ")[:120]


@dataclass
class AssembledContext:
    text: str
    nonce: str
    citations: dict = field(default_factory=dict)   # "c1" -> chunk_id
    tagged: bool = True


def tag_context(retrieved, nonce: str | None = None) -> AssembledContext:
    """`retrieved` is a list of RetrievedChunk (or (text, metadata) tuples)."""
    nonce = nonce or new_nonce()
    blocks, citations = [], {}
    for i, item in enumerate(retrieved, start=1):
        text, meta, chunk_id = _unpack(item)
        cid = f"c{i}"
        citations[cid] = chunk_id
        blocks.append(
            f'<document-{nonce} citation="{cid}" title="{_attr(meta.get("title", "untitled"))}" '
            f'trust="{_attr(meta.get("trust", "internal"))}">\n{sanitize(text)}\n</document-{nonce}>')
    return AssembledContext("\n\n".join(blocks), nonce, citations)


def raw_context(retrieved) -> AssembledContext:
    """L6 disabled (ablation): chunks concatenated with no tags or sanitization."""
    parts, citations = [], {}
    for i, item in enumerate(retrieved, start=1):
        text, _, chunk_id = _unpack(item)
        citations[f"c{i}"] = chunk_id
        parts.append(text)
    return AssembledContext("\n\n".join(parts), "", citations, tagged=False)


def _unpack(item):
    if hasattr(item, "text"):
        return item.text, item.metadata, item.chunk_id
    text, meta = item
    return text, meta, meta.get("chunk_id", meta.get("source_doc_id", "unknown"))
