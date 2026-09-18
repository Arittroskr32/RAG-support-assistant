"""KB-3: role -> (clearance, allowed document types), and document type -> clearance.

Both mappings come from rbac_policy.yaml so the retrieval filter (L5) and the ingestion
tagger can never drift apart again.
"""
import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_RBAC_PATH = Path(__file__).parent / "rbac_policy.yaml"


class RBACPolicyError(ValueError):
    pass


def validate_policy(policy: dict) -> None:
    doc_types = policy.get("document_types") or {}
    roles = policy.get("roles") or {}
    if not doc_types or not roles:
        raise RBACPolicyError("rbac_policy.yaml needs non-empty 'document_types' and 'roles'")
    if policy.get("default_role") not in roles:
        raise RBACPolicyError("'default_role' must name one of the defined roles")
    problems = []
    for role, entry in roles.items():
        for t in entry["allowed_document_types"]:
            if t not in doc_types:
                problems.append(f"role '{role}' allows unknown document type '{t}'")
            elif doc_types[t] > entry["clearance_level"]:
                problems.append(
                    f"role '{role}' (clearance {entry['clearance_level']}) allows '{t}' "
                    f"(clearance {doc_types[t]}) — it would be unreachable")
    if problems:
        raise RBACPolicyError("; ".join(problems))


@lru_cache(maxsize=1)
def load_policy(path: Path = _RBAC_PATH) -> dict:
    with open(path) as f:
        policy = yaml.safe_load(f)
    validate_policy(policy)
    return policy


def get_user_scope(role: str):
    """Returns (clearance_level: int, allowed_document_types: list[str]) for a role.
    Unknown roles fall back to the policy's default (least-privileged) role."""
    policy = load_policy()
    key = (role or "").strip().lower()
    entry = policy["roles"].get(key)
    if entry is None:
        logger.warning("Unknown role %r — falling back to %r", role, policy["default_role"])
        entry = policy["roles"][policy["default_role"]]
    return entry["clearance_level"], list(entry["allowed_document_types"])


def clearance_for_type(document_type: str) -> int:
    """Clearance for a document type. Unknown types (a new data/ folder nobody added to
    the policy) get the highest clearance in the policy + 1, i.e. unreachable until the
    policy is updated — fail closed rather than leak."""
    policy = load_policy()
    doc_types = policy["document_types"]
    if document_type in doc_types:
        return doc_types[document_type]
    max_role = max(r["clearance_level"] for r in policy["roles"].values())
    logger.warning("Document type %r not in rbac_policy.yaml — tagging as unreachable", document_type)
    return max_role + 1


def all_document_types() -> list[str]:
    return list(load_policy()["document_types"])


def max_clearance() -> int:
    return max(r["clearance_level"] for r in load_policy()["roles"].values())


def known_roles() -> list[str]:
    return list(load_policy()["roles"])
