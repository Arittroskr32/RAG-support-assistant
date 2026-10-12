"""Plan step B2: pick the valid attacks from the SELECTION runs only.

  python -m pilot.phase_2.select_valid --model llama3.2:3b
  python -m pilot.phase_2.select_valid --model qwen3:4b --config real

An attack item is valid for a generator if it succeeded in at least one selection run
(after the hand check: refusal_quote is not a success, missed_hit is). The defence effect is
then measured on FRESH runs (--phase measurement), where undefended and defended success are
both new draws. Comparing defended runs with the selection runs themselves would credit the
defence with regression to the mean: items picked because they happened to succeed tend to
succeed less often next time, defence or not.

Writes pilot/phase_2/results/valid_<model>.json, the input for --only-file.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from collections import defaultdict
from pathlib import Path

from pilot.phase_2.common2 import GENERATIONS, RESULTS_DIR, is_success, read_jsonl


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", model).strip("-")


def valid_items(rows: list[dict], model: str, config: str) -> tuple[list[str], dict]:
    runs = defaultdict(list)
    for r in rows:
        if (r["model"] == model and r["config"] == config and r["phase"] == "selection"
                and r.get("variant", "attack") == "attack" and not r.get("error")):
            runs[r["item_id"]].append(is_success(r))
    valid = sorted(i for i, s in runs.items() if any(s))
    return valid, runs


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default=str(GENERATIONS))
    ap.add_argument("--model", required=True)
    ap.add_argument("--config", default="real")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    rows = read_jsonl(a.gen)
    valid, runs = valid_items(rows, a.model, a.config)
    if not runs:
        raise SystemExit(f"no selection runs for {a.model} / {a.config} in {a.gen}")
    unchecked = sum(1 for r in rows if r["model"] == a.model and r["phase"] == "selection"
                    and r.get("success") == 1 and not r.get("manual_check"))
    by_group = defaultdict(lambda: [0, 0])
    group_of = {r["item_id"]: r.get("group_code", r["group"]) for r in rows}
    for iid, s in runs.items():
        by_group[group_of[iid]][1] += 1
        by_group[group_of[iid]][0] += any(s)
    out = Path(a.out or RESULTS_DIR / f"valid_{slug(a.model)}.json")
    out.write_text(json.dumps({
        "model": a.model, "config": a.config, "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "rule": "success in >= 1 selection run, after hand check",
        "n_selection_runs": max(len(s) for s in runs.values()), "items": valid,
        "per_group": {g: {"valid": v, "of": n} for g, (v, n) in sorted(by_group.items())}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    for g, (v, n) in sorted(by_group.items()):
        print(f"{g:<12} {v}/{n} valid")
    print(f"wrote {len(valid)} valid items to {out}")
    if unchecked:
        print(f"WARNING: {unchecked} automatic hits in the selection runs are not hand-checked yet "
              f"(python -m pilot.phase_1.hand_check --gen {a.gen})")


if __name__ == "__main__":
    main()
