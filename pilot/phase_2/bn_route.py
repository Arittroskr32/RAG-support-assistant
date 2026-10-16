"""The Bangla route for phase 2 (G2: multilingual-E5-small), kept outside the core pipeline.

Plan steps A2, E1 and E3. Nothing here changes the deployed system: the phase-2 runners
switch the route on for one run by wrapping pipeline.orchestrator.secure_search, so English
numbers from the unchanged pipeline stay comparable.

  router        is_bangla(text) / route(text): inclusive routing (D-26 / Phase 6). Bangla
                script anywhere -> "bn"; enough Banglish function words -> "banglish";
                otherwise "en". The Banglish word list is a heuristic; check route() on
                your human-written Banglish before trusting it (retrieval_eval.py prints
                the routing rate per language).
  E5 retrieval  a second Chroma collection (kb4_documents_e5) holding the same chunks and
                metadata as KB-4, embedded with E5 ("passage: " prefix). Bangla/Banglish
                questions are embedded with "query: " and searched there with the SAME
                RBAC/tenant/quarantine `where` filter as L5 (retrieval.l5_secure_retrieval
                .build_where), so the deterministic guarantees are unchanged.
  BN_native     similarity of a text to a small Bangla/Banglish attack KB, "query: " prefix
                on both sides (the senior's instruction for similarity). Flag when the best
                cosine similarity is ABOVE the threshold; calibrate the threshold with
                calibrate.py, never reuse MiniLM thresholds.

The E5 model is loaded on first use (sentence-transformers). Tests swap in a fake with
set_e5(...).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from pilot.phase_2 import tags

E5_MODEL = "intfloat/multilingual-e5-small"
E5_COLLECTION = "kb4_documents_e5"
# How a text is wrapped before E5 embeds it. "standard" is what E5 was trained with and the
# plan's default. "tagged" is the alternative style; compare both with
#   python -m pilot.phase_2.retrieval_eval --embedders minilm e5 e5-tagged
# The wrapping is added on the server, after the user's or document's text arrives, and only
# changes the embedding; it is not a trust boundary (the random L6 nonce tags are).
PREFIX_STYLES = {
    "standard": {"query": ("query: ", ""), "passage": ("passage: ", "")},
    "tagged": {"query": (tags.OPEN["query"] + " ", " " + tags.CLOSE["query"]),
               "passage": (tags.OPEN["passage"] + " ", " " + tags.CLOSE["passage"])},
}
_style = "standard"


def set_prefix_style(style: str) -> None:
    """Choose the E5 wrapping for this process. Each style has its own E5 collection, so the
    chunks and the questions are always wrapped the same way."""
    global _style
    if style not in PREFIX_STYLES:
        raise ValueError(f"unknown E5 prefix style {style!r}; choose from {sorted(PREFIX_STYLES)}")
    _style = style


def prefix_style() -> str:
    return _style


def e5_collection_name() -> str:
    return E5_COLLECTION if _style == "standard" else f"{E5_COLLECTION}_{_style}"
_BN_SCRIPT = re.compile(r"[ঀ-৿]")
# Frequent Banglish function words and question words. Two or more hits, or at least 15% of
# the words, routes the text to the Bangla route.
BANGLISH_WORDS = {
    "ami", "amar", "amra", "apni", "apnar", "tumi", "tomar", "ki", "kivabe", "kibhabe", "keno", "kothay",
    "koto", "kokhon", "ache", "achhe", "nai", "nei", "hobe", "hoy", "hoye", "korbo", "korte", "koren",
    "korun", "kore", "korlam", "dite", "diben", "deben", "den", "pabo", "pai", "jabe", "theke", "jonno",
    "er", "ar", "o", "na", "ta", "ti", "gulo", "shob", "sob", "din", "taka", "ekta", "ekti", "kono",
    "bolben", "bolun", "janaben", "janan", "lagbe", "lage", "chai", "chaichi", "dorkar", "ekhon", "pore",
    "shathe", "sathe", "shuru", "bondho", "kintu", "tahole", "jodi", "ei", "oi", "eta", "oita",
    "baire", "bhitore", "moddhe", "porjonto", "uttor", "sheshe", "likhben", "likhun", "diner", "jay",
    "deya", "dewa", "somoy", "shomoy", "kaj", "pathaben", "pathan", "ferot", "dam", "daam", "korar",
}
# Banglish words that are also English words (or common English fragments) count half, so an
# English sentence such as "Is there a den or a pore filter?" stays English.
EN_COLLIDE = {"den", "pore", "din", "er", "ar", "o", "ta", "ti", "na", "ei", "oi", "eta", "pai", "ache", "dam", "jay"}
_WORD = re.compile(r"[A-Za-z]+")


def route(text: str) -> str:
    if _BN_SCRIPT.search(text or ""):
        return "bn"
    words = [w.lower() for w in _WORD.findall(text or "")]
    hits = sum((0.5 if w in EN_COLLIDE else 1.0) for w in words if w in BANGLISH_WORDS)
    if hits >= 2 and (hits >= 3 or hits / max(len(words), 1) >= 0.15):
        return "banglish"
    return "en"


def is_bangla(text: str) -> bool:
    return route(text) != "en"


# --------------------------------------------------------------------------- E5

class E5:
    """multilingual-E5-small with the E5 prefixes; normalised embeddings (cosine = dot)."""

    def __init__(self, model_name: str = E5_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self._lock = threading.Lock()

    def encode(self, texts: list[str], prefix: str, suffix: str = "") -> list[list[float]]:
        with self._lock:
            return self.model.encode([prefix + t + suffix for t in texts], normalize_embeddings=True,
                                     show_progress_bar=False, batch_size=32).tolist()


_e5 = None
_e5_lock = threading.Lock()


def get_e5():
    global _e5
    if _e5 is None:
        with _e5_lock:
            if _e5 is None:
                _e5 = E5()
    return _e5


def set_e5(instance) -> None:
    global _e5
    _e5 = instance


def embed_query(texts: list[str]) -> list[list[float]]:
    """Any wrapper already on the text is removed first, so it is wrapped exactly once."""
    return get_e5().encode([tags.unwrap(t, "query") for t in texts], *PREFIX_STYLES[_style]["query"])


def embed_passage(texts: list[str]) -> list[list[float]]:
    return get_e5().encode([tags.unwrap(t, "passage") for t in texts], *PREFIX_STYLES[_style]["passage"])


# --------------------------------------------------------------------------- E5 collection

def build_e5_collection(kb=None) -> int:
    """Copy every KB-4 chunk (text + metadata, including the quarantine flag) into the E5
    collection. Call it after every KB-4 rebuild."""
    if kb is None:
        from knowledge_bases.kb_manager import kb
    src = kb.kb4_documents.get(include=["documents", "metadatas"])
    coll = kb.reset_collection(e5_collection_name())
    if src["ids"]:
        kb.add_batched(coll, ids=src["ids"], documents=src["documents"],
                       embeddings=embed_passage(src["documents"]), metadatas=src["metadatas"])
    return len(src["ids"])


def e5_collection(kb=None):
    if kb is None:
        from knowledge_bases.kb_manager import kb
    return kb._get_or_create(e5_collection_name())


def quarantine(chunk_ids: list[str], reason: str, kb=None) -> None:
    """Mark chunks quarantined in BOTH collections, as the ingestion scan would."""
    if not chunk_ids:
        return
    if kb is None:
        from knowledge_bases.kb_manager import kb
    for coll in (kb.kb4_documents, e5_collection(kb)):
        got = coll.get(ids=chunk_ids, include=["metadatas"])
        metas = [{**m, "quarantined": True, "quarantine_reason": reason} for m in got["metadatas"]]
        if got["ids"]:
            coll.update(ids=got["ids"], metadatas=metas)


# --------------------------------------------------------------------------- routed retrieval

class RoutedSearch:
    """Drop-in replacement for pipeline.orchestrator.secure_search.

    English questions go to the original L5 unchanged. Bangla/Banglish questions (or every
    question with route_all=True) are embedded with E5 and searched in the E5 collection
    with the same where-filter, top-k and audit log as L5. `last` records the route of the
    most recent call so the runner can log it."""

    def __init__(self, original, route_all: bool = False, max_distance: float | None = None):
        self.original, self.route_all, self.max_distance = original, route_all, max_distance
        self.last = {}

    def __call__(self, query_emb, scope, tenant_id="default", cfg=None, user_id="anon",
                 request_id="", query=""):
        from config.settings import get_thresholds
        from retrieval.l5_secure_retrieval import RetrievedChunk, build_where
        from security import l2_pattern_filter
        from security.event_log import log_retrieval, query_fingerprint

        query = tags.unwrap(query, "query")
        r = route(query)
        if r == "en" and not self.route_all:
            self.last = {"route": "en", "embedder": "minilm"}
            results = self.original(query_emb, scope, tenant_id, cfg, user_id=user_id,
                                    request_id=request_id, query=query)
            for x in results:                 # the LLM never sees a wrapper marker
                x.text = tags.strip_markers(x.text)
            return results
        cfg = cfg or get_thresholds()
        coll = e5_collection()
        results = []
        if scope.allowed_types and coll.count() > 0:
            res = coll.query(query_embeddings=embed_query([query]), n_results=cfg.retrieval_top_k,
                             where=build_where(scope, tenant_id), include=["documents", "metadatas", "distances"])
            for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0],
                                            res["distances"][0]):
                results.append(RetrievedChunk(cid, tags.strip_markers(doc), meta, dist))
        limit = self.max_distance if self.max_distance is not None else cfg.retrieval_max_distance
        too_far = [x for x in results if x.distance > limit]
        results = [x for x in results if x.distance <= limit]
        rescan = []
        if cfg.enable_retrieval_rescan:
            rescan = [x for x in results if l2_pattern_filter.matches_known_injection(x.text, extended=True)]
            results = [x for x in results if x not in rescan]
        log_retrieval({"request_id": request_id, "user_id": user_id, "role": scope.role, "tenant_id": tenant_id,
                       "clearance": scope.clearance, "allowed_types": scope.allowed_types,
                       "intent": scope.intent, "rbac_enforced": scope.rbac_enforced, "route": r,
                       "embedder": "e5", "e5_prefix": _style, **query_fingerprint(query),
                       "result_ids": [x.chunk_id for x in results],
                       "distances": [round(x.distance, 4) for x in results],
                       "dropped_irrelevant": [x.chunk_id for x in too_far],
                       "dropped_rescan": [x.chunk_id for x in rescan]})
        self.last = {"route": r, "embedder": "e5" if _style == "standard" else f"e5-{_style}"}
        return results


# --------------------------------------------------------------------------- BN_native

class BNNative:
    """Nearest-attack similarity with E5, the query wrapping on both sides. flagged = sim > threshold."""

    def __init__(self, attack_texts: list[str], threshold: float):
        if not attack_texts:
            raise ValueError("BN_native needs at least one attack example")
        import numpy as np
        self.texts = attack_texts
        self.threshold = threshold
        self._np = np
        self.kb_emb = np.asarray(embed_query(attack_texts), dtype=float)

    def scores(self, texts: list[str], exclude: list[set[str]] | None = None) -> list[float]:
        """Max similarity to the attack KB. exclude[i] = KB texts to ignore for texts[i] (leave one
        family out when the scored documents carry the KB's own payloads)."""
        if not texts:
            return []
        np = self._np
        sims = np.asarray(embed_query(texts), dtype=float) @ self.kb_emb.T
        if exclude is not None:
            for i, ex in enumerate(exclude):
                for j, t in enumerate(self.texts):
                    if t in ex:
                        sims[i, j] = -np.inf
        return [round(float(x), 4) if np.isfinite(x) else None for x in sims.max(axis=1)]

    def score(self, text: str) -> float:
        return self.scores([text])[0]

    def check(self, text: str) -> dict:
        s = self.score(text)
        return {"flagged": s > self.threshold, "score": s}


def bn_attack_texts(dev_items: str | Path | None = None, extra: str | Path | None = None,
                    exclude_texts: set[str] | None = None) -> list[str]:
    """The BN_native attack KB: payloads of NON-English phase-1 (dev) items, plus an optional
    JSONL of {"text": ...} examples. Test items must never be in it (D-36): pass their
    payloads as exclude_texts and the function refuses to continue if one appears."""
    from pilot.phase_2.common2 import PHASE1_ITEMS, read_jsonl
    texts = []
    for it in read_jsonl(dev_items or PHASE1_ITEMS):
        if it.get("language") != "en" and it.get("payload"):
            texts.append(it["payload"])
    if extra and Path(extra).exists():
        texts += [r["text"] for r in read_jsonl(extra) if r.get("text")]
    texts = list(dict.fromkeys(t.strip() for t in texts if t.strip()))
    leak = set(texts) & (exclude_texts or set())
    if leak:
        raise ValueError(f"{len(leak)} test payload(s) found in the BN_native KB (contamination)")
    return texts


def load_threshold(calibration: str | Path | None, default: float | None = None, key: str = "bn_native") -> float:
    """Threshold from calibrate.py's calibration.json, or the default."""
    if calibration and _style != "standard" and Path(calibration).name == "calibration.json":
        calibration = Path(calibration).with_name(f"calibration_{_style}.json")   # calibrate.py's name for it
    if calibration and Path(calibration).exists():
        data = json.loads(Path(calibration).read_text(encoding="utf-8"))
        if key == "bn_native" and data.get("e5_prefix", "standard") != _style:
            raise SystemExit(f"{calibration} was calibrated with the {data.get('e5_prefix', 'standard')!r} E5 "
                             f"prefix but this run uses {_style!r}; re-run calibrate.py with --e5-prefix {_style}")
        thr = data.get("chosen", {}).get(key)
        if thr is not None:
            return float(thr)
    if default is None:
        raise SystemExit(f"no {key} threshold: run calibrate.py first or pass --bn-threshold")
    return default
