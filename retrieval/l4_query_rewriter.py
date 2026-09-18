"""L4: resolves the caller's retrieval scope from their (server-verified) role.

The query text itself is NOT modified: scoping is enforced by L5's metadata filter, and
prepending scope text to the query would shift its embedding and hurt retrieval.

Optional intent narrowing (cfg.enable_intent_narrowing): a keyword classifier picks an
intent and intersects its document types with the role's allowed types. It can only
narrow the scope, never widen it, and falls back to the full role scope when the
intersection would be empty.
"""
import re
from dataclasses import dataclass

from config.settings import get_thresholds
from knowledge_bases.kb3_rbac import all_document_types, get_user_scope, max_clearance

INTENT_KEYWORDS = {
    "billing": (r"\b(bill|billing|invoice|refund|charge|payment|subscription|cancel|price|pricing|plan|trial)\b",
                ["public_faq", "product_info", "sales_info"]),
    "technical": (r"\b(api|sdk|endpoint|integrat\w*|webhook|error|bug|token|auth\w*|developer)\b",
                  ["public_faq", "product_info", "developer_info"]),
    "account": (r"\b(password|login|log in|sign in|account|profile|email|2fa|mfa)\b",
                ["public_faq", "product_info"]),
    "company": (r"\b(company|about|mission|policy|policies|careers|office|team)\b",
                ["public_faq", "company_info"]),
}


@dataclass
class Scope:
    role: str
    clearance: int
    allowed_types: list[str]
    intent: str | None = None
    rbac_enforced: bool = True


def classify_intent(query: str) -> str | None:
    q = query.lower()
    scores = {name: len(re.findall(rx, q)) for name, (rx, _) in INTENT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def resolve_scope(query: str, role: str, cfg=None) -> Scope:
    cfg = cfg or get_thresholds()
    if not cfg.enable_rbac:   # ablation only: what would leak without L4/L5
        return Scope(role, max_clearance(), all_document_types(), rbac_enforced=False)

    clearance, allowed = get_user_scope(role)
    intent = None
    if cfg.enable_intent_narrowing:
        intent = classify_intent(query)
        if intent:
            narrowed = [t for t in allowed if t in INTENT_KEYWORDS[intent][1]]
            allowed = narrowed or allowed
    return Scope(role, clearance, allowed, intent)


def rewrite_query(query: str, role: str, cfg=None):
    """Backward-compatible wrapper: (query, clearance, allowed_types)."""
    scope = resolve_scope(query, role, cfg)
    return query, scope.clearance, scope.allowed_types
