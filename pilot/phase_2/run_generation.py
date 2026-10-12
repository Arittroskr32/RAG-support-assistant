"""Phase 2: generator-only runs (exposure forced) with the real L6/L7 prompt as baseline.

Plan steps B2, B3, B7, C1, C2 and D2. One row per (item, model, config, phase, run) is
appended to pilot/phase_2/results/generations2.jsonl; finished rows are skipped, so an
interrupted run can simply be restarted.

  # selection run: which test items are valid attacks on this generator
  python -m pilot.phase_2.run_generation --backend ollama --model llama3.2:3b --phase selection

  # measurement run on fresh seeds, only the valid items (see select_valid.py)
  python -m pilot.phase_2.run_generation --backend ollama --model llama3.2:3b --phase measurement \
      --only-file pilot/phase_2/results/valid_llama3.2-3b.json

  # the two controls (make_variants.py writes the file)
  python -m pilot.phase_2.run_generation --backend ollama --model llama3.2:3b --phase measurement \
      --items pilot/phase_2/results/variants2.jsonl

  # the same items with the phase-1 stand-in prompt, for comparison
  python -m pilot.phase_2.run_generation ... --prompt stand_in

  # phase-1 dev items through the new baseline
  python -m pilot.phase_2.run_generation ... --items pilot/phase_1/pilot_items.jsonl --phase dev

Seeds: run r uses seed = --seed-base + 1000 * phase_offset + r, so selection and
measurement runs never share a seed (B2). Temperature and seed are stored on every row.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from pilot.phase_2.common2 import (GENERATIONS, attack_success, build_prompt, config_label, generate2,
                                   git_commit, group_code, load_items2, ollama_digest, postprocess,
                                   require_real_matcher, wants_think_off)

PHASES = {"dev": 0, "selection": 1, "measurement": 2}


def seed_for(base: int, phase: str, run: int) -> int:
    return base + 1000 * PHASES[phase] + run


def done_keys(path: Path) -> set:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as fh:
        return {(r["item_id"], r["model"], r["config"], r["phase"], r["run"])
                for r in (json.loads(l) for l in fh if l.strip()) if not r.get("error")}


def select(items: list[dict], only: str | None, only_file: str | None, variant: str) -> list[dict]:
    if variant != "all":
        items = [i for i in items if i["variant"] == variant]
    keep = set()
    if only:
        keep |= set(only.split(","))
    if only_file:
        data = json.loads(Path(only_file).read_text(encoding="utf-8"))
        keep |= set(data["items"] if isinstance(data, dict) else data)
    if keep:
        known = {i["item_id"] for i in items} | {i.get("parent_id") for i in items}
        unknown = keep - known
        if unknown:
            sys.exit(f"unknown item_id(s): {sorted(unknown)[:10]}")
        # a control is selected when its parent is selected
        items = [i for i in items if i["item_id"] in keep or i.get("parent_id") in keep]
    return items


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--items", default="pilot/phase_2/pilot_items2.jsonl")
    ap.add_argument("--out", default=str(GENERATIONS))
    ap.add_argument("--backend", choices=["ollama", "local", "anthropic"], default="ollama")
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--phase", choices=list(PHASES), required=True,
                    help="dev = phase-1 items; selection = find valid attacks; measurement = fresh runs")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seed-base", type=int, default=20261012)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--prompt", choices=["real", "stand_in"], default="real",
                    help="real = repository L6/L7 (the phase-2 baseline); stand_in = phase-1 prompt")
    ap.add_argument("--no-l6", action="store_true", help="ablation: no nonce fencing")
    ap.add_argument("--think", choices=["auto", "off", "on"], default="auto",
                    help="auto switches Qwen3 thinking off")
    ap.add_argument("--variant", choices=["attack", "positive_control", "base_rate", "all"], default="all")
    ap.add_argument("--only", help="comma-separated item ids")
    ap.add_argument("--only-file", help="JSON list (or {'items': [...]}) of item ids, e.g. valid_<model>.json")
    a = ap.parse_args(argv)
    require_real_matcher("run_generation")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    items = select(load_items2(a.items), a.only, a.only_file, a.variant)
    if not items:
        sys.exit("no items selected")
    if a.phase == "measurement" and not a.only_file and not a.only:
        print("note: measurement run without --only-file: every item is run, valid or not. "
              "Restrict outcome metrics to valid items in analyze.py.", file=sys.stderr)
    l6 = not a.no_l6
    config = config_label(a.prompt, l6)
    think = wants_think_off(a.model, a.think) if a.backend == "ollama" else None
    skip = done_keys(out)
    todo = [(it, r) for it in items for r in range(1, a.runs + 1)
            if (it["item_id"], a.model, config, a.phase, r) not in skip]
    print(f"{len(todo)} generations to run ({a.model}, {config}, phase={a.phase}, backend={a.backend})")

    meta = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "backend": a.backend,
            "model": a.model, "model_digest": ollama_digest(a.model, a.base_url) if a.backend == "ollama" else "",
            "config": config, "phase": a.phase, "runs": a.runs, "seed_base": a.seed_base,
            "temperature": a.temperature, "max_tokens": a.max_tokens,
            "num_ctx": a.num_ctx if a.backend == "ollama" else None, "think": think,
            "items": a.items, "n_items": len(items), "n_todo": len(todo), "git_commit": git_commit()}
    with open(out.parent / "run_metadata2.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta) + "\n")

    n_err = n_cut = 0
    with open(out, "a", encoding="utf-8") as fh:
        for n, (it, run) in enumerate(todo, 1):
            system, user, ctx = build_prompt(it, a.prompt, l6)
            seed = seed_for(a.seed_base, a.phase, run)
            try:
                g = generate2(a.backend, a.model, system, user, seed=seed, base_url=a.base_url,
                              temperature=a.temperature, max_tokens=a.max_tokens, num_ctx=a.num_ctx,
                              think=think)
                err = ""
            except Exception as e:
                g, err = {"text": "", "latency_s": 0.0}, repr(e)[:500]
                n_err += 1
            answer, echoed = postprocess(g["text"], ctx) if not err else ("", 0)
            res = attack_success(it, answer) if not err else {"success": None, "evidence": "error"}
            n_cut += g.get("finish") == "length"
            row = {"item_id": it["item_id"], "parent_id": it.get("parent_id") or it["item_id"],
                   "variant": it["variant"], "seed_family": it["seed_family"], "group": it["group"],
                   "group_code": group_code(it), "language": it["language"], "goal_type": it["goal_type"],
                   "technique": it["technique"], "threat_class": it["threat_class"],
                   "author": it.get("author", ""), "split": it.get("split", ""),
                   "model": a.model, "backend": a.backend, "config": config, "phase": a.phase, "run": run,
                   "seed": g.get("seed_sent", seed) if not err else seed, "temperature": a.temperature,
                   "think_sent": g.get("think_sent"), "success": res["success"], "evidence": res["evidence"],
                   "latency_s": round(g["latency_s"], 2), "finish": g.get("finish", ""),
                   "prompt_tokens": g.get("prompt_tokens"), "completion_tokens": g.get("completion_tokens"),
                   "echoed_tags": echoed, "max_tokens": a.max_tokens, "error": err, "manual_check": "",
                   "answer": answer}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            mark = "ERR" if err else ("HIT" if res["success"] else "-")
            print(f"[{n}/{len(todo)}] {it['item_id']} run {run} seed {seed}: {mark}"
                  f"{' CUT' if g.get('finish') == 'length' else ''} ({g['latency_s']:.1f}s)", file=sys.stderr)

    print(f"done: {len(todo) - n_err} ok, {n_err} errors (re-run the same command to retry), "
          f"{n_cut} answers cut off at max_tokens")


if __name__ == "__main__":
    main()
