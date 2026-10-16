"""Plan step B6: calibrate the ingestion detectors at a fixed false-quarantine rate.

  python -m pilot.phase_2.calibrate --target 0.02
  python -m pilot.phase_2.calibrate --target 0.02 --with-l3          # L3 on every benign chunk (GPU, slow)
  python -m pilot.phase_2.calibrate --target 0.02 --target-extra 0.05

The threshold is chosen on BENIGN support documents only, so that at most --target of
benign chunks would be quarantined. The attack documents are only scored afterwards, at
that threshold; they never move it (the senior: calibrate at a fixed false-quarantine rate,
not to catch the 24 calibration attacks).

Benign documents: pilot/phase_2/data/benign_docs/<lang>/*.md|*.txt with <lang> in
en, bn, banglish. --include-repo-data also counts the repository's own data/ documents as
English benign text (they are the real support corpus).

Detectors (the ingestion scan of ingestion/build_kb4.py, plus BN_native):
  L2ext      regex, no threshold: only its false-quarantine rate is reported
  L2b        KB-6 distance, flag if distance < threshold   (narrative_match_threshold;
             the same key is used by the query-side L2b, so changing it moves L2b's FPR too)
  L3         guardrail verdict, no threshold (only with --with-l3)
  BN_native  E5 similarity to the Bangla attack KB, flag if similarity > threshold;
             calibrated on bn + banglish benign chunks only (it only sees Bangla-routed text)

Writes pilot/phase_2/results/calibration.json (read by stack_check2.py) and calibration.md;
with --e5-prefix tagged the files are calibration_tagged.json / .md instead.
config/thresholds.yaml is NOT changed: copy the printed values yourself once agreed.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from pilot.phase_2 import tags
from pilot.phase_2.common2 import DATA2_DIR, PHASE1_ITEMS, RESULTS_DIR, ROOT, group_code, load_items2

LANGS = ("en", "bn", "banglish")


def load_benign(benign_dir: Path, include_repo_data: bool) -> list[dict]:
    """Benign chunks: [{"lang", "source", "text"}], chunked like ingestion does."""
    from ingestion.chunkers import chunk_document
    from ingestion.loaders import parse_front_matter
    docs = []
    for lang in LANGS:
        for p in sorted((benign_dir / lang).glob("*")):
            if p.suffix.lower() in (".md", ".txt"):
                text = tags.unwrap(p.read_text(encoding="utf-8"), "passage")
                docs.append((lang, f"{lang}/{p.name}", parse_front_matter(text)[1]))   # as ingestion does
    if include_repo_data:
        from ingestion.loaders import load_documents
        for d in load_documents(ROOT / "data"):
            docs.append(("en", f"data/{d['source_doc_id']}", d["text"]))
    chunks = []
    for lang, src, text in docs:
        for c in chunk_document(text, "product_info", Path(src).stem):
            if c.strip():
                chunks.append({"lang": lang, "source": src, "text": c})
    return chunks


def threshold_below(scores: list[float], target: float) -> float:
    """Largest t such that the share of scores strictly below t is <= target (flag if s < t)."""
    s = sorted(scores)
    k = math.floor(target * len(s))
    return s[k] if k < len(s) else s[-1] + 1e-6


def threshold_above(scores: list[float], target: float) -> float:
    """Smallest t such that the share of scores strictly above t is <= target (flag if s > t)."""
    s = sorted(scores, reverse=True)
    k = math.floor(target * len(s))
    return s[k] if k < len(s) else s[-1] - 1e-6


def rate(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)} ({100 * sum(flags) / len(flags):.1f}%)" if flags else "-"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benign-dir", default=str(DATA2_DIR / "benign_docs"))
    ap.add_argument("--include-repo-data", action="store_true")
    ap.add_argument("--attacks", default=str(PHASE1_ITEMS),
                    help="attack items to score at the chosen thresholds (default: phase-1 dev items)")
    ap.add_argument("--target", type=float, default=0.02, help="false-quarantine rate, e.g. 0.02")
    ap.add_argument("--target-extra", type=float, nargs="*", default=[0.05], help="sensitivity rows")
    ap.add_argument("--with-l3", action="store_true")
    ap.add_argument("--no-bn", action="store_true", help="skip BN_native (no E5 model)")
    ap.add_argument("--bn-extra", help="extra BN_native attack examples (JSONL with 'text')")
    ap.add_argument("--out-dir", default=str(RESULTS_DIR))
    ap.add_argument("--e5-prefix", choices=["standard", "tagged"], default="standard",
                    help="E5 wrapping: standard = query:/passage: (default), tagged = <!><query> ... <!query>")
    a = ap.parse_args(argv)
    from pilot.phase_2 import bn_route as _bn
    _bn.set_prefix_style(a.e5_prefix)

    from config.settings import get_thresholds
    from pilot.phase_1 import layers
    from pilot.phase_2 import bn_route

    cfg = get_thresholds()
    benign = load_benign(Path(a.benign_dir), a.include_repo_data)
    if not benign:
        raise SystemExit(f"no benign documents under {a.benign_dir} (see pilot/phase_2/data/README.md)")
    n_lang = defaultdict(int)
    for c in benign:
        n_lang[c["lang"]] += 1
    warnings = [f"only {n} benign {lang} chunks: a {a.target:.0%} rate needs at least {math.ceil(2 / a.target)} "
                f"to be more than a couple of chunks" for lang, n in n_lang.items() if n * a.target < 2]
    attacks = [i for i in load_items2(a.attacks) if i["variant"] == "attack"]
    if Path(a.attacks).resolve() != PHASE1_ITEMS.resolve():
        warnings.append(f"attack items from {a.attacks}: fine for reporting, but never re-pick thresholds "
                        f"after looking at test-set detection rates")

    bn = None
    if not a.no_bn:
        # phase-1 items carry their own old "split" field (cal/test); in phase 2 they are all dev
        # items, so only phase-2 test payloads are excluded from the BN_native attack KB
        is_phase1 = Path(a.attacks).resolve() == PHASE1_ITEMS.resolve()
        test_payloads = set() if is_phase1 else {i.get("payload", "").strip() for i in attacks
                                                 if i.get("split") == "test"}
        bn = bn_route.BNNative(bn_route.bn_attack_texts(extra=a.bn_extra, exclude_texts=test_payloads),
                               threshold=1.0)

    def score_all(texts):
        out = {"L2ext": [layers.l2_pattern(t, extended=True)["flagged"] for t in texts],
               "L2b": [layers.l2b_narrative(t)["score"] for t in texts]}
        if a.with_l3:
            out["L3"] = [layers.l3_guardrail(t)["flagged"] for t in texts]
        if bn:
            routed = [bn_route.is_bangla(t) for t in texts]
            sims = bn.scores([t for t, r in zip(texts, routed) if r])
            it = iter(sims)
            out["BN_native"] = [next(it) if r else None for r in routed]
        return out

    b_scores = score_all([c["text"] for c in benign])
    langs = [c["lang"] for c in benign]
    a_scores = score_all([i["carrier_doc"] for i in attacks])
    a_groups = [group_code(i) for i in attacks]

    targets = [a.target] + [t for t in a.target_extra if t != a.target]
    result = {"target_fqr": a.target, "e5_prefix": a.e5_prefix, "n_benign_chunks": dict(n_lang), "n_attacks": len(attacks),
              "attacks_file": a.attacks, "current": {"L2b": cfg.narrative_match_threshold},
              "thresholds": {}, "chosen": {}, "warnings": warnings}
    md = [f"# Ingestion detector calibration (target false-quarantine rate {a.target:.0%})", "",
          f"Benign chunks: {dict(n_lang)}. Attack documents: {len(attacks)} from `{a.attacks}`.", ""]
    for w in warnings:
        md.append(f"> Warning: {w}")
    md += ["", "## Thresholds chosen on benign chunks", "",
           "| Detector | Target | Threshold | Benign flagged: en | bn | banglish |", "|---|---|---|---|---|---|"]

    def flags_at(det, thr, scores):
        if det == "L2b":
            return [s is not None and s < thr for s in scores]
        return [s is not None and s > thr for s in scores]

    for t in targets:
        for det in ("L2b", "BN_native"):
            if det not in b_scores:
                continue
            pool = [s for s, lang in zip(b_scores[det], langs)
                    if s is not None and (det != "BN_native" or lang != "en")]
            if not pool:
                continue
            thr = threshold_below(pool, t) if det == "L2b" else threshold_above(pool, t)
            result["thresholds"].setdefault(det, {})[str(t)] = round(thr, 4)
            if t == a.target:
                result["chosen"][{"L2b": "narrative_match_threshold", "BN_native": "bn_native"}[det]] = round(thr, 4)
            fl = flags_at(det, thr, b_scores[det])
            cells = [rate([f for f, lang, s in zip(fl, langs, b_scores[det]) if lang == L and s is not None])
                     for L in LANGS]
            md.append(f"| {det} | {t:.0%} | {thr:.4f} | " + " | ".join(cells) + " |")
    # regex / verdict detectors: only their false-quarantine rate
    md += ["", "## Detectors without a threshold (false-quarantine rate on benign chunks)", "",
           "| Detector | en | bn | banglish |", "|---|---|---|---|"]
    for det in ("L2ext", "L3"):
        if det in b_scores:
            md.append(f"| {det} | " + " | ".join(
                rate([f for f, lang in zip(b_scores[det], langs) if lang == L]) for L in LANGS) + " |")

    # attacks at the chosen thresholds
    md += ["", "## Attack documents flagged at the chosen thresholds", "",
           "| Detector | " + " | ".join(sorted(set(a_groups))) + " |", "|---|" + "---|" * len(set(a_groups))]
    chosen_thr = {"L2b": result["chosen"].get("narrative_match_threshold"),
                  "BN_native": result["chosen"].get("bn_native")}
    for det in ("L2ext", "L2b", "L3", "BN_native"):
        if det not in a_scores:
            continue
        if det in chosen_thr:
            if chosen_thr[det] is None:
                continue
            fl = flags_at(det, chosen_thr[det], a_scores[det])
        else:
            fl = [bool(x) for x in a_scores[det]]
        md.append(f"| {det} | " + " | ".join(rate([f for f, g in zip(fl, a_groups) if g == G])
                                              for G in sorted(set(a_groups))) + " |")
    if "L2b" in chosen_thr and chosen_thr["L2b"] is not None:
        md += ["", f"Current `narrative_match_threshold` in config/thresholds.yaml: {cfg.narrative_match_threshold}. "
                   f"Calibrated: {chosen_thr['L2b']}."]

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"lang": c["lang"], "source": c["source"], **{k: v[i] for k, v in b_scores.items()}}
            for i, c in enumerate(benign)]
    stem = "calibration" + ("" if a.e5_prefix == "standard" else f"_{a.e5_prefix}")
    result["benign_scores_file"] = f"{stem}_benign_scores.jsonl"
    with open(out / f"{stem}_benign_scores.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{stem}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {out / (stem + '.json')} and {stem}.md")


if __name__ == "__main__":
    main()
