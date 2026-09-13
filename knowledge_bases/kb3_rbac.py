from pathlib import Path

import yaml

_RBAC_PATH = Path(__file__).parent / "rbac_policy.yaml"


def _load_policy():
    with open(_RBAC_PATH) as f:
        return yaml.safe_load(f)


_POLICY = _load_policy()


def get_user_scope(role: str):
    """Returns (clearance_level: int, allowed_document_types: list[str]) for a role."""
    entry = _POLICY.get(role, _POLICY["public"])
    return entry["clearance_level"], entry["allowed_document_types"]
