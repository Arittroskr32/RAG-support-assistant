"""L8: output guard on the generated answer.

1. Regex scanner with named patterns (modern API-key formats, JWTs, PEM keys, SSNs,
   Luhn-validated card numbers, emails, phone numbers). Matches are redacted.
   - "secret" findings are always redacted.
   - "contact" findings (email/phone) are left alone when the same string appears in the
     authorized retrieved context (e.g. the support phone number from the FAQ) or the
     email domain is allow-listed via L8_EMAIL_ALLOWLIST_DOMAINS.
2. Semantic backstop: every sentence is compared against KB-5; a close match blocks the
   whole answer. This runs even when the regex already redacted something.
3. Optional Microsoft Presidio NER (cfg.enable_presidio, `pip install presidio-analyzer`)
   for PII the regexes don't cover.
"""
import os
import re
from dataclasses import dataclass, field

from config.settings import get_thresholds
from knowledge_bases.kb_manager import kb, nearest

BLOCK_MESSAGE = "I can't share that information."


def luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _ssn_valid(s: str) -> bool:
    area, group, serial = s.split("-")
    return area not in ("000", "666") and not area.startswith("9") and group != "00" and serial != "0000"


@dataclass(frozen=True)
class OutputPattern:
    name: str
    regex: re.Pattern
    kind: str = "secret"              # "secret" | "contact"
    validator: object = None


OUTPUT_PATTERNS = [
    OutputPattern("anthropic_or_openai_key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}")),
    OutputPattern("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    OutputPattern("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    OutputPattern("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    OutputPattern("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    OutputPattern("jwt", re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}")),
    OutputPattern("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")),
    OutputPattern("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), validator=_ssn_valid),
    OutputPattern("credit_card", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"), validator=luhn_valid),
    OutputPattern("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), kind="contact"),
    OutputPattern("phone", re.compile(r"(?<![\w+])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\w)"),
                  kind="contact"),
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_PRESIDIO_ENTITIES = ["CREDIT_CARD", "US_SSN", "IBAN_CODE", "US_BANK_NUMBER", "US_PASSPORT",
                      "US_DRIVER_LICENSE", "EMAIL_ADDRESS", "PHONE_NUMBER", "CRYPTO"]
_presidio = None


@dataclass
class OutputCheck:
    verdict: str                      # "pass" | "redacted" | "blocked"
    text: str
    findings: list = field(default_factory=list)   # pattern names that fired
    pii_category: str | None = None   # KB-5 category when blocked
    kb5_distance: float = 1.0


def _email_allowlist() -> set[str]:
    return {d.strip().lower() for d in os.getenv("L8_EMAIL_ALLOWLIST_DOMAINS", "").split(",") if d.strip()}


def _is_authorized_contact(value: str, pattern: OutputPattern, allowed_context: str) -> bool:
    if value in allowed_context:
        return True
    if pattern.name == "email":
        return value.rsplit("@", 1)[-1].lower() in _email_allowlist()
    return False


def redact(text: str, allowed_context: str = "") -> tuple[str, list[str]]:
    findings = []
    for p in OUTPUT_PATTERNS:
        def _sub(m, p=p):
            value = m.group(0)
            if p.validator and not p.validator(value):
                return value
            if p.kind == "contact" and _is_authorized_contact(value, p, allowed_context):
                return value
            findings.append(p.name)
            return "[REDACTED]"
        text = p.regex.sub(_sub, text)
    return text, findings


def _presidio_redact(text: str, allowed_context: str) -> tuple[str, list[str]]:
    global _presidio
    try:
        if _presidio is None:
            from presidio_analyzer import AnalyzerEngine
            _presidio = AnalyzerEngine()
    except ImportError:
        return text, []
    results = _presidio.analyze(text=text, entities=_PRESIDIO_ENTITIES, language="en", score_threshold=0.6)
    findings = []
    for r in sorted(results, key=lambda r: r.start, reverse=True):
        value = text[r.start:r.end]
        if value in allowed_context or value == "[REDACTED]":
            continue
        findings.append(f"presidio_{r.entity_type.lower()}")
        text = text[:r.start] + "[REDACTED]" + text[r.end:]
    return text, findings


def semantic_pii_match(text: str):
    """Returns (min_distance, pii_category) over the sentences of `text`."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 3]
    if not sentences:
        return 1.0, None
    dist, _, meta = nearest(kb.kb5_pii, kb.embed(sentences))
    return dist, (meta or {}).get("pii_category")


def check_output(text: str, allowed_context: str = "", cfg=None) -> OutputCheck:
    cfg = cfg or get_thresholds()
    dist, category = semantic_pii_match(text)
    if dist < cfg.kb5_pii_threshold:
        return OutputCheck("blocked", BLOCK_MESSAGE, ["kb5_semantic"], category, dist)

    redacted, findings = redact(text, allowed_context)
    if cfg.enable_presidio:
        redacted, more = _presidio_redact(redacted, allowed_context)
        findings += more
    if findings:
        return OutputCheck("redacted", redacted, findings, kb5_distance=dist)
    return OutputCheck("pass", text, kb5_distance=dist)
