"""Shared paths and helpers for the phase-2 extension (the senior's review of the full phase-2 report).

The extension reuses the phase-2 code (pilot/phase_2/*) instead of copying it, so a bug fixed
there is fixed here too. What it copies is the DATA it starts from (inputs/), so the inputs of
every extension result are frozen next to it even if phase 2 is re-run later.

Run every script from the repository root:  python -m pilot.phase_2_extension.<script> --help
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parent
ROOT = EXT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INPUTS = EXT_DIR / "inputs"
DATA = EXT_DIR / "data"
RESULTS = EXT_DIR / "results"
PHASE2_RESULTS = ROOT / "pilot" / "phase_2" / "results"

ITEMS = INPUTS / "pilot_items2.jsonl"          # the 80 phase-2 attack items
ALL_ITEMS = INPUTS / "all_items2.jsonl"        # attacks + ~pc + ~br controls
CALIBRATION = INPUTS / "calibration.json"      # phase-2 thresholds (L2b, BN_native)
OFFICIAL_CONTACTS = EXT_DIR / "official_contacts.yaml"

MODELS = {"3B": "llama3.2:3b", "8B": "llama3.1:8b", "Qwen": "qwen3:4b-instruct-2507-q4_K_M"}
VALID = {"3B": INPUTS / "valid_llama3.2-3b.json", "8B": INPUTS / "valid_llama3.1-8b.json",
         "Qwen": INPUTS / "valid_qwen3-4b-instruct-2507-q4-K-M.json"}
GROUP_ORDER = ["EN", "TR", "BL", "NT"]


def read_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def valid_items(key: str) -> list[str]:
    return json.loads(Path(VALID[key]).read_text(encoding="utf-8"))["items"]


def frac(k: int, n: int) -> str:
    """'k/n (p%)' or '-' for an empty cell."""
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "-"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


def frac_ci(k: int, n: int) -> str:
    if not n:
        return "-"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%, {100 * lo:.0f}–{100 * hi:.0f}%)"


def truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def md_table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out
