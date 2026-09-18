"""L2: high-confidence regex filter for literal injection phrases.

Text is normalized first (Unicode NFKC, zero-width/bidi characters removed, whitespace
collapsed, and a leetspeak-folded variant), and obvious base64 blobs are decoded and
re-scanned, so trivial obfuscation doesn't bypass the patterns.

The generic "ignore previous instructions" family lives in EXTENDED_PATTERNS, which is
off by default (cfg.enable_l2_extended_patterns): prompt-injection-test.ipynb found these
phrases are also common in benign custom-assistant prompts, so hard-blocking on them
alone caused real false positives. L3 judges them from full context instead.
"""
import base64
import binascii
import re
import unicodedata

CORE_PATTERNS = [
    r"you are now (in )?(dan|developer|jailbreak) mode",
    r"pretend (you are|to be) (an? )?(ai )?without (any )?restrictions",
    r"repeat (the words|everything) (above|before this)",
    r"reveal (your |the )?system prompt",
    r"</?(system|instructions)>",
    r"act as if you have no (guidelines|filters|restrictions)",
    r"bypass (your |the )?(safety|content) (filters|guidelines)",
    r"do anything now",
    r"\[/?document\b",                      # forged L6 context tags
]

EXTENDED_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |the )?(prior|previous|above)",
    r"forget (all |your )?(previous |prior )?(instructions|rules)",
    r"new instructions\s*:",
    r"system prompt\s*:",
]

_CORE = [re.compile(p, re.IGNORECASE) for p in CORE_PATTERNS]
_EXTENDED = [re.compile(p, re.IGNORECASE) for p in EXTENDED_PATTERNS]

_INVISIBLE = re.compile(r"[­᠎​-‏‪-‮⁠-⁤﻿]")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _decoded_blobs(text: str) -> list[str]:
    out = []
    for blob in _B64_BLOB.findall(text):
        try:
            decoded = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable():
            out.append(decoded)
    return out


def _variants(text: str) -> list[str]:
    base = normalize(text)
    variants = [base, base.translate(_LEET)]
    variants += [normalize(d) for d in _decoded_blobs(base)]
    return variants


def match_injection(query: str, extended: bool = False) -> str | None:
    """Returns the matching pattern, or None."""
    patterns = _CORE + (_EXTENDED if extended else [])
    for variant in _variants(query):
        for p in patterns:
            if p.search(variant):
                return p.pattern
    return None


def matches_known_injection(query: str, extended: bool = False) -> bool:
    return match_injection(query, extended) is not None
