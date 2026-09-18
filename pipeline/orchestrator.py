"""Wires the layers into one request path:

    rate limit (KB-1) -> L2 regex -> L1 risk (embedding, KB-2) -> L2b (KB-6)
    -> KB-2 match -> L3 guardrail LLM -> L4 scope -> L5 retrieval -> L6 tagging
    -> L7 generation -> L8 output guard

- `cfg` is passed per call (default: config/thresholds.yaml), so the ablation runner can
  toggle any layer without touching globals.
- Security layers fail CLOSED: an exception inside one blocks the request.
- Every request is logged to logs/security_events.jsonl with the blocking layer, scores
  and per-layer latency. The caller only sees a generic message unless
  cfg.expose_block_layer is set (debug/eval), so attackers can't probe layer by layer.
- generation_mode: "llm" (normal), "echo" (worst-case leaky generator, used for DLR),
  "none" (detection only: stops after L3 and, like prompt-injection-test.ipynb, applies
  L8 to the query text).
"""
import time
import uuid
from dataclasses import dataclass, field

from config.settings import get_thresholds
from generation import l6_context_assembler, l7_generation
from generation.rich_output import sanitize_rich_answer
from retrieval.l4_query_rewriter import resolve_scope
from retrieval.l5_secure_retrieval import secure_search
from security import l1_risk_scorer, l2_pattern_filter, l2b_narrative_guard, l3_llm_guardrail, l8_output_guard
from security.event_log import log_security_event, query_fingerprint

GENERIC_BLOCK_MESSAGE = "Sorry, I can't help with that request."
RATE_LIMIT_MESSAGE = "Too many requests. Please wait a moment and try again."
UNAVAILABLE_MESSAGE = "The assistant is temporarily unavailable. Please try again, or ask to be connected to a human agent."


class _Blocked(Exception):
    def __init__(self, layer: str, message: str = GENERIC_BLOCK_MESSAGE, status: int = 200, **details):
        self.layer, self.message, self.status, self.details = layer, message, status, details


@dataclass
class PipelineResult:
    request_id: str
    response: str
    blocked_at: str | None = None
    verdict: str = "pass"                    # pass | redacted | blocked | error
    status_code: int = 200
    sources: list = field(default_factory=list)
    citations: dict = field(default_factory=dict)   # "c1" -> document title (for the UI)
    retrieved_ids: list = field(default_factory=list)
    retrieved_meta: list = field(default_factory=list)
    timings_ms: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    @property
    def final_action(self) -> str:
        """Row label compatible with eval.metrics.calculate_metrics."""
        return f"Blocked at {self.blocked_at}" if self.blocked_at else "Completed"

    @property
    def total_latency_ms(self) -> float:
        return self.timings_ms.get("total", 0.0)

    def public(self, expose_block_layer: bool = False) -> dict:
        out = {"request_id": self.request_id, "response": self.response, "sources": self.sources,
               "citations": self.citations, "blocked": self.blocked_at is not None,
               "latency_ms": round(self.total_latency_ms)}
        if expose_block_layer:
            out.update(blocked_at=self.blocked_at, verdict=self.verdict)
        return out


class _Timer:
    def __init__(self, timings: dict, name: str):
        self.timings, self.name = timings, name

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *exc):
        self.timings[self.name] = round((time.perf_counter() - self.t0) * 1000, 3)
        return False


def _guarded(layer: str, fn, *args, **kwargs):
    """Run a security layer; any exception blocks the request (fail closed)."""
    try:
        return fn(*args, **kwargs)
    except _Blocked:
        raise
    except Exception as e:
        raise _Blocked(f"{layer}-error", error=f"{type(e).__name__}: {e}")


def handle_request(query: str, user_id: str, role: str, ip: str, session_id: str, tenant_id: str = "default",
                   cfg=None, generation_mode: str = "llm", request_id: str | None = None,
                   log: bool = True) -> PipelineResult:
    cfg = cfg or get_thresholds()
    request_id = request_id or uuid.uuid4().hex
    timings, details = {}, {}
    result = PipelineResult(request_id=request_id, response="")
    t_start = time.perf_counter()

    try:
        # --- KB-1 rate limit (counted before anything else so blocked requests count too)
        with _Timer(timings, "rate"):
            count = _guarded("RATE", l1_risk_scorer.check_rate, session_id, cfg)
        details["request_count"] = count
        if count > cfg.rate_limit_hard:
            raise _Blocked("RATE", RATE_LIMIT_MESSAGE, status=429)

        # --- L2: cheap regex first
        if cfg.enable_l2:
            with _Timer(timings, "L2"):
                pattern = _guarded("L2", l2_pattern_filter.match_injection, query, cfg.enable_l2_extended_patterns)
            if pattern:
                raise _Blocked("L2", pattern=pattern)

        # --- L1: embedding + KB-2 distance (the embedding is reused by L2b and L5)
        with _Timer(timings, "L1"):
            risk = _guarded("L1", l1_risk_scorer.compute_risk, query, ip, count, cfg)
        details.update(risk_score=round(risk.risk_score, 4), path_taken=risk.path_taken,
                       kb2_distance=round(risk.min_kb2_distance, 4), kb2_nearest=risk.nearest_attack_id)
        if cfg.enable_l1_block and risk.risk_score >= cfg.l1_block_threshold:
            raise _Blocked("L1")

        # --- L2b: narrative jailbreak archetypes
        if cfg.enable_l2b:
            with _Timer(timings, "L2b"):
                dist, archetype, category = _guarded("L2b", l2b_narrative_guard.narrative_match, risk.window_embs)
            details.update(kb6_distance=round(dist, 4), kb6_archetype=archetype, kb6_category=category)
            if dist < cfg.narrative_match_threshold:
                raise _Blocked("L2b")

        # --- KB-2 short-circuit and L3 guardrail LLM
        if cfg.enable_kb2_match and l3_llm_guardrail.kb2_match(risk.min_kb2_distance, cfg):
            raise _Blocked("KB2")
        if cfg.enable_l3 and risk.path_taken == "full":
            with _Timer(timings, "L3"):
                verdict = _guarded("L3", l3_llm_guardrail.classify, query)
            if verdict == "unsafe":
                raise _Blocked("L3")

        if generation_mode == "none":
            if cfg.enable_l8:
                with _Timer(timings, "L8"):
                    check = _guarded("L8", l8_output_guard.check_output, query, "", cfg)
                if check.verdict != "pass":
                    raise _Blocked("L8", findings=check.findings, pii_category=check.pii_category)
            result.response = ""
            return result

        # --- L4 / L5
        with _Timer(timings, "L4"):
            scope = _guarded("L4", resolve_scope, query, role, cfg)
        with _Timer(timings, "L5"):
            retrieved = _guarded("L5", secure_search, risk.query_emb, scope, tenant_id, cfg,
                                 user_id=user_id, request_id=request_id, query=query)
        result.retrieved_ids = [r.chunk_id for r in retrieved]
        result.retrieved_meta = [r.metadata for r in retrieved]
        details.update(intent=scope.intent, n_retrieved=len(retrieved))

        # --- L6 / L7
        if not retrieved:
            answer = l7_generation.GenerationResult(l7_generation.ESCALATION_MESSAGE, model="none")
        else:
            with _Timer(timings, "L6"):
                context = (l6_context_assembler.tag_context(retrieved) if cfg.enable_l6
                           else l6_context_assembler.raw_context(retrieved))
            with _Timer(timings, "L7"):
                try:
                    answer = (l7_generation.echo_answer(context) if generation_mode == "echo"
                              else l7_generation.generate_answer(query, context))
                except Exception as e:
                    raise _Blocked("L7-error", UNAVAILABLE_MESSAGE, status=503, error=f"{type(e).__name__}: {e}")
            details.update(model=answer.model, refused=answer.refused, cited=answer.cited,
                           invalid_citations=answer.invalid_citations, uncited=answer.uncited)
            cited_ids = {context.citations[c] for c in answer.cited if c in context.citations}
            shown = [r for r in retrieved if r.chunk_id in cited_ids] or retrieved
            result.sources = list(dict.fromkeys(r.metadata.get("title", "untitled") for r in shown))
            titles = {r.chunk_id: r.metadata.get("title", "untitled") for r in retrieved}
            result.citations = {c: titles[cid] for c, cid in context.citations.items() if c in answer.cited}

        # --- L8 on the generated answer
        final_text = answer.text
        if cfg.enable_l8:
            allowed = "\n".join(r.text for r in retrieved)
            with _Timer(timings, "L8"):
                check = _guarded("L8", l8_output_guard.check_output, answer.text, allowed, cfg)
            details.update(l8_findings=check.findings, kb5_distance=round(check.kb5_distance, 4))
            if check.verdict == "blocked":
                raise _Blocked("L8", check.text, pii_category=check.pii_category)
            final_text = check.text
            result.verdict = check.verdict
        # Validate chart/diagram blocks only after L8 has screened the complete text.
        final_text, rich = sanitize_rich_answer(final_text)
        details["rich"] = rich
        result.response = final_text
        return result

    except _Blocked as b:
        result.blocked_at, result.response, result.status_code = b.layer, b.message, b.status
        result.verdict = "error" if b.layer.endswith("-error") else "blocked"
        result.sources, result.citations = [], {}
        details.update(b.details)
        return result

    finally:
        timings["total"] = round((time.perf_counter() - t_start) * 1000, 3)
        result.timings_ms, result.details = timings, details
        if log:
            log_security_event({
                "request_id": request_id, "user_id": user_id, "role": role, "tenant_id": tenant_id, "ip": ip,
                "generation_mode": generation_mode, "blocked_at": result.blocked_at, "verdict": result.verdict,
                "status_code": result.status_code, **query_fingerprint(query),
                "retrieved_ids": result.retrieved_ids, "timings_ms": timings, **details,
            })
