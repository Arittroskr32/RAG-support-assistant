"""Compute the numbers still marked [n], [e] and [k] in generation.md.

  python -m pilot.pilot_numbers
  python -m pilot.pilot_numbers --gen pilot/results-pilot-v1/generations.jsonl

[n]  labels that change when all answers are re-scored with the revised matcher
     (commas/slashes/dots no longer join digits; image goals also count inline links,
     autolinks and raw HTML). Hand-check labels (refusal_quote / missed_hit) are applied
     on top, exactly as in report_tables.py.
[e]  fenced llama3.2:3b answers that echo the fence (contain "document-" + 16 hex digits)
[k]  of those, how many count as successes
Nothing is written; the numbers are printed for you to copy into generation.md.
"""
from __future__ import annotations

import argparse
import json
import re

from pilot.common import RESULTS_DIR, attack_success, load_items, require_real_matcher

ECHO = re.compile(r"document-[0-9a-f]{16}", re.I)


def final(success, manual_check) -> int:
    if manual_check == "refusal_quote":
        return 0
    if manual_check == "missed_hit":
        return 1
    return int(success or 0)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default=str(RESULTS_DIR / "generations.jsonl"))
    ap.add_argument("--items", default="pilot/pilot_items.jsonl")
    ap.add_argument("--echo-model", default="llama3.2:3b")
    a = ap.parse_args(argv)
    require_real_matcher("pilot_numbers")

    items = {i["item_id"]: i for i in load_items(a.items)}
    rows = [json.loads(l) for l in open(a.gen, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if not r.get("error")]

    changed = []
    for r in rows:
        mc = r.get("manual_check") or ""
        old = final(r["success"], mc)
        new = final(attack_success(items[r["item_id"]], r.get("answer") or "")["success"], mc)
        if old != new:
            changed.append((r["item_id"], r["model"], r["config"], r["run"], old, new))
    print(f"[n] labels changed by the revised matcher: {len(changed)} of {len(rows)}")
    for c in changed[:20]:
        print(f"    {c[0]:7} {c[1]:12} {c[2]:10} run {c[3]}: {c[4]} -> {c[5]}")
    if changed:
        print("    -> look at these answers; if the new label is right, the tables need "
              "re-scoring (ask before changing the reported numbers)")

    fenced = [r for r in rows if r["config"] == "fenced"]
    for model in sorted({r["model"] for r in fenced}):
        echo = [r for r in fenced if r["model"] == model and ECHO.search(r.get("answer") or "")]
        k = sum(final(r["success"], r.get("manual_check") or "") for r in echo)
        tag = "  <- [e] and [k]" if model == a.echo_model else ""
        print(f"{model:12} fenced answers echoing the fence: {len(echo)}, successes among them: {k}{tag}")


if __name__ == "__main__":
    main()
