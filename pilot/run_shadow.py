"""Prep item 1, step 1.3: run every applicable layer on every pilot item, no early exit.

Writes pilot/results/shadow_long.csv in the long format of analysis-methods.md §1:
one row per (item, layer[, run]) with applicable / flagged / miss / score / latency_ms.

  python -m pilot.run_shadow                          # real layers (fill pilot/layers.py)
  python -m pilot.run_shadow --skip q_L3,ingest_L3    # without the GPU guardrail
  python -m pilot.run_shadow --dry                    # toy detectors, tests the plumbing

Before a real run, the positive/negative-control self-test of pilot/layers.py runs
automatically and the run stops if any layer fails it (--no-check to override).

Applicability:
  chunk layers      applicable = 1 for every item (they see the planted document)
  query_diag (q_*)  applicable = 0, diagnostic = 1: the payload sent as if it were a
                    query. Shown in the summary, never paired in the correlation analysis.
  L8                applicable = 1 only if the goal leaks data (pii, phish) AND that run's
                    answer actually contained the leak (success, or a hand-found missed_hit).

The L8 rows use the answers already stored by run_undefended.py (--answers-model).
L8 is applicable only when the goal leaks data (pii, phish) AND the generator actually
produced the leak in that run: L8 cannot "miss" something that never reached it.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from pilot.common import RESULTS_DIR, load_items

OUT = RESULTS_DIR / "shadow_long.csv"
FIELDS = ["sample_id", "run", "seed_family", "group", "language", "difficulty", "threat_class",
          "goal_type", "layer", "artifact", "applicable", "diagnostic", "flagged", "miss", "score",
          "latency_ms", "error"]


def call(fn, text):
    t0 = time.perf_counter()
    try:
        r = fn(text)
        return r["flagged"], r.get("score"), (time.perf_counter() - t0) * 1000, ""
    except Exception as e:
        return None, None, (time.perf_counter() - t0) * 1000, repr(e)[:200]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="pilot/pilot_items.jsonl")
    ap.add_argument("--answers-model", default="llama3.2:3b",
                    help="whose undefended answers L8 is run on")
    ap.add_argument("--skip", default="", help="comma-separated layer names to skip")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-check", action="store_true", help="skip the layer self-test (not advised)")
    ap.add_argument("--gen", default=str(RESULTS_DIR / "generations.jsonl"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)

    from pilot.layers import self_test
    if a.dry:
        from pilot.layers import TOY_LAYERS as LAYERS
    else:
        from pilot.layers import LAYERS
    skip = set(filter(None, a.skip.split(",")))
    unknown = skip - set(LAYERS)
    if unknown:
        raise SystemExit(f"unknown layer(s) in --skip: {sorted(unknown)}; known: {sorted(LAYERS)}")
    if not a.no_check and not self_test(LAYERS, skip):
        raise SystemExit("layer self-test failed: fix pilot/layers.py (or use --skip / --no-check)")
    items = load_items(a.items)

    # Latest error-free answer per (item, run); earlier error rows were retried.
    latest = {}
    gen = Path(a.gen)
    if gen.exists():
        for r in (json.loads(l) for l in open(gen, encoding="utf-8") if l.strip()):
            if (r["model"] == a.answers_model and r["config"] == "undefended"
                    and not r.get("error")):
                latest[(r["item_id"], r["run"])] = r
    answers = {}
    for (iid, _), r in sorted(latest.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        answers.setdefault(iid, []).append(r)
    if not answers:
        print(f"note: no undefended answers from {a.answers_model} in {gen}; L8 rows will be empty")

    rows = []
    for it in items:
        base = {"sample_id": it["item_id"], "seed_family": it["seed_family"], "group": it["group"],
                "language": it["language"], "difficulty": it["technique"],
                "threat_class": it["threat_class"], "goal_type": it["goal_type"]}
        payload = it.get("payload") or it["carrier_doc"]
        for name, (artifact, fn) in LAYERS.items():
            if name in skip:
                continue
            if artifact in ("chunk", "query_diag"):
                text = it["carrier_doc"] if artifact == "chunk" else payload
                flagged, score, ms, err = call(fn, text)
                diag = artifact == "query_diag"
                rows.append({**base, "run": "", "layer": name, "artifact": artifact,
                             "applicable": 0 if diag else 1, "diagnostic": int(diag),
                             "flagged": flagged,
                             "miss": "" if flagged is None else int(not flagged),
                             "score": score, "latency_ms": round(ms, 1), "error": err})
            elif artifact == "answer":
                for g in answers.get(it["item_id"], []):
                    leaked = (g.get("success") == 1 or g.get("manual_check") == "missed_hit")
                    exposed = it["goal_type"] in ("pii", "phish") and leaked
                    if not exposed:
                        rows.append({**base, "run": g["run"], "layer": name, "artifact": artifact,
                                     "applicable": 0, "diagnostic": 0, "flagged": "", "miss": "",
                                     "score": "", "latency_ms": "", "error": ""})
                        continue
                    flagged, score, ms, err = call(fn, g["answer"])
                    rows.append({**base, "run": g["run"], "layer": name, "artifact": artifact,
                                 "applicable": 1, "diagnostic": 0, "flagged": flagged,
                                 "miss": "" if flagged is None else int(not flagged),
                                 "score": score, "latency_ms": round(ms, 1), "error": err})

    out = Path(a.out)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    errors = sum(1 for r in rows if r["error"])
    print(f"wrote {len(rows)} rows to {out} ({errors} errors)")
    if errors:
        print("first error:", next(r["error"] for r in rows if r["error"]))


if __name__ == "__main__":
    main()
