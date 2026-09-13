import re

INJECTION_PATTERNS = [
    r"you are now (in )?(dan|developer|jailbreak) mode",
    r"pretend (you are|to be) (an? )?(ai )?without (any )?restrictions",
    r"repeat (the words|everything) (above|before this)",
    r"reveal (your |the )?system prompt",
    r"</?(system|instructions)>",
    r"act as if you have no (guidelines|filters|restrictions)",
    r"bypass (your |the )?(safety|content) (filters|guidelines)",
    r"do anything now",
]


def matches_known_injection(query: str) -> bool:
    return any(re.search(p, query, re.IGNORECASE) for p in INJECTION_PATTERNS)
