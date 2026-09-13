"""Ports `sweep_threshold_fpr_constrained` / `get_min_distances` from
prompt-injection-test.ipynb (Step 7) so thresholds can be re-calibrated any time the
embedder, KB-2/KB-6 population, or guardrail adapter changes — without re-running the
notebook. Writes results to config/thresholds.yaml.

Expects data/security_datasets/{train_dataset.jsonl,test_dataset.jsonl} in the same
`{"input_prompt": ..., "ground_truth_input": "safe"|"unsafe"}` shape used to build KB-2/KB-6.
"""
import json
import random
import re

import numpy as np
import yaml

from config.settings import _THRESHOLDS_YAML, SecurityThresholds
from knowledge_bases.kb_manager import kb

TRAIN_PATH = "data/security_datasets/train_dataset.jsonl"
TEST_PATH = "data/security_datasets/test_dataset.jsonl"
TARGET_FPR_CEILING = 0.08  # stay under 8%, leaving margin below the <10% paper target
TEST_CALIB_FRACTION = 0.25


def get_min_distances(prompts, collection, batch_size=64):
    dists = []
    for i in range(0, len(prompts), batch_size):
        batch = prompts[i:i + batch_size]
        embs = kb.embed(batch)
        for e in embs:
            res = collection.query(query_embeddings=[e], n_results=1)
            d = res["distances"][0][0] if res.get("distances") and res["distances"][0] else 1.0
            dists.append(d)
    return dists


def sweep_threshold_fpr_constrained(dists, labels, target_fpr, lo=0.05, hi=0.60, step=0.01):
    """Pick the threshold that maximizes recall while keeping FPR <= target_fpr on this
    calibration set. Falls back to the lowest-FPR threshold found if none meet the target
    (better to under-block than silently exceed the ceiling)."""
    best_thresh, best_recall, best_fpr_at_best = None, -1, None
    fallback_thresh, fallback_fpr = None, 2.0
    for t in np.arange(lo, hi, step):
        preds = [1 if d < t else 0 for d in dists]
        tp = sum(1 for p, l in zip(preds, labels) if p == 1 and l == 1)
        fp = sum(1 for p, l in zip(preds, labels) if p == 1 and l == 0)
        fn = sum(1 for p, l in zip(preds, labels) if p == 0 and l == 1)
        tn = sum(1 for p, l in zip(preds, labels) if p == 0 and l == 0)
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
        if fpr <= target_fpr and recall > best_recall:
            best_recall, best_thresh, best_fpr_at_best = recall, t, fpr
        if fpr < fallback_fpr:
            fallback_fpr, fallback_thresh = fpr, t
    if best_thresh is None:
        print(f"  No threshold hit target FPR {target_fpr:.2%} — using lowest-FPR fallback ({fallback_fpr:.2%} FPR).")
        return round(float(fallback_thresh), 3), fallback_fpr
    return round(float(best_thresh), 3), best_fpr_at_best


def looks_like_pwned_canary(text):
    """Excludes PWNED-canary-style prompts from the safe side of calibration — if they're
    mislabeled 'safe', including them would calibrate thresholds to tolerate exactly the
    false positives you're trying to eliminate."""
    markers = [r"ignore previous instructions", r"i have been pwned",
               r"disregard (all |the )?(prior|previous|above)"]
    return any(re.search(p, text, re.IGNORECASE) for p in markers)


def _load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def calibrate():
    train_data = _load_jsonl(TRAIN_PATH)
    test_data = _load_jsonl(TEST_PATH)

    train_unsafe_all = [d for d in train_data if d.get("ground_truth_input") == "unsafe"]
    train_safe = [d for d in train_data if d.get("ground_truth_input") == "safe"]

    random.seed(42)
    cap_size = min(5000, len(train_unsafe_all))
    train_unsafe = random.sample(train_unsafe_all, cap_size)
    split_idx = int(len(train_unsafe) * 0.85)
    calib_unsafe_holdout = train_unsafe[split_idx:]   # KB-2 is built from train_unsafe[:split_idx] only

    random.seed(123)
    test_calib_slice = random.sample(test_data, int(len(test_data) * TEST_CALIB_FRACTION))

    calib_train_safe = [d for d in train_safe if not looks_like_pwned_canary(d["input_prompt"])]
    calib_test_safe = [d for d in test_calib_slice
                        if d.get("ground_truth_input") == "safe" and not looks_like_pwned_canary(d["input_prompt"])]
    calib_test_unsafe = [d for d in test_calib_slice if d.get("ground_truth_input") == "unsafe"]

    calib_pool = (
        calib_unsafe_holdout
        + calib_train_safe[:len(calib_unsafe_holdout) * 3]
        + calib_test_unsafe * 2
        + calib_test_safe * 2
    )
    calib_prompts = [d["input_prompt"] for d in calib_pool]
    calib_labels = [1 if d.get("ground_truth_input") == "unsafe" else 0 for d in calib_pool]

    print(f"Calibrating on {len(calib_pool)} prompts "
          f"({sum(calib_labels)} unsafe, {len(calib_labels) - sum(calib_labels)} safe), "
          f"target FPR ceiling {TARGET_FPR_CEILING:.0%}...")

    kb2_dists = get_min_distances(calib_prompts, kb.kb2_attacks)
    l3_kb_match_threshold, kb2_fpr = sweep_threshold_fpr_constrained(kb2_dists, calib_labels, TARGET_FPR_CEILING)

    kb6_dists = get_min_distances(calib_prompts, kb.kb6_narrative)
    narrative_match_threshold, kb6_fpr = sweep_threshold_fpr_constrained(
        kb6_dists, calib_labels, TARGET_FPR_CEILING, lo=0.15, hi=0.65)

    print(f"Calibrated L3 KB match threshold: {l3_kb_match_threshold} (calib FPR={kb2_fpr:.2%})")
    print(f"Calibrated narrative match threshold: {narrative_match_threshold} (calib FPR={kb6_fpr:.2%})")

    return l3_kb_match_threshold, narrative_match_threshold


def write_thresholds(l3_kb_match_threshold, narrative_match_threshold):
    current = SecurityThresholds()
    updated = {**current.__dict__, "l3_kb_match_threshold": l3_kb_match_threshold,
               "narrative_match_threshold": narrative_match_threshold}
    with open(_THRESHOLDS_YAML, "w") as f:
        yaml.safe_dump(updated, f, sort_keys=False)
    print(f"Wrote calibrated thresholds to {_THRESHOLDS_YAML}")


if __name__ == "__main__":
    l3_thresh, narrative_thresh = calibrate()
    write_thresholds(l3_thresh, narrative_thresh)
