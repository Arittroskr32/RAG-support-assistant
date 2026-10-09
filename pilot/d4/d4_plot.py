"""Prep item 4 / design check D4, step 2: latency grouped by the layer that blocked.

  python pilot/d4/d4_plot.py --events logs/security_events.jsonl
  python pilot/d4/d4_plot.py --events logs/security_events.jsonl --traffic pilot/d4/out/traffic.csv

With --traffic, latency is the client-side wall-clock time (what an attacker measures),
joined to the server log by request_id. Without it, the server's own latency field is used.

Besides the box plot it answers threat row 9 directly: can an attacker tell which layer
fired from latency alone, better than chance? (leave-one-out 1-nearest-neighbour classifier
on log-latency, compared with always guessing the most common group).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
BLOCK_KEYS = ["blocked_at", "blocking_layer", "blocked_by", "block_layer"]
LAT_KEYS = ["latency_ms", "total_latency_ms", "total_ms", "elapsed_ms"]
# groups whose answer was generated before the decision. L8 regex findings only redact
# (verdict "redacted", blocked_at null); L8 blocks only on a KB-5 semantic match.
GENERATED = {"not blocked", "L8 redacted", "L8"}


def first_key(rec: dict, keys: list[str]):
    for k in keys:
        if k in rec:
            return rec[k]
    return None


def load_events(path: str) -> pd.DataFrame:
    """One row per request. The log may hold several lines per request (one per layer,
    or a start and an end event); a request counts as blocked if ANY of its lines names
    a blocking layer, and its latency is the largest latency logged for it."""
    rows = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        blocked = first_key(r, BLOCK_KEYS)
        if not blocked and r.get("verdict") == "redacted":
            blocked = "L8 redacted"
        # the orchestrator logs per-layer times under timings_ms, with the request total in "total"
        lat = first_key(r, LAT_KEYS)
        if lat is None and isinstance(r.get("timings_ms"), dict):
            lat = r["timings_ms"].get("total")
        rows.append({"request_id": r.get("request_id"), "blocked": blocked,
                     "server_ms": pd.to_numeric(lat, errors="coerce")})
    ev = pd.DataFrame(rows)
    if ev.empty:
        raise SystemExit(f"no events in {path}")
    n_lines = len(ev)
    with_id = ev[ev.request_id.notna()]
    agg = with_id.groupby("request_id", sort=False).agg(
        group=("blocked", lambda s: next((x for x in s if isinstance(x, str) and x), "not blocked")),
        server_ms=("server_ms", "max")).reset_index()
    no_id = ev[ev.request_id.isna()].assign(
        group=lambda d: d.blocked.where(d.blocked.map(lambda x: isinstance(x, str) and bool(x)),
                                        "not blocked"))
    ev = pd.concat([agg, no_id[["request_id", "group", "server_ms"]]], ignore_index=True)
    if len(ev) < n_lines:
        print(f"note: {n_lines} log lines collapsed to {len(ev)} requests (several lines per request)")
    return ev


def loo_accuracy(df: pd.DataFrame, label: str) -> tuple[float, float]:
    """Leave-one-out 1-nearest-neighbour on log-latency: for each request, guess the
    label of the closest OTHER request. Unlike comparing with group medians, this also
    works when one class mixes fast and slow requests (e.g. "not generated" = L2 + L3)."""
    x, y = np.log(df.latency_ms.to_numpy()), df[label].to_numpy()
    if len(df) < 2:
        return float("nan"), float("nan")
    correct = 0
    for i in range(len(df)):
        d = np.abs(x - x[i])
        d[i] = np.inf
        correct += y[d.argmin()] == y[i]
    return correct / len(df), pd.Series(y).value_counts(normalize=True).iloc[0]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="logs/security_events.jsonl")
    ap.add_argument("--traffic", default="")
    ap.add_argument("--tag", default="before", help="'before' or 'after' the padding fix")
    a = ap.parse_args(argv)
    OUT.mkdir(exist_ok=True)

    ev = load_events(a.events)
    if a.traffic:
        tr = pd.read_csv(a.traffic)
        df = tr.merge(ev, on="request_id", how="left", suffixes=("", "_log"))
        df["group"] = df["group"].fillna("unknown")
        df.loc[df.status == 429, "group"] = "rate limit (429)"
        df["latency_ms"] = df.client_ms
    else:
        df = ev.rename(columns={"server_ms": "latency_ms"})
    df = df[pd.to_numeric(df.latency_ms, errors="coerce") > 0].copy()
    df["latency_ms"] = df.latency_ms.astype(float)

    stats = (df.groupby("group").latency_ms
             .agg(n="size", median="median", p25=lambda s: s.quantile(.25),
                  p75=lambda s: s.quantile(.75), min="min", max="max")
             .sort_values("median").round(0))
    order = list(stats.index)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.2))
    data = [df.loc[df.group == g, "latency_ms"] for g in order]
    ax.boxplot(data, showfliers=False)
    ax.set_xticks(range(1, len(order) + 1), order)
    rng = np.random.default_rng(0)
    for i, d in enumerate(data, 1):
        ax.scatter(i + rng.uniform(-0.15, 0.15, len(d)), d, s=10, alpha=0.6)
    ax.set_yscale("log")
    ax.set_ylabel("response time (ms, log scale)")
    ax.set_xlabel("layer that blocked the request (blocked_at)")
    src = "client wall-clock" if a.traffic else "server log"
    ax.set_title(f"D4: response time by blocking layer ({src}, {a.tag})")
    plt.xticks(rotation=20)
    plt.tight_layout()
    png = OUT / f"d4_latency_by_layer_{a.tag}.png"
    plt.savefig(png, dpi=150)

    print(f"wrote {png}")
    small = stats[stats.n < 3].index.tolist()
    if small:
        print(f"note: groups with fewer than 3 requests ({small}); raise --repeats in d4_traffic.py")
    acc, base = loo_accuracy(df, "group")
    df["generated"] = df.group.isin(GENERATED)
    acc2, base2 = loo_accuracy(df, "generated")
    md = [f"# D4 latency by blocking layer ({a.tag})", "", f"Source: {src}. Plot: `{png.name}`", "",
          stats.to_markdown(), "",
          "## Can an attacker tell the layer from latency? (threat row 9)", "",
          "| Question | Attacker accuracy | Guess-the-majority baseline |", "|---|---|---|",
          f"| Which layer fired | {acc:.0%} | {base:.0%} |",
          f"| Was an answer generated before the decision | {acc2:.0%} | {base2:.0%} |", "",
          "Accuracy well above the baseline = side channel demonstrated."]
    if a.traffic and (df.group == "unknown").any():
        md += ["", f"WARNING: {(df.group == 'unknown').sum()} requests had no matching request_id in the log "
               "(wrong --events file, or the log was rotated)."]
    (OUT / f"d4_summary_{a.tag}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
