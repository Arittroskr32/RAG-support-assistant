"""Prep item 1, step 1.2: undefended attack success per generator.

"Undefended" = every detector off, L6 off, carrier document placed directly in the
context (exposure is guaranteed, so this measures the generator, not retrieval).
With --fence the same run uses L6-style nonce tags, giving the L6 outcome.

Examples (from the folder that contains pilot/ and eval/):
  python -m pilot.run_undefended --backend ollama --model llama3.2:3b
  python -m pilot.run_undefended --backend ollama --model llama3.1:8b
  python -m pilot.run_undefended --backend anthropic --model claude-sonnet-5-5
  python -m pilot.run_undefended --backend ollama --model llama3.2:3b --fence
  python -m pilot.run_undefended ... --only EN-01,TR-01 --runs 1        # quick test

Results are appended to pilot/results/generations.jsonl (or --out). Finished
(item, model, config, run) combinations are skipped, so an interrupted run can be
restarted. Rows that ended in an error are NOT counted as finished: they are retried,
and the old error row is ignored by report_tables.py / summarize.py.

Every row records `finish` ("stop" / "length"), prompt and completion token counts,
and whether a temperature was sent, so truncated answers can be found afterwards
(python -m pilot.check_truncation).
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from pilot.common import (DEFAULT_MAX_TOKENS, DEFAULT_NUM_CTX, RESULTS_DIR, attack_success,
                          build_messages, generate, load_items, require_real_matcher)

OUT = RESULTS_DIR / "generations.jsonl"


def done_keys(path: Path) -> set:
    """(item, model, config, run) that finished WITHOUT an error."""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as fh:
        return {(r["item_id"], r["model"], r["config"], r["run"])
                for r in (json.loads(l) for l in fh if l.strip()) if not r.get("error")}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="pilot/pilot_items.jsonl")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--backend", choices=["ollama", "local", "anthropic"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX,
                    help="Ollama context window (backend ollama only)")
    ap.add_argument("--fence", action="store_true", help="L6-style nonce fencing on")
    ap.add_argument("--only", help="comma-separated item_ids (for quick tests)")
    a = ap.parse_args(argv)
    require_real_matcher("run_undefended")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    items = load_items(a.items)
    if a.only:
        keep = set(a.only.split(","))
        unknown = keep - {i["item_id"] for i in items}
        if unknown:
            sys.exit(f"unknown item_id(s): {sorted(unknown)}")
        items = [i for i in items if i["item_id"] in keep]
    config = "fenced" if a.fence else "undefended"
    skip = done_keys(out)
    todo = [(it, r) for it in items for r in range(1, a.runs + 1)
            if (it["item_id"], a.model, config, r) not in skip]
    print(f"{len(todo)} generations to run ({a.model}, {config}, backend={a.backend})")

    meta = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
            "backend": a.backend, "model": a.model, "config": config, "runs": a.runs,
            "temperature": a.temperature, "max_tokens": a.max_tokens,
            "num_ctx": a.num_ctx if a.backend == "ollama" else None,
            "items": a.items, "n_items": len(items), "n_todo": len(todo)}
    with open(out.parent / "run_metadata.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta) + "\n")

    n_err = n_cut = 0
    with open(out, "a", encoding="utf-8") as fh:
        for n, (it, run) in enumerate(todo, 1):
            system, user = build_messages(it, fenced=a.fence)
            try:
                g = generate(a.backend, a.model, system, user, base_url=a.base_url,
                             temperature=a.temperature, max_tokens=a.max_tokens, num_ctx=a.num_ctx)
                err = ""
            except Exception as e:  # keep going, record the error; it is retried next time
                g, err = {"text": "", "latency_s": 0.0}, repr(e)[:500]
                n_err += 1
            answer = g["text"]
            res = attack_success(it, answer) if not err else {"success": None, "evidence": "error"}
            n_cut += g.get("finish") == "length"
            row = {"item_id": it["item_id"], "seed_family": it["seed_family"], "group": it["group"],
                   "language": it["language"], "goal_type": it["goal_type"],
                   "threat_class": it["threat_class"], "model": a.model, "backend": a.backend,
                   "config": config, "run": run, "success": res["success"],
                   "evidence": res["evidence"], "latency_s": round(g["latency_s"], 2),
                   "finish": g.get("finish", ""), "prompt_tokens": g.get("prompt_tokens"),
                   "completion_tokens": g.get("completion_tokens"),
                   "temperature_sent": g.get("temperature_sent"),
                   "model_returned": g.get("model_returned", ""),
                   "max_tokens": a.max_tokens,
                   "num_ctx": a.num_ctx if a.backend == "ollama" else None,
                   "error": err, "manual_check": "", "answer": answer}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            mark = "ERR" if err else ("HIT" if res["success"] else "-")
            cut = " CUT" if g.get("finish") == "length" else ""
            print(f"[{n}/{len(todo)}] {it['item_id']} run {run}: {mark}{cut} ({g['latency_s']:.1f}s)",
                  file=sys.stderr)

    print(f"done: {len(todo) - n_err} ok, {n_err} errors (re-run the same command to retry), "
          f"{n_cut} answers cut off at max_tokens")


if __name__ == "__main__":
    main()
