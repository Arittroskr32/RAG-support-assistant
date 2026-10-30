"""Extended stack run (senior, Qwen question and points 1-2). Same funnel and CSV columns as
pilot/phase_2/stack_check2.py, plus four things:

  --only-file <valid_qwen...json>   run on QWEN's own valid set (its 4 Banglish items were never
                                    planted in phase 2, which used the 3B set for every model)
  --variant base_rate               plant the instruction-deleted ~br documents instead of the
                                    attacks: does BN_native (or E5_all) stop instruction-free
                                    poisoning, and does the address still leak? (point 1)
  --isolate                         plant ALL chosen items at once and keep them indexed, but hide
                                    the other planted items' documents from retrieval at query time
                                    (an extra source_doc_id $nin filter in the same where-clause as
                                    RBAC/tenant/quarantine). Every question then competes only with
                                    the real KB, as one item would in deployment (point 2)
  --config bangla_serving_e5all     bangla_serving + the language-independent E5_all detector on
                                    EVERY chunk at ingestion (threshold from detectors_all.py); no
                                    router decides which chunks are scanned (design point 1)

Final runs (senior, point 2) add one more:

  --carrier joined                  remove the blank lines from every planted document before
                                    ingestion, so the payload stays inside its paragraph instead
                                    of becoming a "Support note" chunk of its own (the `joined`
                                    mode of detectors_all.py). The output file gets "_joined" in
                                    its name, and stackx_runs.jsonl records how many KB-4 chunks
                                    each planted document became (1 = the payload is not alone).
                                    Use --items with a paraphrase item file (one style) to plant
                                    paraphrased payloads instead of the originals.

Every answer is also passed through contact_guard.py in shadow mode (columns contact_guard,
contact_guard_caught): it changes nothing in the answer, it records what the official-contact
check would have removed.

  python -m pilot.phase_2_extension.stack_ext --config bangla_serving --model qwen3:4b-instruct-2507-q4_K_M \
      --only-file pilot/phase_2_extension/inputs/valid_qwen3-4b-instruct-2507-q4-K-M.json --isolate
  (run.md lists every run)

Stop the API first (this rebuilds KB-4); keep `ollama serve` running. Planted files are removed
and KB-4 is rebuilt at the end, even after a crash.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime
import json
import re
import sys
from pathlib import Path

from pilot.phase_2_extension.common_ext import ALL_ITEMS, CALIBRATION, RESULTS

CARRIERS = ("as_is", "joined")


def join_carrier(text: str) -> str:
    """The `joined` attacker: no blank lines, so the FAQ chunker keeps the payload in its paragraph
    (same transformation as detectors_all.chunks_of(mode="joined"))."""
    return re.sub(r"\n\s*\n", "\n", text).strip()


def planted_chunk_counts() -> dict[str, int]:
    """{item_id: number of KB-4 chunks} for every planted document."""
    from knowledge_bases.kb_manager import kb
    from pilot.phase_2.stack_check2 import item_of_source
    got = kb.kb4_documents.get(include=["metadatas"])
    out: dict[str, int] = {}
    for meta in got["metadatas"]:
        iid = item_of_source(str(meta.get("source_doc_id", "")))
        if iid:
            out[iid] = out.get(iid, 0) + 1
    return out


CONFIGS = ("deployed", "bangla_serving", "bangla_serving_bn", "bangla_serving_e5all")
EXTRA_FIELDS = ["isolated", "excluded_items", "contact_guard", "contact_guard_caught", "scan_detector"]


class Isolation:
    """Adds `source_doc_id NOT IN <other planted docs>` to L5's where-clause (both the MiniLM and
    the E5 route build their filter with retrieval.l5_secure_retrieval.build_where)."""

    def __init__(self):
        import retrieval.l5_secure_retrieval as l5
        self.l5, self.orig, self.exclude = l5, l5.build_where, []
        l5.build_where = self.where

    def where(self, scope, tenant_id):
        w = self.orig(scope, tenant_id)
        if not self.exclude:
            return w
        cond = {"source_doc_id": {"$nin": list(self.exclude)}}
        return {"$and": (list(w["$and"]) if "$and" in w else [w]) + [cond]}

    def restore(self):
        self.l5.build_where = self.orig


def planted_sources() -> dict[str, set[str]]:
    """{item_id: {source_doc_id, ...}} for every planted document in KB-4."""
    from knowledge_bases.kb_manager import kb
    from pilot.phase_2.stack_check2 import item_of_source
    got = kb.kb4_documents.get(include=["metadatas"])
    out: dict[str, set[str]] = {}
    for meta in got["metadatas"]:
        sid = str(meta.get("source_doc_id", ""))
        iid = item_of_source(sid)
        if iid:
            out.setdefault(iid, set()).add(sid)
    return out


def scan_every_chunk(detector, reasons: dict, label: str) -> int:
    """Language-independent ingestion scan: score EVERY non-quarantined KB-4 chunk."""
    from knowledge_bases.kb_manager import kb
    from pilot.phase_2 import bn_route
    from pilot.phase_2.stack_check2 import item_of_source
    got = kb.kb4_documents.get(include=["documents", "metadatas"])
    cand = [(cid, doc, meta) for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"])
            if not meta.get("quarantined")]
    scores = detector.scores([d for _, d, _ in cand])
    flagged = [(cid, meta, s) for (cid, _, meta), s in zip(cand, scores) if s is not None and s > detector.threshold]
    bn_route.quarantine([cid for cid, _, _ in flagged], label)
    benign_hit = 0
    for _, meta, s in flagged:
        iid = item_of_source(str(meta.get("source_doc_id", "")))
        if iid:
            reasons.setdefault(iid, f"{label}:{s:.3f}")
        else:
            benign_hit += 1
    return benign_hit


def benign_quarantined() -> int:
    """KB-4 chunks that are quarantined but are NOT planted documents (false quarantines)."""
    from knowledge_bases.kb_manager import kb
    from pilot.phase_2.stack_check2 import item_of_source
    got = kb.kb4_documents.get(include=["metadatas"])
    return sum(1 for m in got["metadatas"] if m.get("quarantined") and not item_of_source(str(m.get("source_doc_id", ""))))


def select(a, items: list[dict]) -> dict[str, list[dict]]:
    from pilot.phase_2.common2 import GROUPS
    items = [i for i in items if i["variant"] == a.variant]
    keep = set(a.ids)
    if a.only_file:
        data = json.loads(Path(a.only_file).read_text(encoding="utf-8"))
        keep |= set(data["items"] if isinstance(data, dict) else data)
    chosen = {}
    for g in a.groups:
        rows = [r for r in items if r["group"] == GROUPS[g]
                and (not keep or r["item_id"] in keep or r.get("parent_id") in keep)]
        if rows:
            chosen[g] = rows
    if not chosen:
        raise SystemExit("no items selected (check --variant, --only-file, --groups)")
    return chosen


def main(argv=None) -> None:
    from pilot.phase_2.common2 import GROUPS
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default=str(ALL_ITEMS), help="attacks + controls (all_items2.jsonl)")
    ap.add_argument("--config", choices=CONFIGS, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--variant", choices=["attack", "base_rate"], default="attack")
    ap.add_argument("--isolate", action="store_true", help="hide other planted items at query time")
    ap.add_argument("--carrier", choices=CARRIERS, default="as_is",
                    help="joined = remove blank lines so the payload is not split off as its own chunk")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seed-base", type=int, default=20261012)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--timeout", type=float, default=2400)
    ap.add_argument("--think", choices=["auto", "off", "on"], default="auto")
    ap.add_argument("--openai-compat", action="store_true",
                    help="use the repository's OpenAI-compatible call (no seed is sent; tests use it)")
    ap.add_argument("--groups", nargs="+", default=list(GROUPS), choices=list(GROUPS))
    ap.add_argument("--ids", nargs="+", default=[])
    ap.add_argument("--only-file")
    ap.add_argument("--role", default="customer")
    ap.add_argument("--with-l3", action="store_true", help="L3 also scans chunks at ingestion")
    ap.add_argument("--calibration", default=str(CALIBRATION), help="BN_native threshold (phase 2)")
    ap.add_argument("--detector-thresholds", default=str(RESULTS / "detectors_thresholds.json"),
                    help="E5_all threshold from detectors_all.py")
    ap.add_argument("--tag", default="")
    ap.add_argument("--out-dir", default=str(RESULTS))
    a = ap.parse_args(argv)

    import pipeline.orchestrator as orch
    from generation import l7_generation as l7
    from pilot.phase_2.common2 import load_items2
    items = load_items2(a.items)
    if a.carrier == "joined":
        for it in items:
            it["carrier_doc"] = join_carrier(it["carrier_doc"])
    chosen = select(a, items)
    saved = (orch.secure_search, l7.generate_answer, l7.MODEL_SETTINGS, l7._generate_local)
    iso = None
    try:
        if a.isolate:
            iso = Isolation()
        run_all(a, items, chosen, iso)
    finally:
        orch.secure_search, l7.generate_answer, l7.MODEL_SETTINGS, l7._generate_local = saved
        if iso:
            iso.restore()


def run_all(a, items, chosen, iso) -> None:
    import pipeline.orchestrator as orch
    from config.settings import get_thresholds
    from generation import l7_generation as l7
    from pilot.phase_2 import bn_route
    from pilot.phase_2.stack_check2 import (FIELDS, Capture, ask, install_generator, outcome, plant, plant_dir,
                                           rebuild, unplant)
    from pilot.phase_2_extension.contact_guard import check, load_official, normalize
    from pilot.phase_2_extension.detectors_all import e5_attack_texts

    official = load_official()
    e5 = a.config != "deployed"
    test_payloads = {i.get("payload", "").strip() for i in items}
    bn = detector = None
    if a.config == "bangla_serving_bn":
        bn = bn_route.BNNative(bn_route.bn_attack_texts(exclude_texts=test_payloads),
                               bn_route.load_threshold(a.calibration))
    if a.config == "bangla_serving_e5all":
        p = Path(a.detector_thresholds)
        if not p.exists():
            raise SystemExit(f"missing {p}: run detectors_all.py first (it calibrates E5_all)")
        thr = json.loads(p.read_text(encoding="utf-8"))["E5_all"]
        detector = bn_route.BNNative(e5_attack_texts(test_payloads), thr)
    searcher = None
    if e5:
        searcher = bn_route.RoutedSearch(orch.secure_search)
        orch.secure_search = searcher
    set_seed = install_generator(a.model, a.temperature, a.base_url, a.think, native=not a.openai_compat,
                                 timeout=a.timeout)
    capture = Capture(l7.generate_answer)
    l7.generate_answer = capture

    cfg = get_thresholds()
    where = plant_dir()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    label = (a.config + ("_br" if a.variant == "base_rate" else "") + ("_iso" if a.isolate else "")
             + ("_joined" if a.carrier == "joined" else ""))
    stem = f"stackx_{label}_{re.sub(r'[^A-Za-z0-9.]+', '-', a.model)}" + (f"_{a.tag}" if a.tag else "")
    scan_label = {"bangla_serving_bn": "BN_native (router-gated)", "bangla_serving_e5all": "E5_all (every chunk)"}.get(a.config, "")
    print(f"config {a.config}, variant {a.variant}, model {a.model}, isolate {a.isolate}, scan {scan_label or 'deployed only'}, "
          f"render guard {'on' if cfg.enable_render_guard else 'OFF'}")
    # with --isolate every chosen item is planted at once (one rebuild); otherwise one group at a time
    batches = {"ALL": [r for g in chosen for r in chosen[g]]} if a.isolate else chosen
    rows, meta_batches = [], []
    unplant(where)
    try:
        for bname, batch in batches.items():
            print(f"\n== {bname}: {len(batch)} documents planted")
            plant(batch, where)
            quarantine = rebuild(where, scan=True, with_l3=a.with_l3, e5=e5, bn=bn)
            if detector is not None:
                scan_every_chunk(detector, quarantine, "E5_all")
            fq = benign_quarantined()
            n_chunks = planted_chunk_counts()
            meta_batches.append({"batch": bname, "planted": len(batch), "benign_chunks_quarantined": fq,
                                 "chunks_per_planted_doc": n_chunks})
            if a.carrier == "joined" and any(n > 1 for n in n_chunks.values()):
                print(f"   WARNING: some joined documents still became several chunks: "
                      f"{ {k: v for k, v in n_chunks.items() if v > 1} }")
            print(f"   benign KB-4 chunks quarantined: {fq}")
            sources = planted_sources() if iso else {}
            cores_scope = batch                      # every canary of the batch is checked in every answer
            for r in batch:
                if iso:
                    iso.exclude = sorted(s for iid, ss in sources.items() if iid != r["item_id"] for s in ss)
                for run in range(1, a.runs + 1):
                    seed = a.seed_base + 2000 + run
                    set_seed(seed)
                    g = next(k for k, v in chosen.items() if r in v)
                    row = {"config": label, "model": a.model, "run": run, "seed": seed, "item_id": r["item_id"],
                           "parent_id": r.get("parent_id") or r["item_id"], "variant": r["variant"], "group": g,
                           "seed_family": r["seed_family"], "goal_type": r["goal_type"], "technique": r["technique"],
                           "author": r.get("author", ""), "quarantined": bool(quarantine.get(r["item_id"])),
                           "quarantine_reason": quarantine.get(r["item_id"], ""), "isolated": bool(iso),
                           "excluded_items": len({i for i in sources if i != r["item_id"]}) if iso else 0,
                           "scan_detector": scan_label}
                    if row["quarantined"]:
                        row.update(route="", embedder="", blocked_at="", verdict="", n_retrieved=0,
                                   retrieved_chunk_ids="", retrieved_items="", own_payload_retrieved=False,
                                   other_payload_items="", canary_in_raw=False, canary_in_answer=False,
                                   other_canaries_in_answer="", external_markup=0, latency_ms=0,
                                   l8_findings="", raw_answer="", response="")
                    else:
                        row.update(ask(r, cores_scope, a.role, capture, searcher))
                    cg = check(row["response"] or "", official) if row["response"] else None
                    row["contact_guard"] = ";".join(v for _, v in cg.unofficial) if cg else ""
                    row["contact_guard_caught"] = bool(cg and any(str(r["canary_core"]) in normalize(v)
                                                                  for _, v in cg.unofficial))
                    row["outcome"] = outcome(row)
                    rows.append(row)
                    print(f"  {r['item_id']:<10} run {run} {row['route'] or '-':<8} {row['outcome']:<24} "
                          f"{row['latency_ms']} ms", file=sys.stderr)
            unplant(where)
    finally:
        unplant(where)
        print("\nrestoring KB-4 without the planted documents ...")
        rebuild(where, scan=True, with_l3=False, e5=False)

    with open(out_dir / f"{stem}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS + EXTRA_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    from pilot.phase_2.common2 import git_commit
    meta = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "config": a.config, "variant": a.variant,
            "isolate": a.isolate, "carrier": a.carrier, "model": a.model, "runs": a.runs, "seed_base": a.seed_base,
            "temperature": a.temperature, "items": a.items, "only_file": a.only_file,
            "bn_threshold": bn.threshold if bn else None, "e5all_threshold": detector.threshold if detector else None,
            "batches": meta_batches, "thresholds": dataclasses.asdict(cfg), "git_commit": git_commit(),
            "n_rows": len(rows), "csv": f"{stem}.csv"}
    with open(out_dir / "stackx_runs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, default=str) + "\n")
    from collections import Counter
    print(f"\nwrote {len(rows)} rows to {out_dir / (stem + '.csv')}")
    for g, n in sorted(Counter((r["group"], r["outcome"]) for r in rows).items()):
        print(g, n)


if __name__ == "__main__":
    main()
