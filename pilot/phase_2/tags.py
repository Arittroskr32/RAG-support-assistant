"""The <!><query> ... <!query> and <!><passage> ... <!passage> wrappers.

Item files may store the question and the carrier document wrapped:

  "question":    "<!><query> How long does delivery outside Dhaka take? <!query>"
  "carrier_doc": "<!><passage> ## Delivery\nOutside Dhaka it takes 3-5 days. ... <!passage>"

The wrappers are a storage and embedding format only. load_items2() separates them from the
text as soon as an item is read (unwrap), so every script works on the plain text: the
document planted into data/ and the question sent to the pipeline are plain, and the LLM never
sees a wrapper. The retriever puts them back only where it embeds text with E5 in the tagged
style (bn_route, --e5-prefix tagged), and removes any stray marker from retrieved chunks and
questions before they go on to the LLM.
"""
from __future__ import annotations

import re

OPEN = {"query": "<!><query>", "passage": "<!><passage>"}
CLOSE = {"query": "<!query>", "passage": "<!passage>"}
# any of the four markers, tolerant of case and inner spaces ("<! > < query >")
MARKER = re.compile(r"<\s*!\s*>\s*<\s*(?:query|passage)\s*>|<\s*!\s*(?:query|passage)\s*>", re.I)


def wrap(text: str, kind: str) -> str:
    """A question goes on one line; a document gets the markers on lines of their own."""
    if kind == "passage":
        return f"{OPEN[kind]}\n{text.strip()}\n{CLOSE[kind]}"
    return f"{OPEN[kind]} {text.strip()} {CLOSE[kind]}"


def is_wrapped(text: str, kind: str) -> bool:
    t = (text or "").strip()
    return t.startswith(OPEN[kind]) and t.endswith(CLOSE[kind])


def strip_markers(text: str) -> str:
    """Remove every wrapper marker wherever it appears."""
    return MARKER.sub("", text or "")


def unwrap(text: str, kind: str) -> str:
    """The text without its outer wrapper. Text that is not wrapped comes back unchanged
    (apart from stray markers, which are removed)."""
    t = (text or "").strip()
    if is_wrapped(t, kind):
        t = t[len(OPEN[kind]):len(t) - len(CLOSE[kind])].strip("\n ")
        return strip_markers(t)
    return strip_markers(text) if MARKER.search(text or "") else text


def problems(text: str, kind: str) -> list[str]:
    """Format problems in one field: a marker without its partner, the wrong kind of wrapper,
    or a marker inside the text."""
    t = (text or "").strip()
    out = []
    if not MARKER.search(t):
        return out
    other = "passage" if kind == "query" else "query"
    if t.startswith(OPEN[other]) or t.endswith(CLOSE[other]):
        out.append(f"uses the <{other}> wrapper; this field takes {OPEN[kind]} ... {CLOSE[kind]}")
    elif not t.startswith(OPEN[kind]):
        out.append(f"has a marker but does not start with {OPEN[kind]}")
    elif not t.endswith(CLOSE[kind]):
        out.append(f"starts with {OPEN[kind]} but does not end with {CLOSE[kind]}")
    inner = t[len(OPEN[kind]):len(t) - len(CLOSE[kind])] if is_wrapped(t, kind) else t
    if not out and MARKER.search(inner):
        out.append("has a wrapper marker inside the text (only one pair, at the very start and end)")
    return out
