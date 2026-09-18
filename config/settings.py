"""Central configuration.

- All filesystem paths are anchored to PROJECT_ROOT, so scripts behave the same no matter
  which directory they're launched from.
- `get_thresholds()` loads config/thresholds.yaml once (falling back to the dataclass
  defaults for missing keys). Every layer takes an explicit `cfg` argument that defaults
  to it, so the ablation runner can pass a modified copy per experiment instead of
  mutating globals.
"""
import os
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from pathlib import Path

import yaml

try:  # optional: pip install python-dotenv
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
SECURITY_DATASETS_DIR = DATA_DIR / "security_datasets"
LOGS_DIR = PROJECT_ROOT / "logs"
EVAL_RESULTS_DIR = PROJECT_ROOT / "eval" / "results"
_THRESHOLDS_YAML = CONFIG_DIR / "thresholds.yaml"


@dataclass(frozen=True)
class SecurityThresholds:
    # --- Calibrated distances (cosine distance; lower = more similar). Re-run
    # eval/calibrate_thresholds.py whenever the embedder, KB-2/KB-6 population, windowing,
    # or guardrail adapter changes.
    l3_kb_match_threshold: float = 0.26       # KB-2 distance below which the query is blocked outright
    narrative_match_threshold: float = 0.42   # KB-6 distance below which L2b blocks
    kb5_pii_threshold: float = 0.20           # KB-5 distance (per sentence) below which L8 blocks

    # --- L1 risk scoring
    risk_distance_scale: float = 0.65         # risk = 1 - kb2_distance / scale
    # -1.0 = every query goes through the L3 LLM (the configuration the reported ARR/FPR
    # were measured with). A value >= 0 lets low-risk queries skip L3 — but "low risk"
    # means "far from known attacks", so novel attacks skip L3 too. Only enable for a
    # measured latency/ARR trade-off experiment.
    fast_path_ceiling: float = -1.0
    l1_block_threshold: float = 0.55          # used only when enable_l1_block=True
    enable_l1_block: bool = False

    # --- KB-1 rate limiting
    rate_limit_window_s: int = 60
    rate_limit_soft: int = 50                 # above this, risk_score += rate_limit_risk_bump
    rate_limit_risk_bump: float = 0.2
    rate_limit_hard: int = 120                # above this, the request is rejected (HTTP 429)

    # --- Layer toggles (ablation)
    enable_l2: bool = True
    enable_l2_extended_patterns: bool = False  # generic "ignore previous instructions"-style
                                               # patterns; off by default because they caused
                                               # false positives in prompt-injection-test.ipynb
    enable_l2b: bool = True
    enable_kb2_match: bool = True              # KB-2 nearest-attack short-circuit (embedding only)
    enable_l3: bool = True                     # fine-tuned guardrail LLM
    enable_rbac: bool = True                   # L4/L5 clearance + document-type + tenant filter
    enable_intent_narrowing: bool = False      # L4 keyword intent classifier narrowing allowed types
    enable_l6: bool = True                     # [DOCUMENT] tagging; False = raw concatenated chunks
    enable_retrieval_rescan: bool = True       # re-run L2 on retrieved chunks at query time
    enable_l8: bool = True
    enable_presidio: bool = False              # extra NER-based PII detection in L8 (pip install presidio-analyzer)

    # --- Embedding windowing: all-MiniLM-L6-v2 truncates at 256 word-pieces, so long
    # prompts are embedded as overlapping windows and the minimum distance is used.
    enable_windowed_embedding: bool = True
    embed_window_words: int = 150
    embed_window_stride: int = 100

    # --- Retrieval
    retrieval_top_k: int = 6
    retrieval_max_distance: float = 0.60       # chunks farther than this are dropped as irrelevant

    # --- API / response behaviour
    max_query_chars: int = 4000
    expose_block_layer: bool = False           # True only for debugging/eval — tells a caller which layer blocked them


@dataclass(frozen=True)
class ModelSettings:
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"   # 384-d, shared by every KB
    guardrail_base_model: str = "meta-llama/Llama-Guard-3-1B"
    guardrail_adapter: str = "Arittroskr3232/llama-guard-3-1b-secure-rag"
    # The adapter was evaluated (prompt-injection-test.ipynb) with a hand-built prompt that
    # already starts with <|begin_of_text|> AND the tokenizer's default special tokens, i.e.
    # a doubled BOS. Keep True to reproduce the measured results; set False only if the
    # adapter's training script tokenized with add_special_tokens=False.
    guardrail_add_special_tokens: bool = True
    guardrail_max_input_tokens: int = 512
    # L7 backend: "local" = any OpenAI-compatible server on your machine (Ollama, LM Studio,
    # llama.cpp server, vLLM); "anthropic" = Claude API.
    generation_backend: str = os.getenv("GENERATION_BACKEND", "local")
    local_llm_base_url: str = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")   # Ollama default
    local_llm_model: str = os.getenv("LOCAL_LLM_MODEL", "llama3.1:8b")
    local_llm_api_key: str = os.getenv("LOCAL_LLM_API_KEY", "")                # most local servers need none
    local_llm_temperature: float = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.1"))
    local_llm_max_tokens: int = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "1500"))
    local_llm_timeout_s: float = float(os.getenv("LOCAL_LLM_TIMEOUT_S", "180"))
    generation_model: str = os.getenv("GENERATION_MODEL", "claude-opus-5")    # anthropic backend
    generation_max_tokens: int = 16000
    generation_effort: str = "medium"          # low | medium | high | xhigh | max
    generation_server_fallbacks: bool = True   # re-run refused requests on Anthropic's recommended fallback
    chroma_path: str = os.getenv("CHROMA_PATH", str(PROJECT_ROOT / "chroma_db"))
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))


@dataclass(frozen=True)
class APISettings:
    api_keys_file: Path = CONFIG_DIR / "api_keys.yaml"
    # If True, requests without an API key are served as role "public" / tenant "default".
    allow_anonymous: bool = os.getenv("ALLOW_ANONYMOUS", "true").lower() == "true"
    # Only trust X-Forwarded-For when running behind a reverse proxy you control.
    trust_forwarded_for: bool = os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true"
    # Browser accounts (api/accounts.py): registered users start as the default role;
    # role_assignments.json gives specific emails another role.
    users_file: Path = CONFIG_DIR / "users.json"
    role_assignments_file: Path = CONFIG_DIR / "role_assignments.json"
    session_secret_file: Path = CONFIG_DIR / "session_secret"
    session_ttl_s: int = int(float(os.getenv("SESSION_TTL_HOURS", "168")) * 3600)
    allow_registration: bool = os.getenv("ALLOW_REGISTRATION", "true").lower() == "true"


def load_thresholds(path: Path = _THRESHOLDS_YAML) -> SecurityThresholds:
    """Loads SecurityThresholds from thresholds.yaml, falling back to dataclass defaults
    for any key that's missing or if the file itself doesn't exist. Unknown keys raise so
    a typo in the YAML can't silently leave a layer misconfigured."""
    defaults = SecurityThresholds()
    if not path.exists():
        return defaults
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    valid_keys = {f.name for f in fields(SecurityThresholds)}
    unknown = set(raw) - valid_keys
    if unknown:
        raise ValueError(f"Unknown keys in {path}: {sorted(unknown)}")
    return replace(defaults, **raw)


@lru_cache(maxsize=1)
def get_thresholds() -> SecurityThresholds:
    return load_thresholds()


def reload_thresholds() -> SecurityThresholds:
    get_thresholds.cache_clear()
    return get_thresholds()


MODEL_SETTINGS = ModelSettings()
API_SETTINGS = APISettings()
