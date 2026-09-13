from config.settings import SecurityThresholds
from generation.l6_context_assembler import tag_context
from generation.l7_generation import generate_answer
from retrieval.l4_query_rewriter import rewrite_query
from retrieval.l5_secure_retrieval import secure_search
from security import l1_risk_scorer, l2_pattern_filter, l2b_narrative_guard, l3_llm_guardrail, l8_output_guard

_cfg = SecurityThresholds()
GENERIC_BLOCK_MESSAGE = "Sorry, I can't help with that request."


def handle_request(query: str, user_id: str, role: str, ip: str, session_id: str, tenant_id="default"):
    risk_score, path_taken, query_emb, min_kb2_dist = l1_risk_scorer.compute_risk(query, ip, session_id)

    if _cfg.enable_l1_block and risk_score >= _cfg.l1_block_threshold:
        return {"blocked_at": "L1", "response": GENERIC_BLOCK_MESSAGE}

    if _cfg.enable_l2 and l2_pattern_filter.matches_known_injection(query):
        return {"blocked_at": "L2", "response": GENERIC_BLOCK_MESSAGE}

    if _cfg.enable_l2b and l2b_narrative_guard.is_narrative_jailbreak(query_emb):
        return {"blocked_at": "L2b", "response": GENERIC_BLOCK_MESSAGE}

    if _cfg.enable_l3 and (path_taken == "full" or _cfg.fast_path_ceiling < 0):
        if l3_llm_guardrail.check(query, min_kb2_dist) == "unsafe":
            return {"blocked_at": "L3", "response": GENERIC_BLOCK_MESSAGE}

    scoped_query, clearance, allowed_types = rewrite_query(query, role)
    retrieved = secure_search(scoped_query, clearance, allowed_types, tenant_id=tenant_id, user_id=user_id)
    answer = generate_answer(query, tag_context(retrieved))

    verdict, final_text = l8_output_guard.check_output(answer)
    if verdict == "blocked":
        return {"blocked_at": "L8", "response": final_text}

    return {"blocked_at": None, "response": final_text, "verdict": verdict,
            "sources": [m["source_doc_id"] for _, m in retrieved]}
