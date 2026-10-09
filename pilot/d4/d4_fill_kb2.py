"""Prep item 4 / design check D4, step 0: fill kb2_known in d4_prompts.json.

Picks prompts that are stored in KB-2 (the "kb2" split, so the KB-2 match fires at distance
~0) and that the regex filter (L2) does not already catch, so the KB2 group in the plot is
not empty. Run once on the machine whose data/security_datasets/ built KB-2.

  python pilot/d4/d4_fill_kb2.py --n 10
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))   # repository root

from eval.splits import get_splits  # noqa: E402
from security.l2_pattern_filter import match_injection  # noqa: E402


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default=str(HERE / "d4_prompts.json"))
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--max-chars", type=int, default=400, help="skip very long prompts")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    pool = [d["input_prompt"] for d in get_splits()["kb2"]]
    pool = [p for p in dict.fromkeys(pool) if len(p) <= a.max_chars and not match_injection(p)]
    if not pool:
        raise SystemExit("no KB-2 prompts left after removing the ones L2 catches")
    picked = random.Random(a.seed).sample(pool, min(a.n, len(pool)))

    path = Path(a.prompts)
    prompts = json.loads(path.read_text(encoding="utf-8"))
    prompts["kb2_known"] = picked
    path.write_text(json.dumps(prompts, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(picked)} KB-2 prompts (of {len(pool)} not caught by L2) to {path}")


if __name__ == "__main__":
    main()
