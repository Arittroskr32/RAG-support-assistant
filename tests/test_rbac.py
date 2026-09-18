import copy

import pytest

from ingestion.metadata_tagger import tag_chunk
from knowledge_bases import kb3_rbac


def test_every_allowed_type_is_reachable_by_its_role():
    """Regression for the off-by-one: L5 filters on clearance AND type, so an allowed type
    whose clearance exceeds the role's would be silently unreachable."""
    policy = kb3_rbac.load_policy()
    for role in policy["roles"]:
        clearance, allowed = kb3_rbac.get_user_scope(role)
        for t in allowed:
            chunk = tag_chunk("x", t, f"{t}/doc.md")
            assert chunk["clearance_level"] <= clearance, (role, t)


def test_policy_validation_rejects_unreachable_types():
    bad = copy.deepcopy(kb3_rbac.load_policy())
    bad["document_types"]["sales_info"] = 4
    with pytest.raises(kb3_rbac.RBACPolicyError, match="unreachable"):
        kb3_rbac.validate_policy(bad)


def test_unknown_role_falls_back_to_least_privilege():
    assert kb3_rbac.get_user_scope("superuser") == kb3_rbac.get_user_scope("public")
    assert kb3_rbac.get_user_scope("  Admin ")[0] == kb3_rbac.get_user_scope("admin")[0]


def test_unknown_document_type_is_unreachable():
    assert kb3_rbac.clearance_for_type("secret_new_folder") > kb3_rbac.max_clearance()


def test_front_matter_can_raise_but_not_lower_clearance():
    assert tag_chunk("x", "public_faq", "a.md", clearance_override=3)["clearance_level"] == 3
    assert tag_chunk("x", "sales_info", "a.md", clearance_override=0)["clearance_level"] == \
        kb3_rbac.clearance_for_type("sales_info")
