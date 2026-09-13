from config.settings import SecurityThresholds
from knowledge_bases.kb_manager import kb

_cfg = SecurityThresholds()


def narrative_distance(query_emb) -> float:
    res = kb.kb6_narrative.query(query_embeddings=[query_emb], n_results=1)
    return res["distances"][0][0] if res.get("distances") and res["distances"][0] else 1.0


def is_narrative_jailbreak(query_emb) -> bool:
    return narrative_distance(query_emb) < _cfg.narrative_match_threshold
