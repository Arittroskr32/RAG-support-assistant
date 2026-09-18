"""L1: risk score from nearest-attack distance (KB-2) + request rate (KB-1) + IP reputation."""
from dataclasses import dataclass

from config.settings import get_thresholds
from knowledge_bases import kb1_session_log
from knowledge_bases.kb_manager import kb, nearest, split_windows


@dataclass
class RiskResult:
    risk_score: float
    path_taken: str                  # "fast" (L3 may be skipped) or "full"
    query_emb: list[float]           # whole-query embedding (reused by L5 retrieval)
    window_embs: list[list[float]]   # windowed embeddings (reused by L2b)
    min_kb2_distance: float
    nearest_attack_id: str | None


def check_rate(session_id: str, cfg=None) -> int:
    """Records the request and returns the count in the trailing window. Called before
    any other layer so blocked requests still count toward the rate limit."""
    cfg = cfg or get_thresholds()
    return kb1_session_log.record_request(session_id, window_s=cfg.rate_limit_window_s)


def compute_risk(query: str, ip: str, request_count: int, cfg=None) -> RiskResult:
    cfg = cfg or get_thresholds()
    windows = (split_windows(query, cfg.embed_window_words, cfg.embed_window_stride)
               if cfg.enable_windowed_embedding else [query])
    if windows == [query]:          # short query: one embedding serves both purposes
        query_emb = kb.embed(query)[0]
        window_embs = [query_emb]
    else:                           # one batched encode call for whole query + windows
        embs = kb.embed([query] + windows)
        query_emb, window_embs = embs[0], embs[1:]
    min_distance, attack_id, _ = nearest(kb.kb2_attacks, window_embs)

    risk_score = max(0.0, 1.0 - (min_distance / cfg.risk_distance_scale))
    if request_count > cfg.rate_limit_soft:
        risk_score = min(1.0, risk_score + cfg.rate_limit_risk_bump)
    risk_score = min(1.0, risk_score + kb1_session_log.get_ip_reputation(ip))

    path_taken = "fast" if (cfg.fast_path_ceiling >= 0 and risk_score < cfg.fast_path_ceiling) else "full"
    return RiskResult(risk_score, path_taken, query_emb, window_embs, min_distance, attack_id)
