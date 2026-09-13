from config.settings import SecurityThresholds
from knowledge_bases import kb1_session_log
from knowledge_bases.kb_manager import kb

_cfg = SecurityThresholds()


def compute_risk(query: str, ip: str, session_id: str):
    query_emb = kb.embed(query)[0]
    kb2_res = kb.kb2_attacks.query(query_embeddings=[query_emb], n_results=1)
    min_distance = kb2_res["distances"][0][0] if kb2_res.get("distances") and kb2_res["distances"][0] else 1.0

    risk_score = max(0.0, 1.0 - (min_distance / 0.65))
    if kb1_session_log.record_request(session_id) > 50:
        risk_score = min(1.0, risk_score + 0.2)
    risk_score = min(1.0, risk_score + kb1_session_log.get_ip_reputation(ip))

    path_taken = "fast" if risk_score < _cfg.fast_path_ceiling else "full"
    return risk_score, path_taken, query_emb, min_distance
