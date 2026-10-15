"""Give items new canary cores when the validator says a core also appears in data/.

  python -m pilot.phase_2.recore                    # only the items whose core collides
  python -m pilot.phase_2.recore --ids EN-201 TR-201
  python -m pilot.phase_2.recore --dry-run          # show what would change

The new core has the same number of digits, is not used by any phase-1 or phase-2 item, and
appears nowhere in the knowledge-base part of data/. It replaces the old core everywhere in
the item (payload, carrier_doc, question, user_request, entity_sentence), in ASCII and in
Bangla digits. The original file is kept next to it as <name>.bak.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

from pilot.phase_1.validate_items import grep_files
from pilot.phase_2.common2 import PHASE1_ITEMS, read_jsonl

TO_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
TEXT_FIELDS = ("payload", "carrier_doc", "question", "user_request", "entity_sentence")


def new_core(old: str, taken: set[str], data: str, rng: random.Random) -> str:
    for _ in range(10000):
        c = str(rng.randint(10 ** (len(old) - 1), 10 ** len(old) - 1))
        if c not in taken and not any(c in t or t in c for t in taken) and not grep_files(c, data):
            return c
    raise SystemExit(f"could not find a free {len(old)}-digit core")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="pilot/phase_2/pilot_items2.jsonl")
    ap.add_argument("--data", default="data/")
    ap.add_argument("--ids", nargs="*", help="items to re-core (default: every item whose core collides)")
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    lines = Path(a.items).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) if line.strip() else None for line in lines]
    taken = {str(r["canary_core"]) for r in rows if r} | {str(r["canary_core"]) for r in read_jsonl(PHASE1_ITEMS)}
    rng = random.Random(a.seed)
    changed = []
    for i, r in enumerate(rows):
        if r is None:
            continue
        old = str(r["canary_core"])
        if (r["item_id"] not in a.ids) if a.ids else not grep_files(old, a.data):
            continue
        new = new_core(old, taken, a.data, rng)
        taken.add(new)
        for f in TEXT_FIELDS:
            if isinstance(r.get(f), str):
                r[f] = r[f].replace(old, new).replace(old.translate(TO_BN), new.translate(TO_BN))
        r["canary_core"] = new
        compact = '":"' in lines[i]                    # keep the file's own JSON style
        lines[i] = json.dumps(r, ensure_ascii=False, separators=(",", ":") if compact else None)
        changed.append((r["item_id"], old, new))
        print(f"{r['item_id']}: {old} -> {new}")
    if not changed:
        print("no item needed a new core")
        return
    if a.dry_run:
        print(f"\n--dry-run: {len(changed)} item(s) would change; nothing written")
        return
    shutil.copy(a.items, a.items + ".bak")
    Path(a.items).write_text("\n".join(lines) + "\n", encoding="utf-8")   # untouched lines stay byte-identical
    print(f"\nwrote {len(changed)} new core(s) to {a.items} (original kept as {Path(a.items).name}.bak); "
          f"run validate_items2 again")


if __name__ == "__main__":
    main()
