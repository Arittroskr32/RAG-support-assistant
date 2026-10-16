"""Build data/direct_injection.jsonl (run.md step 12) from a spreadsheet you fill in.

  python -m pilot.phase_2.make_direct                    # data/direct_injection.csv -> .jsonl
  python -m pilot.phase_2.make_direct --check            # only report problems

The CSV (Excel: save as "CSV UTF-8") has one row per attack idea or benign prompt:

  label, seed_family, technique, threat_class, goal_type, canary_core, en, bn, banglish

* attack rows: one seed family, written in up to three languages (en, bn, banglish). Each filled
  language cell becomes one sample with that family, so the paired analysis can compare
  languages within a family. Use families that are NOT in KB-2 (D-36).
  goal_type marker / phish / pii needs a canary_core (4+ digits, unique, not a year) that
  appears in every filled cell; leave goal_type empty for attacks without a canary.
* benign rows: label "benign"; each filled language cell becomes one benign prompt.

The starter CSV holds the benign prompts and the example family d01 from
data/examples/direct_injection.jsonl; add your attack families below it.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from pilot.phase_2 import tags
from pilot.phase_2.common2 import DATA2_DIR, ROOT, canary_hit

LANGS = ("en", "bn", "banglish")
CANARY_GOALS = ("marker", "phish", "pii")


def build(rows: list[dict]) -> tuple[list[dict], list[str]]:
    out, problems = [], []
    families = Counter(r["seed_family"].strip() for r in rows if r["label"].strip() == "attack")
    n_att = n_ben = 0
    for i, r in enumerate(rows, 2):                     # line 1 is the header
        label = r["label"].strip()
        if label not in ("attack", "benign"):
            problems.append(f"line {i}: label must be attack or benign, not {label!r}")
            continue
        fam = r.get("seed_family", "").strip()
        if label == "attack":
            if not fam:
                problems.append(f"line {i}: attack without seed_family")
            elif families[fam] > 1:
                problems.append(f"line {i}: seed_family {fam} is used on {families[fam]} rows (one row per family)")
        goal, core = r.get("goal_type", "").strip(), r.get("canary_core", "").strip()
        if label == "attack" and goal in CANARY_GOALS and not re.fullmatch(r"\d{4,}", core):
            problems.append(f"line {i}: goal_type {goal} needs a canary_core of 4+ digits")
        for lang in LANGS:
            text = tags.unwrap(r.get(lang, "").strip(), "query")
            if not text:
                continue
            for p in tags.problems(r.get(lang, "").strip(), "query"):
                problems.append(f"line {i} {lang}: {p}")
            if label == "attack":
                n_att += 1
                if goal in CANARY_GOALS and core and not canary_hit(text, core):
                    problems.append(f"line {i} {lang}: canary {core} is not in the text")
                s = {"sample_id": f"di-{n_att:03d}", "label": "attack", "text": text, "seed_family": fam,
                     "language": lang, "threat_class": r.get("threat_class", "").strip() or "4",
                     "technique": r.get("technique", "").strip() or "plain"}
                if goal:
                    s["goal_type"] = goal
                if core:
                    s["canary_core"] = core
            else:
                n_ben += 1
                s = {"sample_id": f"bq-{n_ben:03d}", "label": "benign", "text": text, "language": lang}
            out.append(s)
    return out, problems


def core_collisions(samples: list[dict]) -> list[str]:
    cores = {s["canary_core"] for s in samples if s.get("canary_core")}
    hits = []
    for p in (ROOT / "data").rglob("*"):
        if p.is_file() and "security_datasets" not in p.parts and p.suffix in (".md", ".txt", ".json", ".jsonl", ".csv"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            hits += [f"canary {c} also appears in {p.relative_to(ROOT)}" for c in cores if c in text]
    return hits


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DATA2_DIR / "direct_injection.csv"))
    ap.add_argument("--out", default=str(DATA2_DIR / "direct_injection.jsonl"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    samples, problems = build(rows)
    problems += core_collisions(samples)
    att = [s for s in samples if s["label"] == "attack"]
    by_lang = Counter(s["language"] for s in att)
    print(f"{len(att)} attacks in {len({s['seed_family'] for s in att})} families "
          f"({', '.join(f'{l} {by_lang[l]}' for l in LANGS)}), "
          f"{len(samples) - len(att)} benign prompts")
    for p in problems:
        print("FAIL", p)
    if problems:
        raise SystemExit(f"{len(problems)} problem(s); nothing written")
    if not a.check:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(s, ensure_ascii=False) + "\n" for s in samples)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
