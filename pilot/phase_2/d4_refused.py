"""Plan step H: the D4 timing side channel, reported the way the senior asked.

  python -m pilot.phase_2.d4_refused --events logs/security_events.jsonl \
      --traffic pilot/phase_1/d4/out/traffic.csv --tag before
  # after setting refusal_min_latency_ms and re-running d4_traffic.py:
  python -m pilot.phase_2.d4_refused --events logs/security_events.jsonl --traffic <new traffic.csv> --tag after

The refusal message already tells an attacker THAT they were blocked, so "was an answer
generated" is not a leak. The leak is WHICH pre-generation layer fired. This script:

  1. restricts to requests refused before generation (L2, L1, L2b, KB2, L3) and reports the
     leave-one-out nearest-neighbour accuracy of guessing the layer from latency alone,
     against guessing the most common layer, plus a confusion table;
  2. lists the slowest refusals of each layer with the per-layer timings from the security
     log, their position in the traffic and the gap since the previous request, so outliers
     such as the 1.4 s KB-2 refusal can be explained (cold start, a slow earlier layer,
     contention with a generation still running) before a padding value is chosen;
  3. prints the largest refusal latency with and without the flagged outliers, i.e. the
     smallest padding (refusal_min_latency_ms) that would cover every refusal.

Needs the security log of the same run (logs/security_events.jsonl on the GPU machine).
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from pilot.phase_2.common2 import RESULTS_DIR, need

PRE_GEN = {"L2", "L1", "L2b", "KB2", "L3"}


def load_timings(path: str) -> dict:
    """request_id -> {"timings": {...}, "blocked_at": ...} from the raw security log."""
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("request_id"):
                out[r["request_id"]] = {"timings": r.get("timings_ms") or {}, "blocked_at": r.get("blocked_at"),
                                        "ts": r.get("ts") or r.get("timestamp") or r.get("time")}
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="logs/security_events.jsonl")
    ap.add_argument("--traffic", default="pilot/phase_1/d4/out/traffic.csv")
    ap.add_argument("--tag", default="before")
    ap.add_argument("--top", type=int, default=3, help="slowest refusals listed per layer")
    ap.add_argument("--out-dir", default=str(RESULTS_DIR))
    a = ap.parse_args(argv)

    import numpy as np
    import pandas as pd

    from pilot.phase_1.d4.d4_plot import load_events, loo_accuracy

    need(a.events, "the API's security log; run the D4 traffic first (run.md step 13)")
    need(a.traffic, "run pilot/phase_1/d4/d4_traffic.py first (run.md step 13)")
    ev = load_events(a.events)
    tr = pd.read_csv(a.traffic)
    df = tr.merge(ev, on="request_id", how="left")
    missing = df.group.isna().sum()
    df["group"] = df.group.fillna("unknown")
    df["latency_ms"] = pd.to_numeric(df.client_ms, errors="coerce")
    df = df[df.latency_ms > 0].sort_values("n").reset_index(drop=True)
    df["gap_to_previous_ms"] = df.latency_ms.shift(1)          # the previous request's duration
    ref = df[df.group.isin(PRE_GEN)].copy()
    if len(ref) < 2:
        raise SystemExit("fewer than 2 pre-generation refusals: is this the right security log?")
    acc, base = loo_accuracy(ref, "group")

    # confusion of the LOO nearest neighbour
    x, y = np.log(ref.latency_ms.to_numpy()), ref.group.to_numpy()
    conf = Counter()
    for i in range(len(ref)):
        d = np.abs(x - x[i])
        d[i] = np.inf
        conf[(y[i], y[d.argmin()])] += 1
    labels = sorted(set(y))

    timings = load_timings(a.events)
    md = [f"# D4: which layer refused, from latency alone ({a.tag})", "",
          f"Traffic `{a.traffic}`, security log `{a.events}`. "
          f"{len(df)} requests, {len(ref)} refused before generation"
          + (f", {missing} without a log entry" if missing else "") + ".", "",
          "| Question | Attacker accuracy | Guess the most common layer |", "|---|---|---|",
          f"| Which pre-generation layer refused (refused requests only) | {acc:.0%} | {base:.0%} |", "",
          "Confusion (rows = true layer, columns = guessed):", "",
          "| true \\ guessed | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for t in labels:
        md.append(f"| {t} | " + " | ".join(str(conf[(t, g)]) for g in labels) + " |")

    md += ["", "## Slowest refusals per layer", "",
           "| Layer | Request n | Client ms | Server total ms | Slowest server step | Previous request took (ms) |"
           " Position in traffic |", "|---|---|---|---|---|---|---|"]
    outliers = set()
    for g, sub in ref.groupby("group"):
        q1, q3 = sub.latency_ms.quantile(.25), sub.latency_ms.quantile(.75)
        fence = q3 + 3 * (q3 - q1)
        for _, r in sub.sort_values("latency_ms", ascending=False).head(a.top).iterrows():
            t = timings.get(r.request_id, {}).get("timings", {})
            steps = {k: v for k, v in t.items() if k != "total"}
            slow = max(steps.items(), key=lambda kv: kv[1]) if steps else ("-", float("nan"))
            flag = r.latency_ms > fence
            if flag:
                outliers.add(r.request_id)
            md.append(f"| {g}{' (outlier)' if flag else ''} | {int(r.n)} | {r.latency_ms:.0f} | {t.get('total', '-')} | "
                      f"{slow[0]} {slow[1]:.0f} ms | "
                      f"{'-' if math.isnan(r.gap_to_previous_ms) else f'{r.gap_to_previous_ms:.0f}'} | "
                      f"{int(r.n)} of {len(df)} |")
    worst = ref.latency_ms.max()
    clean = ref[~ref.request_id.isin(outliers)].latency_ms.max()
    md += ["", f"Outlier rule: above Q3 + 3 x IQR of its own layer. Read the 'slowest server step' column: a slow "
               f"L0/L1/embedding step on an early request points to a cold start; a slow step right after a long "
               f"generation points to GPU contention; a slow step inside KB2 itself would be a real KB-2 cost.", "",
           f"Largest refusal latency: {worst:.0f} ms; without the flagged outliers: {clean:.0f} ms. "
           f"`refusal_min_latency_ms` must be above the largest latency you cannot explain away; "
           f"generated answers in this run started at {df[~df.group.isin(PRE_GEN | {'unknown'})].latency_ms.min():.0f} ms."]
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"d4_refused_{a.tag}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
