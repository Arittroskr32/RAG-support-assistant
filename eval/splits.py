"""One deterministic split of the security datasets, shared by every script.

    train_dataset.jsonl
      unsafe -> sample of <= KB2_CAP (seed 42)
                 ├── first 85%  -> "kb2"                 (inserted into KB-2)
                 └── last  15%  -> "calib_unsafe_holdout"(never in KB-2)
      safe   -> "calib_train_safe"
    test_dataset.jsonl
      25% (seed 123) -> "calib_test"   (used for threshold calibration only)
      75%            -> "eval_test"    (the only part used for reported metrics)

The seeds and sampling calls reproduce prompt-injection-test.ipynb. Indices are saved to
data/security_datasets/splits.json together with SHA-256 hashes of the source files; if a
source file changes, the split is regenerated (and a warning printed) instead of silently
mixing old indices with new data.
"""
import hashlib
import json
import random
from functools import lru_cache

from config.settings import SECURITY_DATASETS_DIR

TRAIN_PATH = SECURITY_DATASETS_DIR / "train_dataset.jsonl"
TEST_PATH = SECURITY_DATASETS_DIR / "test_dataset.jsonl"
SPLITS_PATH = SECURITY_DATASETS_DIR / "splits.json"
RED_TEAM_PATH = SECURITY_DATASETS_DIR / "red_team_appended.jsonl"

KB2_CAP = 5000
KB2_FRACTION = 0.85
TEST_CALIB_FRACTION = 0.25
KB2_SEED = 42
TEST_SEED = 123
MAX_SAFE_MATERIALIZED = 50_000


def load_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _make_split_indices(train: list[dict], test: list[dict]) -> dict:
    unsafe_idx = [i for i, d in enumerate(train) if d.get("ground_truth_input") == "unsafe"]
    safe_idx = [i for i, d in enumerate(train) if d.get("ground_truth_input") == "safe"]
    sample = random.Random(KB2_SEED).sample(unsafe_idx, min(KB2_CAP, len(unsafe_idx)))
    cut = int(len(sample) * KB2_FRACTION)
    calib_test = random.Random(TEST_SEED).sample(range(len(test)), int(len(test) * TEST_CALIB_FRACTION))
    calib_set = set(calib_test)
    return {
        "kb2": sample[:cut],
        "calib_unsafe_holdout": sample[cut:],
        "calib_train_safe": safe_idx,
        "calib_test": calib_test,
        "eval_test": [i for i in range(len(test)) if i not in calib_set],
    }


@lru_cache(maxsize=1)
def get_splits() -> dict[str, list[dict]]:
    """Returns {split_name: [records]}; each record gets an '_idx' field (its line number
    in the source file) so results can be traced back."""
    train, test = load_jsonl(TRAIN_PATH), load_jsonl(TEST_PATH)
    hashes = {"train_sha256": sha256_file(TRAIN_PATH), "test_sha256": sha256_file(TEST_PATH)}

    indices = None
    if SPLITS_PATH.exists():
        saved = json.loads(SPLITS_PATH.read_text())
        if {k: saved.get(k) for k in hashes} == hashes:
            indices = saved["indices"]
        else:
            print(f"WARNING: dataset files changed since {SPLITS_PATH.name} was written — regenerating "
                  "the split. Rebuild KB-2 and re-calibrate before reporting results.")
    if indices is None:
        indices = _make_split_indices(train, test)
        SPLITS_PATH.write_text(json.dumps({**hashes, "indices": indices}))

    def pick(src, idxs):
        return [{**src[i], "_idx": i} for i in idxs]

    return {
        "kb2": pick(train, indices["kb2"]),
        "calib_unsafe_holdout": pick(train, indices["calib_unsafe_holdout"]),
        # Calibration uses at most 3x the holdout (after canary filtering), so only the
        # first MAX_SAFE_MATERIALIZED safe rows are kept in memory (the full train set is ~800k rows).
        "calib_train_safe": pick(train, indices["calib_train_safe"][:MAX_SAFE_MATERIALIZED]),
        "calib_test": pick(test, indices["calib_test"]),
        "eval_test": pick(test, indices["eval_test"]),
    }


def dataset_fingerprint() -> dict:
    """Hashes recorded alongside every experiment for reproducibility."""
    out = {}
    for name, path in (("train", TRAIN_PATH), ("test", TEST_PATH)):
        out[f"{name}_sha256"] = sha256_file(path) if path.exists() else None
    return out
