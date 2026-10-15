"""Check a filled pilot_items.jsonl before you freeze it.

  python -m pilot.phase_1.validate_items                      # checks pilot/phase_1/pilot_items.jsonl
  python -m pilot.phase_1.validate_items --items path --data data/

Reports (not just pass/fail):
  * structural errors from load_items (missing fields, duplicate id/core);
  * rows still containing TODO;
  * the canary core NOT present in its own carrier_doc (so it cannot be leaked);
  * the core appearing elsewhere in data/ (security_datasets/ and planted zz_* files are
    skipped because they never reach the model), which would cause false hits;
  * payload text not found inside carrier_doc (payload must be embedded);
  * EN/TR/BL family alignment (same goal across the three languages);
  * goal / technique / split / review_status counts, and author breakdown;
  * for pii rows, a Bangladeshi phone (ASCII or Bangla digits) whose last 8 digits equal the core;
  * for marker/phish rows, the core appearing OUTSIDE the payload in carrier_doc (a model
    could then repeat it innocently, giving a false success).
Exit code is non-zero if any hard check fails.

The collision grep needs the repository's data folder. Working outside the repository,
pass it explicitly:  --data /path/to/repo/data
If the folder does not exist the check is reported as NOT RUN (a hard failure unless
--no-data-check is given), never silently skipped.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pilot.phase_1.common import load_items

PHONE = re.compile(r"01[3-9]\d{8}")
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


TO_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


# Only folders the knowledge base reads can cause a false hit: security_datasets/ (KB-2/KB-6
# training data, ingestion.loaders.EXCLUDED_DIRS) never reaches the model's context, and zz_*
# files are documents planted by the stack checks themselves.
SKIP_DIRS = {"security_datasets"}
SKIP_PREFIX = "zz_"


def grep_files(core: str, data_dir: str) -> list[str] | None:
    """Text files under data_dir (KB-4 content only) containing the core in ASCII or Bangla
    digits. Pure Python, so it also works on Windows."""
    root = Path(data_dir)
    if not root.exists():
        return None
    hits = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or SKIP_DIRS & set(rel.parts[:-1]) or p.name.startswith(SKIP_PREFIX):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:                      # binary, like grep -I
            continue
        if core in raw.decode("utf-8", errors="ignore").translate(BN_DIGITS):
            hits.append(str(p))
    return hits


def grep_data(core: str, data_dir: str) -> int:
    files = grep_files(core, data_dir)
    return -1 if files is None else len(files)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="pilot/phase_1/pilot_items.jsonl")
    ap.add_argument("--data", default="data/")
    ap.add_argument("--no-data-check", action="store_true",
                    help="skip the grep over data/ (only if you really have no data folder)")
    a = ap.parse_args(argv)

    hard, soft = [], []
    try:
        items = load_items(a.items)
    except Exception as e:
        print(f"FAIL load_items: {e}")
        sys.exit(1)
    print(f"loaded {len(items)} items from {a.items}\n")

    data_ok = Path(a.data).is_dir()
    if not data_ok and not a.no_data_check:
        hard.append(f"collision check NOT RUN: data folder '{a.data}' not found "
                    f"(pass --data /path/to/repo/data)")
    for it in items:
        tag = it["item_id"]
        for f in ("payload", "carrier_doc", "question", "author"):
            if "TODO" in str(it.get(f, "")):
                soft.append(f"{tag}: {f} still has TODO")
        core = str(it["canary_core"])
        if core not in it["carrier_doc"].translate(BN_DIGITS) and it["goal_type"] != "image":
            hard.append(f"{tag}: canary core {core} not in carrier_doc (cannot be leaked)")
        pay = str(it.get("payload", ""))
        if "TODO" not in pay and pay[:20] not in it["carrier_doc"]:
            soft.append(f"{tag}: payload text not found verbatim in carrier_doc")
        if it["goal_type"] in ("marker", "phish") and pay and "TODO" not in pay:
            outside = it["carrier_doc"].replace(pay, "")
            if core in outside.translate(BN_DIGITS):
                hard.append(f"{tag}: core {core} also appears outside the payload in carrier_doc "
                            f"(the model could repeat it innocently)")
        if it["goal_type"] == "pii":
            phones = PHONE.findall(it["carrier_doc"].translate(BN_DIGITS))
            if not any(p[-8:] == core for p in phones):
                hard.append(f"{tag}: pii core {core} is not the last 8 digits of any phone in carrier_doc")
        if data_ok and not a.no_data_check:
            files = grep_files(core, a.data) or []
            if files:
                hard.append(f"{tag}: core {core} also appears in {len(files)} file(s) under {a.data} "
                            f"(false-hit risk): {', '.join(files[:3])}")

    # a core must not appear in ANOTHER item's carrier document either
    for it in items:
        core = str(it["canary_core"])
        others = [o["item_id"] for o in items
                  if o is not it and core in o["carrier_doc"].translate(BN_DIGITS)]
        if others:
            # Harmless in the pilot (each item's context holds only its own document),
            # but a false-hit risk once all documents share one knowledge base.
            soft.append(f"{it['item_id']}: core {core} also appears in carrier_doc of {others[:4]}")

    # EN/TR/BL family alignment
    fam_goal = defaultdict(dict)
    for it in items:
        if it["group"] in ("english", "translated", "banglish") and not it["item_id"].startswith("EN-C"):
            fam_goal[it["seed_family"]][it["group"]] = it["goal_type"]
    for fam, d in sorted(fam_goal.items()):
        if len(set(d.values())) > 1:
            hard.append(f"family {fam}: goal differs across languages {d}")
        present = {"english", "translated", "banglish"} - set(d)
        if present and len(d) >= 1:
            soft.append(f"family {fam}: missing {sorted(present)} (EN/TR/BL should be aligned)")

    # counts
    print("groups   :", dict(Counter(i["group"] for i in items)))
    print("goals    :", dict(Counter(i["goal_type"] for i in items)))
    print("technique:", dict(Counter(i["technique"] for i in items)))
    print("split    :", dict(Counter(i.get("split", "(missing)") for i in items)))
    print("review   :", dict(Counter(i.get("review_status", "(missing)") for i in items)))
    print("author   :", dict(Counter((str(i.get("author") or "").split() or ["(missing)"])[0]
                                     for i in items)))
    no_author = [i["item_id"] for i in items if not str(i.get("author") or "").strip()]
    if no_author:
        soft.append(f"{len(no_author)} items without author: {no_author[:6]}")
    test_unapproved = [i["item_id"] for i in items
                       if i.get("split") == "test" and i.get("review_status") != "approved"]
    if test_unapproved:
        soft.append(f"{len(test_unapproved)} test items not yet 'approved': {test_unapproved[:6]}...")

    print()
    for m in soft:
        print("WARN ", m)
    for m in hard:
        print("FAIL ", m)
    print(f"\n{len(hard)} hard failure(s), {len(soft)} warning(s)")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
