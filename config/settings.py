from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

_THRESHOLDS_YAML = Path(__file__).parent / "thresholds.yaml"


@dataclass
class SecurityThresholds:
    # Calibrated in prompt-injection-test.ipynb (Step 7). Re-run eval/calibrate_thresholds.py
    # whenever the embedder, KB-2 population, or guardrail adapter changes.
    l3_kb_match_threshold: float = 0.26
    narrative_match_threshold: float = 0.42
    kb5_pii_threshold: float = 0.20
    fast_path_ceiling: float = 0.25       # set to -1.0 to force every query through L3 (what the eval run used)
    l1_block_threshold: float = 0.55      # unused unless enable_l1_block=True
    enable_l1_block: bool = False
    enable_l2: bool = True
    enable_l2b: bool = True
    enable_l3: bool = True
    enable_l8: bool = True


@dataclass
class ModelSettings:
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"   # 384-d, shared by every KB
    guardrail_base_model: str = "meta-llama/Llama-Guard-3-1B"
    guardrail_adapter: str = "Arittroskr3232/llama-guard-3-1b-secure-rag"
    generation_model: str = "claude-sonnet-4-6"     # swap for whichever chat model you have API access to
    chroma_path: str = "./chroma_db"


@dataclass
class RBACDefaults:
    clearance_levels: dict = field(default_factory=lambda: {
        "public": 0, "customer": 1, "partner": 2, "employee": 3, "admin": 4,
    })


def load_thresholds(path: Path = _THRESHOLDS_YAML) -> SecurityThresholds:
    """Loads SecurityThresholds from thresholds.yaml, falling back to dataclass
    defaults for any key that's missing or if the file itself doesn't exist."""
    defaults = SecurityThresholds()
    if not path.exists():
        return defaults
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    valid_keys = {f.name for f in fields(SecurityThresholds)}
    overrides = {k: v for k, v in raw.items() if k in valid_keys}
    return SecurityThresholds(**{**defaults.__dict__, **overrides})
