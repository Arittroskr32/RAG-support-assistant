import re

from config.settings import SecurityThresholds
from knowledge_bases.kb_manager import kb

_cfg = SecurityThresholds()

SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{20,}", r"hf_[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}",
    r"\b\d{3}-\d{2}-\d{4}\b", r"\b(?:\d[ -]*?){13,16}\b",
]


def check_output(text: str):
    """Returns (verdict, cleaned_text). verdict in {'pass', 'redacted', 'blocked'}."""
    if any(re.search(p, text) for p in SECRET_PATTERNS):
        redacted = text
        for p in SECRET_PATTERNS:
            redacted = re.sub(p, "[REDACTED]", redacted)
        return "redacted", redacted

    emb = kb.embed(text)[0]
    res = kb.kb5_pii.query(query_embeddings=[emb], n_results=1)
    if res.get("distances") and res["distances"][0] and res["distances"][0][0] < _cfg.kb5_pii_threshold:
        return "blocked", "I can't share that information."
    return "pass", text
