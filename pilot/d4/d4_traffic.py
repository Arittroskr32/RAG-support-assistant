"""Prep item 4 / design check D4, step 1: generate traffic that reaches every blocking layer.

Measures latency the way an attacker sees it: wall-clock time at the client.

  python pilot/d4/d4_traffic.py --url http://127.0.0.1:8000 --api-key <key> --repeats 3

Before running:
  * put d4_secret_doc.md in data/public_faq/ and rebuild KB-4 (so L8 has something to catch);
  * fill kb2_known in d4_prompts.json: python pilot/d4/d4_fill_kb2.py;
  * raise rate_limit_soft / rate_limit_hard for this run, or keep --sleep high enough,
    otherwise KB-1 answers 429 and the soft limit bumps risk scores.
Requests are shuffled so slow drift (GPU warm-up, other load) does not line up with a category.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--prompts", default=str(HERE / "d4_prompts.json"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--warmup", type=int, default=3, help="unrecorded benign requests first")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    prompts = json.load(open(a.prompts, encoding="utf-8"))
    empty = [cat for cat, qs in prompts.items()
             if not cat.startswith("_") and not [q for q in qs if not q.startswith("<")]]
    if empty:
        print(f"WARNING: no real prompts in {empty} (only placeholders); that category will be "
              f"missing from the plot. Run pilot/d4/d4_fill_kb2.py to fill kb2_known.")
    jobs = [(cat, q) for cat, qs in prompts.items() if not cat.startswith("_")
            for q in qs if not q.startswith("<") for _ in range(a.repeats)]
    random.Random(a.seed).shuffle(jobs)

    s = requests.Session()
    s.headers.update({"X-API-Key": a.api_key, "Content-Type": "application/json"})
    for q in prompts["benign"][:a.warmup]:
        s.post(f"{a.url}/chat", json={"query": q}, timeout=600)

    path = OUT / "traffic.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["n", "expected", "query", "status", "request_id",
                                           "blocked", "client_ms", "server_ms"])
        w.writeheader()
        for n, (cat, q) in enumerate(jobs, 1):
            t0 = time.perf_counter()
            try:
                r = s.post(f"{a.url}/chat", json={"query": q}, timeout=600)
                ms = (time.perf_counter() - t0) * 1000
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            except Exception as e:
                ms, body, r = (time.perf_counter() - t0) * 1000, {"error": repr(e)}, None
            w.writerow({"n": n, "expected": cat, "query": q,
                        "status": r.status_code if r is not None else "error",
                        "request_id": body.get("request_id", ""), "blocked": body.get("blocked", ""),
                        "client_ms": round(ms, 1), "server_ms": body.get("latency_ms", "")})
            fh.flush()
            status = r.status_code if r is not None else "ERR"  # a 4xx Response is falsy
            print(f"[{n}/{len(jobs)}] {cat:<14} {ms:8.0f} ms  status={status}")
            time.sleep(a.sleep)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
