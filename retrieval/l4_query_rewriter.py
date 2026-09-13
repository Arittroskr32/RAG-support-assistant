from knowledge_bases.kb3_rbac import get_user_scope


def rewrite_query(query: str, role: str):
    clearance, allowed_types = get_user_scope(role)
    return f"[scope: {allowed_types}] {query}", clearance, allowed_types
