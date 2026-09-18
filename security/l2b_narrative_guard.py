"""L2b: semantic narrative-jailbreak check against KB-6 archetypes.

Uses the minimum distance over the query's embedding windows, so a jailbreak framing
buried in a long prompt isn't diluted (or truncated away) by the surrounding text.
"""
from config.settings import get_thresholds
from knowledge_bases.kb_manager import kb, nearest


def narrative_match(window_embs: list[list[float]]):
    """Returns (distance, archetype_id, category)."""
    dist, archetype_id, meta = nearest(kb.kb6_narrative, window_embs)
    return dist, archetype_id, (meta or {}).get("category")


def narrative_distance(window_embs: list[list[float]]) -> float:
    return narrative_match(window_embs)[0]


def is_narrative_jailbreak(window_embs: list[list[float]], cfg=None) -> bool:
    cfg = cfg or get_thresholds()
    return narrative_distance(window_embs) < cfg.narrative_match_threshold
