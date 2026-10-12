"""Plan step D2: is the candidate generator actually better in Bangla? Check BEFORE using it.

  # 1. answer benign Bangla/Banglish questions from their gold document (real L6/L7 prompt)
  python -m pilot.phase_2.bangla_check run --models llama3.2:3b qwen3:4b
  # 2. a native speaker fills the review columns in results/bangla_check_<model>.csv
  # 3. summary and the decision rule
  python -m pilot.phase_2.bangla_check summarize

Questions come from data/benign_questions.jsonl (the same file as retrieval_eval.py); only
languages bn and banglish are used unless --languages says otherwise. The gold document is
given directly (exposure forced), so this measures the generator's Bangla, not retrieval.

Review columns (1 = yes, 0 = no):
  correct      the facts match the document
  same_language  answered in the question's language (Bangla for bn, Bangla or Banglish for banglish)
  natural      reads like normal Bangla, not broken or machine-like
Decision rule (write it down before looking): the candidate counts as Bangla-capable if its
share of answers that are correct AND same_language AND natural is clearly above the deployed
model's (default: at least 15 percentage points), and it is not worse on correct.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from pilot.phase_2 import tags
from pilot.phase_2.common2 import (DATA2_DIR, RESULTS_DIR, ROOT, build_prompt, generate2, postprocess,
                                   read_jsonl, wants_think_off)

REVIEW = ["correct", "same_language", "natural", "notes"]


def gold_text(gold: str, benign_dir: Path) -> str:
    p = benign_dir.parent / gold if gold.startswith("benign_docs/") else ROOT / "data" / gold
    return tags.unwrap(p.read_text(encoding="utf-8"), "passage")


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", model).strip("-")


def run(a) -> None:
    qs = [{**q, "question": tags.unwrap(q["question"], "query")}
          for q in read_jsonl(a.questions) if q["language"] in a.languages]
    if not qs:
        raise SystemExit(f"no {a.languages} questions in {a.questions}")
    for model in a.models:
        think = wants_think_off(model, "auto")
        out = Path(a.out_dir) / f"bangla_check_{slug(model)}.csv"
        rows = []
        for n, q in enumerate(qs, 1):
            item = {"item_id": q["qid"], "carrier_doc": gold_text(q["gold_source"], Path(a.benign_dir)),
                    "question": q["question"]}
            system, user, ctx = build_prompt(item, "real")
            try:
                g = generate2("ollama", model, system, user, seed=a.seed, base_url=a.base_url,
                              temperature=a.temperature, think=think)
                ans, _ = postprocess(g["text"], ctx)
                lat, err = round(g["latency_s"], 2), ""
            except Exception as e:
                ans, lat, err = "", 0, repr(e)[:300]
            rows.append({"qid": q["qid"], "language": q["language"], "model": model, "question": q["question"],
                         "answer": ans, "latency_s": lat, "error": err, **{k: "" for k in REVIEW}})
            print(f"[{model} {n}/{len(qs)}] {q['qid']} {'ERR' if err else ''}")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig: Excel shows Bangla correctly
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {out}: fill in {', '.join(REVIEW[:3])} (1/0)")


def summarize(a) -> None:
    sheets = sorted(Path(a.out_dir).glob("bangla_check_*.csv"))
    if not sheets:
        raise SystemExit("no bangla_check_*.csv sheets")
    md = ["# Bangla answer check (D2)", "", "| Model | Language | Reviewed | Correct | Same language | Natural | "
          "All three | Median latency (s) |", "|---|---|---|---|---|---|---|---|"]
    for s in sheets:
        rows = list(csv.DictReader(open(s, encoding="utf-8-sig")))
        for lang in sorted({r["language"] for r in rows}):
            rs = [r for r in rows if r["language"] == lang and all(r[k] in ("0", "1") for k in REVIEW[:3])]
            if not rs:
                md.append(f"| {rows[0]['model']} | {lang} | 0 (not reviewed yet) | | | | | |")
                continue
            share = lambda f: sum(f(r) for r in rs) / len(rs)
            lats = sorted(float(r["latency_s"] or 0) for r in rs)
            md.append(f"| {rows[0]['model']} | {lang} | {len(rs)} | {share(lambda r: r['correct'] == '1'):.0%} | "
                      f"{share(lambda r: r['same_language'] == '1'):.0%} | {share(lambda r: r['natural'] == '1'):.0%} | "
                      f"{share(lambda r: all(r[k] == '1' for k in REVIEW[:3])):.0%} | {lats[len(lats) // 2]:.1f} |")
    md += ["", "Decision rule: Bangla-capable if 'All three' is at least 15 points above the deployed model and "
               "'Correct' is not lower."]
    (Path(a.out_dir) / "bangla_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", default=["llama3.2:3b", "qwen3:4b"])
    r.add_argument("--questions", default=str(DATA2_DIR / "benign_questions.jsonl"))
    r.add_argument("--benign-dir", default=str(DATA2_DIR / "benign_docs"))
    r.add_argument("--languages", nargs="+", default=["bn", "banglish"])
    r.add_argument("--seed", type=int, default=20262001)
    r.add_argument("--temperature", type=float, default=0.2)
    r.add_argument("--base-url", default="http://localhost:11434")
    r.add_argument("--out-dir", default=str(RESULTS_DIR))
    s = sub.add_parser("summarize")
    s.add_argument("--out-dir", default=str(RESULTS_DIR))
    a = ap.parse_args(argv)
    run(a) if a.cmd == "run" else summarize(a)


if __name__ == "__main__":
    main()
