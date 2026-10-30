"""Stress test of the official-contact check (senior, final runs, point 3). The check itself is frozen:
this script only measures it.

  # 1. offline: hand-written hard cases (no model needed, seconds)
  python -m pilot.phase_2_extension.contact_stress offline
  # 2. benign questions whose answers SHOULD contain an official contact, in English, Bangla and
  #    Banglish (Ollama; the gold document is given directly, real L6/L7 prompt, as bangla_check)
  python -m pilot.phase_2_extension.contact_stress benign --models llama3.2:3b qwen3:4b-instruct-2507-q4_K_M
  # 3. both tables -> results/final/contact_stress.md
  python -m pilot.phase_2_extension.contact_stress report

offline reads data/contact_stress_cases.jsonl. Each case says whether the check SHOULD flag it
("flag": an attacker's contact, written to slip past) or let it through ("pass": an official contact
or something that is not a contact at all). `target` is the part of the attacker's contact that has
to be inside a removed value for the case to count as caught (empty = any removal counts). Cases
with a `tenant` use official_contacts.yaml plus the test tenants in data/contact_tenants_test.yaml.
Add cases to the file freely (for example ones a native speaker writes); nothing else changes.

benign writes results/final/contact_benign.csv: one row per (model, question, run) with the answer,
whether an official contact appears in it, and what the check would remove (a false flag).
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from pilot.phase_2_extension.common_ext import DATA, OFFICIAL_CONTACTS, RESULTS, frac, md_table, read_jsonl

FINAL = RESULTS / "final"
CASES = DATA / "contact_stress_cases.jsonl"
TENANTS = DATA / "contact_tenants_test.yaml"
QUESTIONS = DATA / "contact_benign_questions.jsonl"


def officials(tenants_file: Path = TENANTS):
    """(official list for the default tenant, function tenant -> official list)."""
    import yaml
    from pilot.phase_2_extension.contact_guard import official_for
    data = yaml.safe_load(Path(OFFICIAL_CONTACTS).read_text(encoding="utf-8")) or {}
    if Path(tenants_file).exists():
        data = {**data, "tenants": (yaml.safe_load(Path(tenants_file).read_text(encoding="utf-8")) or {}).get("tenants", {})}
    return official_for(data), (lambda t: official_for(data, t))


def caught(unofficial: list, target: str) -> bool:
    from pilot.phase_2_extension.contact_guard import normalize
    if not unofficial:
        return False
    if not target:
        return True
    t = target.lower()
    for _, v in unofficial:
        low = normalize(v).lower()
        if t in low or (t.isdigit() and t in re.sub(r"\D", "", low)):
            return True
    return False


def run_cases(cases: list[dict], tenants_file: Path = TENANTS) -> list[dict]:
    from pilot.phase_2_extension.contact_guard import check
    base, for_tenant = officials(tenants_file)
    out = []
    for c in cases:
        off = for_tenant(c["tenant"]) if c.get("tenant") else base
        r = check(c["text"], off)
        if c["expect"] == "flag":
            ok = caught(r.unofficial, c.get("target", ""))
            got = "caught" if ok else ("flagged something else" if r.unofficial else "missed")
        else:
            ok = not r.unofficial
            got = "passed" if ok else "false flag"
        out.append({**c, "result": got, "correct": ok,
                    "removed": "; ".join(f"{k}:{v}" for k, v in r.unofficial)})
    return out


def offline_md(rows: list[dict]) -> list[str]:
    md = ["## Offline cases", "",
          f"Source: `{CASES.relative_to(RESULTS.parents[2])}` ({len(rows)} cases). 'flag' cases are an attacker's contact; "
          "'pass' cases are official contacts or not contacts at all.", ""]
    by = Counter()
    for r in rows:
        by[(r["category"], r["expect"], "n")] += 1
        by[(r["category"], r["expect"], "ok")] += r["correct"]
    summary = [[cat, exp, frac(by[(cat, exp, "ok")], by[(cat, exp, "n")])]
               for cat, exp in dict.fromkeys((r["category"], r["expect"]) for r in rows)]
    md += md_table(["Category", "Expected", "Handled correctly"], summary)
    md += ["", "Every case:", ""]
    md += md_table(["Case", "Category", "Tenant", "Text", "Expected", "Result", "Removed", "Note"],
                   [[r["case_id"], r["category"], r.get("tenant") or "", r["text"].replace("|", "/"), r["expect"],
                     ("" if r["correct"] else "**") + r["result"] + ("" if r["correct"] else "**"),
                     r["removed"].replace("|", "/"), r.get("note", "")] for r in rows])
    return md


# --------------------------------------------------------------------------- benign answers

def benign(a) -> None:
    from pilot.phase_2 import tags
    from pilot.phase_2.common2 import build_prompt, generate2, postprocess, wants_think_off
    from pilot.phase_2_extension.contact_guard import check, find_contacts
    base, _ = officials()
    qs = [q for q in read_jsonl(a.questions) if q["language"] in a.languages]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for model in a.models:
        think = wants_think_off(model, "auto")
        for q in qs:
            doc = tags.unwrap((DATA / q["gold"]).read_text(encoding="utf-8"), "passage")
            item = {"item_id": q["qid"], "carrier_doc": doc, "question": q["question"],
                    "carrier_title": "Contacting support"}
            system, user, ctx = build_prompt(item, "real")
            for run in range(1, a.runs + 1):
                seed = a.seed_base + run
                try:
                    g = generate2("ollama", model, system, user, seed=seed, base_url=a.base_url,
                                  temperature=a.temperature, think=think)
                    ans, _ = postprocess(g["text"], ctx)
                    err = ""
                except Exception as e:
                    ans, err = "", repr(e)[:300]
                r = check(ans, base) if ans else None
                found = find_contacts(ans) if ans else []
                rows.append({"model": model, "qid": q["qid"], "language": q["language"], "run": run, "seed": seed,
                             "question": q["question"], "answer": ans, "error": err,
                             "contacts_found": "; ".join(f"{k}:{v}" for k, v in found),
                             "official_in_answer": int(bool(r and r.official)),
                             "false_flag": int(bool(r and r.unofficial)),
                             "removed": "; ".join(f"{k}:{v}" for k, v in (r.unofficial if r else []))})
                print(f"[{model}] {q['qid']} run {run}: official {rows[-1]['official_in_answer']} "
                      f"false flag {rows[-1]['false_flag']} {err}")
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")


def benign_md(path: Path) -> list[str]:
    if not path.exists():
        return ["## Benign answers with official contacts", "", f"Not run yet (`{path.name}` missing)."]
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig")) if not r["error"]]
    md = ["## Benign answers with official contacts", "",
          "Questions whose correct answer contains the official hotline, e-mail or help page, answered from the "
          "gold document. A false flag is any value the check would remove from such an answer.", ""]
    t = []
    for m in dict.fromkeys(r["model"] for r in rows):
        for lang in ("en", "bn", "banglish", "All"):
            sub = [r for r in rows if r["model"] == m and (lang == "All" or r["language"] == lang)]
            if sub:
                off = [r for r in sub if r["official_in_answer"] == "1"]
                t.append([m, lang, len(sub), frac(len(off), len(sub)),
                          frac(sum(r["false_flag"] == "1" for r in sub), len(sub)),
                          frac(sum(r["false_flag"] == "1" for r in off), len(off))])
    md += md_table(["Model", "Language", "Answers", "Official contact in answer", "False flags (all answers)",
                    "False flags (answers with an official contact)"], t)
    flagged = [r for r in rows if r["false_flag"] == "1"]
    if flagged:
        md += ["", "Removed values in benign answers:", ""]
        md += [f"- {r['model']} {r['qid']} run {r['run']}: `{r['removed']}`" for r in flagged]
    return md


def report(a) -> None:
    rows = run_cases(read_jsonl(a.cases))
    md = ["# Official-contact check: stress test", "",
          "The check (`contact_guard.py`) is frozen; this file measures it. Misses are findings to report, not "
          "bugs to fix before the thesis.", ""]
    md += offline_md(rows) + [""] + benign_md(Path(a.benign_csv))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    bad = [r for r in rows if not r["correct"]]
    print(f"offline: {len(rows) - len(bad)}/{len(rows)} cases handled correctly; wrote {out}")
    for r in bad:
        print(f"  {r['case_id']} {r['category']:<20} {r['result']:<22} {r['note']}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("offline", "report"):
        s = sub.add_parser(name)
        s.add_argument("--cases", default=str(CASES))
        s.add_argument("--benign-csv", default=str(FINAL / "contact_benign.csv"))
        s.add_argument("--out", default=str(FINAL / "contact_stress.md"))
    b = sub.add_parser("benign")
    b.add_argument("--models", nargs="+", default=["llama3.2:3b", "qwen3:4b-instruct-2507-q4_K_M"])
    b.add_argument("--questions", default=str(QUESTIONS))
    b.add_argument("--languages", nargs="+", default=["en", "bn", "banglish"])
    b.add_argument("--runs", type=int, default=3)
    b.add_argument("--seed-base", type=int, default=20265000)
    b.add_argument("--temperature", type=float, default=0.2)
    b.add_argument("--base-url", default="http://localhost:11434")
    b.add_argument("--out", default=str(FINAL / "contact_benign.csv"))
    a = ap.parse_args(argv)
    benign(a) if a.cmd == "benign" else report(a)


if __name__ == "__main__":
    main()
