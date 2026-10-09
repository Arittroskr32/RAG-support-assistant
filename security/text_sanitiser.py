"""L0: strip invisible and formatting characters before text reaches detectors or the model.

Applied to the user question (pipeline/orchestrator.py, before L2), to every document
at ingestion (ingestion/build_kb4.py, before scanning and embedding) and again to
retrieved chunks in L6, so the detectors and the generator see the same text.

What is removed
  - Format characters (Unicode category Cf): zero-width space/joiners, word
    joiner, invisible math operators, BOM, soft hyphen, bidi embeddings,
    overrides, isolates and marks, interlinear annotation, tag characters
    (U+E0000-E007F, used for "ASCII smuggling").
  - Variation selectors (U+FE00-FE0F, U+E0100-E01EF), which can carry hidden
    bytes, the combining grapheme joiner, and Hangul filler characters.
  - C0/C1 control characters other than tab, newline and carriage return.

What is kept
  - ZWJ (U+200D) and ZWNJ (U+200C) when both neighbours are Bengali-script
    characters. Bangla uses them to control conjunct and ya-phala/reph
    rendering (e.g. র‍্য, ক্‌ষ), so removing them would change how legitimate
    Bangla renders. Anywhere else they are removed.

What is normalised
  - Exotic spaces (NBSP, en/em spaces, ideographic space, ...) become a plain
    space; line/paragraph separators become a newline.
  - The result is NFC-normalised. NFKC is deliberately not used: it is not
    needed for Bangla and folds characters the output validator may want to see.

``sanitise()`` returns the cleaned text and a report of what was removed, so the
"invisible characters present" signal can be logged in shadow mode instead of
being silently discarded.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field

ZWNJ = "‌"
ZWJ = "‍"

_BIDI = set(map(chr, [0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)]))
_INVISIBLE_NON_CF = set(
    map(chr, [0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)])
)
_KEPT_CONTROLS = {"\t", "\n", "\r"}
_LINE_SEPARATORS = {" ", " ", "\x85"}


def _is_bengali(ch: str) -> bool:
    return "ঀ" <= ch <= "৿"


def _category(ch: str) -> str | None:
    """Return the removal class for ``ch``, or None if it is kept as is."""
    cp = ord(ch)
    if ch in _BIDI:
        return "bidi"
    if 0xE0000 <= cp <= 0xE007F:
        return "tag"
    if ch in _INVISIBLE_NON_CF:
        return "variation_or_filler"
    cat = unicodedata.category(ch)
    if cat == "Cf":
        return "format"
    if cat == "Cc" and ch not in _KEPT_CONTROLS:
        return "control"
    return None


@dataclass
class SanitiseReport:
    removed: Counter = field(default_factory=Counter)
    spaces_normalised: int = 0
    joiners_kept: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.removed) or self.spaces_normalised > 0

    @property
    def total_removed(self) -> int:
        return sum(self.removed.values())


def sanitise(text: str) -> tuple[str, SanitiseReport]:
    report = SanitiseReport()
    # Compose first so joiner context checks see composed Bangla characters.
    text = unicodedata.normalize("NFC", text)
    out: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        if ch in (ZWJ, ZWNJ):
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1] if i + 1 < n else ""
            if prev and nxt and _is_bengali(prev) and _is_bengali(nxt):
                out.append(ch)
                report.joiners_kept += 1
            else:
                report.removed["zero_width_joiner"] += 1
            continue
        if ch in _LINE_SEPARATORS:
            out.append("\n")
            report.spaces_normalised += 1
            continue
        if unicodedata.category(ch) == "Zs" and ch != " ":
            out.append(" ")
            report.spaces_normalised += 1
            continue
        cls = _category(ch)
        if cls is None:
            out.append(ch)
        else:
            report.removed[cls] += 1
    cleaned = unicodedata.normalize("NFC", "".join(out))
    return cleaned, report


def sanitise_text(text: str) -> str:
    """Convenience wrapper when the report is not needed."""
    return sanitise(text)[0]


def detector_view(text: str) -> str:
    """Sanitised text with the kept Bangla joiners also removed.

    ZWJ/ZWNJ between Bangla letters only change rendering, never meaning, so an
    attacker can still insert them to split a Bangla keyword. Pattern and
    known-attack matchers should run on this view; the model gets ``sanitise()``.
    """
    return sanitise(text)[0].replace(ZWJ, "").replace(ZWNJ, "")
