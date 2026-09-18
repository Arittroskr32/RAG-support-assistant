"""Joint threshold calibration for the embedding-based detection layers.

Why joint: a benign prompt is blocked if ANY layer fires, so calibrating KB-2 and KB-6
to FPR <= 8% *separately* lets their false positives add up (plus L2 and L3) — which is
how the pipeline ended at ~16% FPR. This script sweeps both thresholds together and picks
the pair that maximizes recall of the *combined* decision

    blocked = L2_regex  OR  kb2_dist < t_kb2  OR  kb6_dist < t_kb6  [OR  L3_llm]

subject to combined FPR <= target.

- Uses only the calibration splits from eval/splits.py (the KB-2 holdout is never inside
  KB-2, and calib_test is excluded from reported metrics).
- Distances use the same windowed embeddings as the live pipeline.
- --with-l3 runs the fine-tuned guardrail on every calibration prompt (GPU recommended)
  and includes it in the union. Without it, --l3-fpr-reserve (default 3 points) of the
  FPR budget is held back for L3.
- Writes the chosen thresholds into config/thresholds.yaml, leaving all other keys as they are.

    python -m eval.calibrate_thresholds [--target-fpr 0.08] [--with-l3 | --l3-fpr-reserve 0.03]
"""
import argparse
import random
import re

import numpy as np
import yaml

from config.settings import _THRESHOLDS_YAML, get_thresholds, reload_thresholds
from eval.splits import get_splits
from knowledge_bases.kb_manager import kb, split_windows
from security import l2_pattern_filter

KB2_RANGE = (0.05, 0.60, 0.01)
KB6_RANGE = (0.15, 0.65, 0.01)
QUERY_BATCH = 256


def looks_like_pwned_canary(text):
    """Excludes PWNED-canary-style prompts from the safe side of calibration — if they're
    mislabeled 'safe', including them would calibrate thresholds to tolerate exactly the
    false positives you're trying to eliminate."""
    markers = [r"ignore previous instructions", r"i have been pwned",
               r"disregard (all |the )?(prior|previous|above)"]
    return any(re.search(p, text, re.IGNORECASE) for p in markers)


def build_calibration_pool(calib_test_sample: int = 0):
    s = get_splits()
    safe_train = [d for d in s["calib_train_safe"] if not looks_like_pwned_canary(d["input_prompt"])]
    calib_test = s["calib_test"]
    if calib_test_sample and calib_test_sample < len(calib_test):   # quick runs only
        calib_test = random.Random(7).sample(calib_test, calib_test_sample)
    test_unsafe = [d for d in calib_test if d.get("ground_truth_input") == "unsafe"]
    test_safe = [d for d in calib_test
                 if d.get("ground_truth_input") == "safe" and not looks_like_pwned_canary(d["input_prompt"])]
    holdout = s["calib_unsafe_holdout"]
    # Same composition/weighting as the notebook: test-distribution prompts counted twice.
    pool = holdout + safe_train[:len(holdout) * 3] + test_unsafe * 2 + test_safe * 2
    prompts = [d["input_prompt"] for d in pool]
    labels = np.array([d.get("ground_truth_input") == "unsafe" for d in pool])
    return prompts, labels


def min_distances(prompts, collection, cfg) -> np.ndarray:
    """Windowed nearest-neighbour distance per prompt (min over its windows), batched."""
    owners, windows = [], []
    for i, p in enumerate(prompts):
        ws = split_windows(p, cfg.embed_window_words, cfg.embed_window_stride) if cfg.enable_windowed_embedding else [p]
        owners += [i] * len(ws)
        windows += ws
    dists = np.ones(len(prompts))
    if collection.count() == 0:
        return dists
    for start in range(0, len(windows), QUERY_BATCH):
        embs = kb.embed(windows[start:start + QUERY_BATCH])
        res = collection.query(query_embeddings=embs, n_results=1, include=["distances"])
        for j, d in enumerate(res["distances"]):
            if d:
                k = owners[start + j]
                dists[k] = min(dists[k], d[0])
    return dists


def _rates(pred, labels):
    tp = np.sum(pred & labels); fn = np.sum(~pred & labels)
    fp = np.sum(pred & ~labels); tn = np.sum(~pred & ~labels)
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return float(recall), float(fpr)


def joint_sweep(kb2_d, kb6_d, base_pred, labels, target_fpr):
    """Returns (t_kb2, t_kb6, recall, fpr). Maximizes recall s.t. FPR <= target (ties ->
    lower FPR); if no pair meets the target, returns the lowest-FPR pair."""
    best, fallback = None, None
    for t2 in np.arange(*KB2_RANGE):
        hit2 = base_pred | (kb2_d < t2)
        for t6 in np.arange(*KB6_RANGE):
            recall, fpr = _rates(hit2 | (kb6_d < t6), labels)
            cand = (round(float(t2), 3), round(float(t6), 3), recall, fpr)
            if fpr <= target_fpr and (best is None or (recall, -fpr) > (best[2], -best[3])):
                best = cand
            if fallback is None or (fpr, -recall) < (fallback[3], -fallback[2]):
                fallback = cand
    if best is None:
        print(f"  No threshold pair reaches FPR <= {target_fpr:.2%}; using the lowest-FPR pair "
              f"({fallback[3]:.2%}). L2/L3 alone may already exceed the budget.")
        return fallback
    return best


def calibrate(target_fpr=0.08, with_l3=False, l3_fpr_reserve=0.03, calib_test_sample=0):
    cfg = get_thresholds()
    prompts, labels = build_calibration_pool(calib_test_sample)
    budget = target_fpr if with_l3 else max(target_fpr - l3_fpr_reserve, 0.0)
    print(f"Calibrating on {len(prompts)} prompts ({labels.sum()} unsafe, {(~labels).sum()} safe); "
          f"end-to-end FPR target {target_fpr:.0%}, budget for L2+KB-2+KB-6{'+L3' if with_l3 else ''}: {budget:.1%}")

    l2_pred = np.array([l2_pattern_filter.matches_known_injection(p, cfg.enable_l2_extended_patterns)
                        if cfg.enable_l2 else False for p in prompts])
    base = l2_pred.copy()
    if with_l3:
        from security import l3_llm_guardrail
        l3_pred = np.array([l3_llm_guardrail.classify(p) == "unsafe" for p in prompts])
        base |= l3_pred
        print("  L3 alone:        recall=%.2f%%  FPR=%.2f%%" % tuple(100 * x for x in _rates(l3_pred, labels)))
    print("  L2 alone:        recall=%.2f%%  FPR=%.2f%%" % tuple(100 * x for x in _rates(l2_pred, labels)))

    kb2_d = min_distances(prompts, kb.kb2_attacks, cfg)
    kb6_d = min_distances(prompts, kb.kb6_narrative, cfg)
    t2, t6, recall, fpr = joint_sweep(kb2_d, kb6_d, base, labels, budget)

    print(f"  KB-2 alone @ {t2}: recall=%.2f%%  FPR=%.2f%%" % tuple(100 * x for x in _rates(kb2_d < t2, labels)))
    print(f"  KB-6 alone @ {t6}: recall=%.2f%%  FPR=%.2f%%" % tuple(100 * x for x in _rates(kb6_d < t6, labels)))
    print(f"Combined: recall={recall:.2%}  FPR={fpr:.2%}  ->  l3_kb_match_threshold={t2}, narrative_match_threshold={t6}")
    return t2, t6


def write_thresholds(l3_kb_match_threshold, narrative_match_threshold, path=_THRESHOLDS_YAML):
    current = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
    current.update(l3_kb_match_threshold=float(l3_kb_match_threshold),
                   narrative_match_threshold=float(narrative_match_threshold))
    path.write_text(yaml.safe_dump(current, sort_keys=False))
    reload_thresholds()
    print(f"Wrote calibrated thresholds to {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-fpr", type=float, default=0.08, help="end-to-end FPR ceiling (paper target <10%%)")
    ap.add_argument("--with-l3", action="store_true", help="include the guardrail LLM's decisions in the union")
    ap.add_argument("--l3-fpr-reserve", type=float, default=0.03, help="FPR budget held back for L3 when not --with-l3")
    ap.add_argument("--calib-test-sample", type=int, default=0,
                    help="use only N prompts of the calib_test split (quick runs; 0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="print results without writing thresholds.yaml")
    args = ap.parse_args()
    t2, t6 = calibrate(args.target_fpr, args.with_l3, args.l3_fpr_reserve, args.calib_test_sample)
    if not args.dry_run:
        write_thresholds(t2, t6)
