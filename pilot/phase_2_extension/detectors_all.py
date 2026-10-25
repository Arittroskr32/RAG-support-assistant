"""Every chunk detector on every phase-2 document (senior, point 3 and the RQ1 design point).

Detection does not depend on the generator, so it is measured once, on all documents, not only on
one model's valid items:
  attack      the 80 phase-2 attack documents
  base_rate   the 12 ~br documents (instruction deleted, contact kept): what an instruction
              detector does on instruction-free poisoning
  paraphrase  results/paraphrase_items.jsonl (make_items_ext paraphrase), if present
  crossed     results/crossed_items.jsonl (make_items_ext crossed), if present
and on the benign chunks (pilot/phase_2/data/benign_docs) for the false-quarantine rates.

Detectors (chunked exactly like ingestion; a document counts as flagged when any chunk is):
  L2ext            regex (no threshold)
  L2b              KB-6 distance at the phase-2 calibrated threshold (inputs/calibration.json)
  L3               the fine-tuned guardrail on each chunk (--with-l3; GPU)
  BN_native        as in phase 2: E5 similarity to the phase-1 Bangla/Banglish payloads, ONLY on
                   chunks the language router calls Bangla (that is how phase 2 ran it)
  BN_native_all    the same detector on EVERY chunk (no router gate)
  E5_all           the senior's design: one E5 detector on every chunk, with English AND
                   Bangla/Banglish attack examples (all phase-1 dev payloads), and ONE threshold
                   that keeps the false-quarantine rate at or below --target in EVERY language
                   (the strictest of the per-language thresholds). No language detection decides
                   whether it runs or which threshold applies.

  python -m pilot.phase_2_extension.detectors_all                 # CPU: everything except L3
  python -m pilot.phase_2_extension.detectors_all --with-l3       # + L3 (GPU, slow)

Writes results/detectors_long.csv (one row per document x detector: flagged, score, n_chunks),
results/detectors_benign.csv (one row per benign chunk), results/detectors_thresholds.json
(E5_all threshold, read by stack_ext.py) and results/detectors_all.md.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from pilot.phase_2_extension.common_ext import ALL_ITEMS, CALIBRATION, GROUP_ORDER, RESULTS, frac, md_table, read_jsonl

LANGS = ("en", "bn", "banglish")
SETS = ("attack", "base_rate", "paraphrase", "crossed")


def lang_of(item: dict) -> str:
    return {"EN": "en", "BL": "banglish"}.get(group_code(item), "bn")


def group_code(item: dict) -> str:
    from pilot.phase_2.common2 import GROUP_CODE, GROUP_ALIASES
    g = GROUP_ALIASES.get(item["group"], item["group"])
    return GROUP_CODE.get(g, g)


def load_docs(all_items: Path, results: Path) -> list[dict]:
    """[{doc_id, set, item fields...}] with carrier_doc unwrapped."""
    from pilot.phase_2 import tags
    docs = []
    for it in read_jsonl(all_items):
        v = it.get("variant", "attack")
        if v in ("attack", "base_rate"):
            docs.append({**it, "set": v})
    for name, s in (("paraphrase_items.jsonl", "paraphrase"), ("crossed_items.jsonl", "crossed")):
        p = results / name
        if p.exists():
            docs += [{**it, "set": s} for it in read_jsonl(p)]
    for d in docs:
        d["carrier_doc"] = tags.unwrap(d["carrier_doc"], "passage")
        d["group_code"] = group_code(d)
        d["lang"] = lang_of(d)
    return docs


def chunks_of(text: str, doc_id: str) -> list[str]:
    from ingestion.chunkers import chunk_document
    return [c for c in (chunk_document(text, "product_info", doc_id) or [text]) if c.strip()]


def strict_threshold(benign_scores: dict[str, list[float]], target: float) -> tuple[float, dict]:
    """One flag-if-above threshold with FQR <= target in every language: the max of the
    per-language thresholds."""
    from pilot.phase_2.calibrate import threshold_above
    per = {lang: threshold_above(s, target) for lang, s in benign_scores.items() if s}
    return max(per.values()), per


def e5_attack_texts(test_payloads: set[str], extra: str | None = None) -> list[str]:
    """E5_all's attack KB: ALL phase-1 dev payloads (English included), never a phase-2 payload."""
    from pilot.phase_2.common2 import PHASE1_ITEMS
    texts = [it["payload"].strip() for it in read_jsonl(PHASE1_ITEMS) if it.get("payload", "").strip()]
    if extra and Path(extra).exists():
        texts += [r["text"].strip() for r in read_jsonl(extra) if r.get("text", "").strip()]
    texts = list(dict.fromkeys(texts))
    leak = set(texts) & test_payloads
    if leak:
        raise ValueError(f"{len(leak)} phase-2 payload(s) in the E5_all attack KB (contamination)")
    return texts


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default=str(ALL_ITEMS))
    ap.add_argument("--benign-dir", default=None, help="default: pilot/phase_2/data/benign_docs")
    ap.add_argument("--calibration", default=str(CALIBRATION))
    ap.add_argument("--target", type=float, default=0.02)
    ap.add_argument("--with-l3", action="store_true")
    ap.add_argument("--no-e5", action="store_true", help="skip the E5 detectors (no model available)")
    ap.add_argument("--e5-extra", help="extra attack examples for E5_all (JSONL with 'text')")
    ap.add_argument("--out-dir", default=str(RESULTS))
    a = ap.parse_args(argv)

    from pilot.phase_1 import layers
    from pilot.phase_2 import bn_route
    from pilot.phase_2.calibrate import load_benign
    from pilot.phase_2.common2 import DATA2_DIR

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cal = json.loads(Path(a.calibration).read_text(encoding="utf-8"))
    l2b_thr = cal["chosen"]["narrative_match_threshold"]
    bn_thr = cal["chosen"]["bn_native"]
    docs = load_docs(Path(a.items), out)
    benign = load_benign(Path(a.benign_dir or DATA2_DIR / "benign_docs"), include_repo_data=False)
    test_payloads = {d.get("payload", "").strip() for d in docs if d["set"] in ("attack", "paraphrase", "crossed")}

    # chunk every document once
    d_chunks, owner = [], []
    for k, d in enumerate(docs):
        for c in chunks_of(d["carrier_doc"], d["item_id"]):
            d_chunks.append(c)
            owner.append(k)
    b_texts = [c["text"] for c in benign]
    b_langs = [c["lang"] for c in benign]

    def score(texts: list[str]) -> dict[str, list]:
        s = {"L2ext": [layers.l2_pattern(t, extended=True)["flagged"] for t in texts],
             "L2b": [layers.l2b_narrative(t)["score"] for t in texts]}
        if a.with_l3:
            s["L3"] = [layers.l3_guardrail(t)["flagged"] for t in texts]
        if not a.no_e5:
            routed = [bn_route.is_bangla(t) for t in texts]
            sims = bn_all.scores(texts)
            s["BN_native"] = [x if r else None for x, r in zip(sims, routed)]
            s["BN_native_all"] = sims
            s["E5_all"] = e5_all.scores(texts)
            s["routed_bangla"] = routed
        return s

    bn_all = e5_all = None
    if not a.no_e5:
        bn_all = bn_route.BNNative(bn_route.bn_attack_texts(exclude_texts=test_payloads), threshold=bn_thr)
        e5_all = bn_route.BNNative(e5_attack_texts(test_payloads, a.e5_extra), threshold=1.0)
    bs, ds = score(b_texts), score(d_chunks)

    thresholds = {"L2b": l2b_thr, "BN_native": bn_thr, "BN_native_all": bn_thr, "target_fqr": a.target}
    if e5_all is not None:
        per_lang = {L: [s for s, lang in zip(bs["E5_all"], b_langs) if lang == L] for L in LANGS}
        thr, per = strict_threshold(per_lang, a.target)
        thresholds["E5_all"] = round(thr, 4)
        thresholds["E5_all_per_language"] = {k: round(v, 4) for k, v in per.items()}
        thresholds["E5_all_kb_size"] = len(e5_all.texts)

    def flag(det, v):
        if v is None:
            return None
        if det == "L2b":
            return v < l2b_thr
        if det in ("BN_native", "BN_native_all", "E5_all"):
            return v > thresholds[det]
        return bool(v)

    dets = [d for d in ("L2ext", "L2b", "L3", "BN_native", "BN_native_all", "E5_all") if d in ds]
    # documents: any chunk flagged; score = most suspicious chunk
    long_rows = []
    for det in dets:
        per_doc = defaultdict(list)
        for o, v in zip(owner, ds[det]):
            per_doc[o].append(v)
        for k, d in enumerate(docs):
            vals = [v for v in per_doc[k] if v is not None]
            flags = [flag(det, v) for v in vals]
            applicable = bool(vals)
            best = (min(vals) if det == "L2b" else max(vals, key=float)) if vals else None
            long_rows.append({"doc_id": d["item_id"], "set": d["set"], "seed_family": d["seed_family"],
                              "group": d["group_code"], "language": d["lang"], "goal_type": d["goal_type"],
                              "technique": d["technique"], "style": d.get("paraphrase_style", ""),
                              "parent": d.get("paraphrase_of") or d.get("crossed_from") or d.get("parent_id") or "",
                              "detector": det, "applicable": int(applicable),
                              "flagged": int(any(flags)) if applicable else "",
                              "miss": int(not any(flags)) if applicable else "",
                              "score": "" if best is None else (round(float(best), 4) if not isinstance(best, bool) else int(best)),
                              "n_chunks": len(per_doc[k])})
    with open(out / "detectors_long.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(long_rows[0]))
        w.writeheader()
        w.writerows(long_rows)
    with open(out / "detectors_benign.csv", "w", newline="", encoding="utf-8") as fh:
        cols = ["lang", "source"] + dets + (["routed_bangla"] if "routed_bangla" in bs else [])
        w = csv.writer(fh)
        w.writerow(cols)
        for i, c in enumerate(benign):
            w.writerow([c["lang"], c["source"]] + [bs[d][i] for d in cols[2:]])
    (out / "detectors_thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ report
    md = ["# Chunk detectors on every phase-2 document", "",
          f"Thresholds: L2b {l2b_thr} and BN_native {bn_thr} from `{Path(a.calibration).name}` (phase 2); "
          + (f"E5_all {thresholds['E5_all']} (strictest per-language threshold at {a.target:.0%}: "
             f"{thresholds['E5_all_per_language']}; attack KB {thresholds['E5_all_kb_size']} phase-1 payloads, "
             f"all languages)." if "E5_all" in thresholds else "E5 detectors skipped."), ""]
    md += ["## False quarantines on benign chunks", ""]
    rows = []
    for det in dets:
        cells = []
        for L in LANGS:
            vals = [flag(det, v) for v, lang in zip(bs[det], b_langs) if lang == L]
            seen = [x for x in vals if x is not None]
            cells.append(f"{frac(sum(seen), len(seen))}" + (f" (of {len(vals)}; {len(vals) - len(seen)} not scanned)"
                                                           if len(seen) < len(vals) else ""))
        rows.append([det] + cells)
    md += md_table(["Detector", "en", "bn", "banglish"], rows)
    if "routed_bangla" in bs:
        miss = [lang for r, lang in zip(bs["routed_bangla"], b_langs) if lang != "en" and not r]
        md += ["", f"Router: {sum(1 for l in miss if l == 'banglish')} Banglish and {sum(1 for l in miss if l == 'bn')} "
               "Bangla benign chunks are routed as English, so router-gated BN_native never sees them."]

    def doc_table(sel_set: str, by: str = "group") -> list[str]:
        sub = [r for r in long_rows if r["set"] == sel_set]
        if not sub:
            return []
        keys = GROUP_ORDER if by == "group" else sorted({r[by] for r in sub})
        rows = []
        for det in dets:
            row = [det]
            for G in keys:
                cell = [r for r in sub if r["detector"] == det and r[by] == G]
                app = [r for r in cell if r["applicable"]]
                row.append(frac(sum(int(r["flagged"]) for r in app), len(cell)) if cell else "-")
            rows.append(row)
        return md_table(["Detector"] + list(keys), rows)

    md += ["", "## Attack documents flagged (all 80 phase-2 items; not-scanned counts as missed)", ""]
    md += doc_table("attack")
    md += ["", "By goal:", ""] + doc_table("attack", by="goal_type")
    md += ["", "## Instruction-deleted documents (~br): would an instruction detector stop poisoning?", ""]
    md += doc_table("base_rate")
    if any(r["set"] == "paraphrase" for r in long_rows):
        md += ["", "## Paraphrase attack against the example-matching detectors", ""]
        md += paraphrase_table(long_rows, dets)
    if any(r["set"] == "crossed" for r in long_rows):
        md += ["", "## Crossed technique (marker as HTML comment, phishing as plain note)", ""]
        md += doc_table("crossed", by="goal_type")
    md += ["", "RQ1 on chunks: `python -m pilot.phase_2_extension.rq1_chunks` pairs these detectors (needs --with-l3 "
           "for the L3 x E5_all pair)."]
    (out / "detectors_all.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def paraphrase_table(long_rows: list[dict], dets: list[str]) -> list[str]:
    """For each paraphrase: parent flagged? paraphrase flagged? score drop."""
    by = {(r["doc_id"], r["detector"]): r for r in long_rows}
    rows = []
    for det in [d for d in dets if d in ("BN_native", "BN_native_all", "E5_all", "L3")]:
        for style in ("policy", "content", "reworded"):
            pars = [r for r in long_rows if r["set"] == "paraphrase" and r["detector"] == det and r["style"] == style]
            if not pars:
                continue
            parent_flag = sum(int(by[(r["parent"], det)]["flagged"] or 0) for r in pars if (r["parent"], det) in by)
            para_flag = sum(int(r["flagged"] or 0) for r in pars)
            evaded = sum(1 for r in pars if (r["parent"], det) in by and by[(r["parent"], det)]["flagged"] == 1
                         and not r["flagged"])
            drops = [float(by[(r["parent"], det)]["score"]) - float(r["score"]) for r in pars
                     if r["score"] != "" and (r["parent"], det) in by and by[(r["parent"], det)]["score"] != ""]
            rows.append([det, style, frac(parent_flag, len(pars)), frac(para_flag, len(pars)),
                         f"{evaded}/{parent_flag}", f"{sum(drops) / len(drops):+.3f}" if drops else "-"])
    return md_table(["Detector", "Style", "Originals flagged", "Paraphrases flagged", "Evaded (of flagged originals)",
                     "Mean score drop"], rows)


if __name__ == "__main__":
    main()
