"""Check pilot_items2.jsonl before freezing it (plan steps B1 and B4).

  python -m pilot.phase_2.validate_items2
  python -m pilot.phase_2.validate_items2 --items pilot/phase_2/pilot_items2.jsonl --data data/

Runs every phase-1 check (pilot/phase_1/validate_items.py: canary in carrier, no core
elsewhere in data/, pii phone, family alignment, ...) and then the phase-2 rules:

  hard  * split is "test" on every item (the 56 phase-1 items are the dev set)
        * no seed_family, canary core or payload shared with a phase-1 (dev) item
        * author is one of: human, ai-draft+human-edit, translated-ai+reviewed, translated-human
  warn  * review_status is not "approved"
        * fewer than 12 items in a group (DATASET.md floor)
        * phish item without entity_sentence (C2 then uses a draft)
        * item without user_request (C1 then uses the payload as a draft)
        * fewer human-written than AI-drafted Banglish items
Exit code 1 on any hard failure.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from pilot.phase_2.common2 import AUTHORS, PHASE1_ITEMS, load_items2, read_jsonl


def phase2_checks(items: list[dict], dev: list[dict]) -> tuple[list[str], list[str]]:
    hard, soft = [], []
    dev_fams = {d["seed_family"] for d in dev}
    dev_cores = {str(d["canary_core"]) for d in dev}
    dev_payloads = {d.get("payload", "").strip() for d in dev if d.get("payload")}
    for it in items:
        tag = it["item_id"]
        if it.get("split") != "test":
            hard.append(f"{tag}: split must be 'test' (phase-1 items are the dev set), got {it.get('split')!r}")
        if it["seed_family"] in dev_fams:
            hard.append(f"{tag}: seed_family {it['seed_family']} is a phase-1 (dev) family; use a new one")
        if it["canary_core"] in dev_cores:
            hard.append(f"{tag}: canary core {it['canary_core']} is already used by a phase-1 item")
        if it.get("payload", "").strip() in dev_payloads:
            hard.append(f"{tag}: payload is copied from a phase-1 item")
        if it.get("author") not in AUTHORS:
            hard.append(f"{tag}: author must be one of {sorted(AUTHORS)}, got {it.get('author')!r}")
        if it.get("review_status") != "approved":
            soft.append(f"{tag}: review_status is {it.get('review_status')!r}, not 'approved'")
        if it["goal_type"] == "phish" and not it.get("entity_sentence"):
            soft.append(f"{tag}: phish item without entity_sentence (base-rate control will use a draft)")
        if not it.get("user_request"):
            soft.append(f"{tag}: no user_request (positive control will use the payload as a draft)")
    groups = Counter(it["group"] for it in items)
    for g, n in groups.items():
        if n < 12:
            soft.append(f"group {g}: {n} items, below the 12-item floor in DATASET.md")
    bl = Counter(it.get("author") for it in items if it["group"] == "banglish")
    if bl and bl.get("human", 0) < sum(v for k, v in bl.items() if k != "human"):
        soft.append(f"banglish authors {dict(bl)}: the senior asked for human-written Banglish")
    return hard, soft


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="pilot/phase_2/pilot_items2.jsonl")
    ap.add_argument("--dev", default=str(PHASE1_ITEMS))
    ap.add_argument("--data", default="data/")
    ap.add_argument("--no-data-check", action="store_true")
    ap.add_argument("--skip-phase1-checks", action="store_true")
    a = ap.parse_args(argv)

    code = 0
    if not a.skip_phase1_checks:
        from pilot.phase_1 import validate_items
        print("== phase-1 checks")
        args = ["--items", a.items, "--data", a.data] + (["--no-data-check"] if a.no_data_check else [])
        try:
            validate_items.main(args)
        except SystemExit as e:
            code = int(e.code or 0)
    try:
        items = [i for i in load_items2(a.items) if i["variant"] == "attack"]
    except Exception as e:
        print(f"FAIL load_items2: {e}")
        sys.exit(1)
    dev = read_jsonl(a.dev) if a.dev else []
    hard, soft = phase2_checks(items, dev)
    print("\n== phase-2 checks")
    print("authors :", dict(Counter(i.get("author") for i in items)))
    print("groups  :", dict(Counter(i["group"] for i in items)))
    for m in soft:
        print("WARN ", m)
    for m in hard:
        print("FAIL ", m)
    print(f"\n{len(hard)} phase-2 hard failure(s), {len(soft)} warning(s); phase-1 checks exit code {code}")
    sys.exit(1 if hard or code else 0)


if __name__ == "__main__":
    main()
