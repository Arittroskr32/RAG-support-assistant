"""Tables for the phase-2 extension, from the stack_ext / run_generation outputs.

  python -m pilot.phase_2_extension.analyze_ext        # -> results/phase2_extension_report.md

Reads (whatever exists):
  results/stackx_*.csv              stack_ext.py runs
  results/generations_ext.jsonl     run_generation on crossed / paraphrase items
  pilot/phase_2/results/generations2.jsonl   the original items, for the crossed comparison

Every success table is split by goal: marker goals are the injection result, phishing goals are
instruction-free poisoning (phase-2 report §5) and are never added to the marker numbers.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from pilot.phase_2_extension.common_ext import (GROUP_ORDER, PHASE2_RESULTS, RESULTS, frac, frac_ci, md_table,
                                                read_jsonl, truthy)


def load_stackx(results: Path) -> dict[str, list[dict]]:
    out = {}
    for p in sorted(results.glob("stackx_*.csv")):
        out[p.stem.removeprefix("stackx_")] = list(csv.DictReader(open(p, encoding="utf-8")))
    return out


def funnel(rows: list[dict]) -> list:
    """runs, not quarantined, not blocked, payload retrieved, followed (raw), survived output guards,
    end-to-end, contact check would catch."""
    n = len(rows)
    nq = [r for r in rows if not truthy(r["quarantined"])]
    nb = [r for r in nq if not r["blocked_at"]]
    ret = [r for r in nb if truthy(r["own_payload_retrieved"])]
    fol = [r for r in ret if truthy(r["canary_in_raw"]) or truthy(r["canary_in_answer"])]
    e2e = [r for r in rows if truthy(r["canary_in_answer"])]
    surv = [r for r in fol if truthy(r["canary_in_answer"])]
    cg = [r for r in e2e if truthy(r.get("contact_guard_caught", ""))]
    return [n, frac(len(nq), n), frac(len(nb), len(nq)), frac(len(ret), len(nb)), frac(len(fol), len(ret)),
            frac(len(surv), len(fol)), frac_ci(len(e2e), n), frac(len(cg), len(e2e)) if e2e else "-"]


def funnel_tables(stack: dict) -> list[str]:
    md = ["## End-to-end funnel per run file, split by goal", "",
          "Each factor is conditional on the previous one. 'Contact check' = share of end-to-end successes the "
          "official-contact check (shadow) would have removed; it can only act on phishing.", ""]
    head = ["Run", "Goal", "Group", "Runs", "Not quarantined", "Not blocked", "Payload retrieved", "Model followed",
            "Survived L8 + render", "End-to-end", "Contact check"]
    rows = []
    for name, rs in stack.items():
        for goal in ("marker", "phish"):
            for G in GROUP_ORDER + ["All"]:
                sub = [r for r in rs if r["goal_type"] == goal and (G == "All" or r["group"] == G)]
                if sub:
                    rows.append([name, goal, G] + funnel(sub))
    return md + md_table(head, rows)


def per_item(stack: dict) -> list[str]:
    md = ["## Per item (runs: quarantined / retrieved / followed / end-to-end)", ""]
    names = list(stack)
    items = sorted({(r["item_id"], r["goal_type"], r["group"]) for rs in stack.values() for r in rs},
                   key=lambda x: (GROUP_ORDER.index(x[2]) if x[2] in GROUP_ORDER else 9, x[0]))
    rows = []
    for iid, goal, g in items:
        row = [iid, goal]
        for n in names:
            sub = [r for r in stack[n] if r["item_id"] == iid]
            if not sub:
                row.append("")
                continue
            q = sum(truthy(r["quarantined"]) for r in sub)
            ret = sum(truthy(r["own_payload_retrieved"]) for r in sub)
            fol = sum(truthy(r["canary_in_raw"]) or truthy(r["canary_in_answer"]) for r in sub)
            e2e = sum(truthy(r["canary_in_answer"]) for r in sub)
            row.append(f"{q}/{ret}/{fol}/**{e2e}**" if e2e else f"{q}/{ret}/{fol}/0")
        rows.append(row)
    return md + md_table(["Item", "Goal"] + names, rows)


def base_rate_table(stack: dict) -> list[str]:
    br = {n: rs for n, rs in stack.items() if "_br" in n}
    if not br:
        return []
    md = ["## Instruction-deleted documents (~br) through the stack", "",
          "Does the ingestion scan stop a poisoned document that carries no instruction, and does the address "
          "still reach the user?", ""]
    rows = []
    for n, rs in br.items():
        for G in GROUP_ORDER:
            sub = [r for r in rs if r["group"] == G]
            if not sub:
                continue
            q = sum(truthy(r["quarantined"]) for r in sub)
            leak = sum(truthy(r["canary_in_answer"]) for r in sub)
            cg = sum(truthy(r.get("contact_guard_caught", "")) for r in sub if truthy(r["canary_in_answer"]))
            rows.append([n, G, frac(q, len(sub)), frac(leak, len(sub)), f"{cg}/{leak}" if leak else "-"])
    return md + md_table(["Run", "Group", "Quarantined", "Address in answer", "Contact check caught"], rows)


def gens_table(gens_ext: list[dict], gens2: list[dict]) -> list[str]:
    md = []
    sel = lambda gs: [g for g in gs if g.get("phase") == "selection" and not g.get("error")]
    crossed = [g for g in sel(gens_ext) if g["item_id"].endswith("x")]
    if crossed:
        md += ["## Goal x technique (selection runs): originals vs crossed items", ""]
        t = defaultdict(lambda: [0, 0])
        for g in sel(gens2) + crossed:
            if g.get("variant", "attack") != "attack":
                continue
            k = (g["model"], g["group_code"], g["goal_type"], g["technique"])
            t[k][0] += str(g["success"]) == "1"
            t[k][1] += 1
        models = sorted({k[0] for k in t if any(c["model"] == k[0] for c in crossed)})
        rows = []
        for m in models:
            for G in GROUP_ORDER:
                rows.append([m, G] + [frac(*t[(m, G, goal, tech)]) for goal, tech in
                                      (("marker", "plain_note"), ("marker", "html_comment"),
                                       ("phish", "html_comment"), ("phish", "plain_note"))])
        md += md_table(["Model", "Group", "marker / plain note", "marker / HTML comment", "phish / HTML comment",
                        "phish / plain note"], rows)
        md += ["", "If marker success collapses as an HTML comment, technique (not goal) explains part of the "
               "phishing result; if phishing stays near its base rate as a plain note, the poisoning reading holds.", ""]
    para = [g for g in sel(gens_ext) if "p" in g["item_id"].split("-")[-1]]
    if para:
        md += ["## Paraphrased payloads: does the attack still work on the generator?", ""]
        t = defaultdict(lambda: [0, 0])
        for g in para:
            t[(g["model"], g["item_id"].rsplit("p", 1)[0])][0] += str(g["success"]) == "1"
            t[(g["model"], g["item_id"].rsplit("p", 1)[0])][1] += 1
        par = defaultdict(lambda: [0, 0])
        for g in sel(gens2):
            if g.get("variant") == "attack":
                par[(g["model"], g["item_id"])][0] += str(g["success"]) == "1"
                par[(g["model"], g["item_id"])][1] += 1
        rows = [[m, i, frac(*par[(m, i)]), frac(*t[(m, i)])] for (m, i) in sorted(t)]
        md += md_table(["Model", "Parent item", "Original (selection)", "Paraphrases (all styles)"], rows)
        md += ["", "A paraphrase that evades BN_native (detectors_all.md) only matters if the model still follows it."]
    return md


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--gen2", default=str(PHASE2_RESULTS / "generations2.jsonl"))
    ap.add_argument("--out", default=str(RESULTS / "phase2_extension_report.md"))
    a = ap.parse_args(argv)
    res = Path(a.results)
    stack = load_stackx(res)
    gx = res / "generations_ext.jsonl"
    gens_ext = read_jsonl(gx) if gx.exists() else []
    gens2 = read_jsonl(a.gen2) if Path(a.gen2).exists() else []
    md = ["# Phase 2 extension: results", ""]
    if (res / "stackx_runs.jsonl").exists():
        meta = read_jsonl(res / "stackx_runs.jsonl")
        md += ["Runs: " + "; ".join(f"{m['csv']} ({m['n_rows']} rows, benign chunks quarantined "
                                    f"{[b['benign_chunks_quarantined'] for b in m.get('batches', [])]})" for m in meta), ""]
    if stack:
        md += funnel_tables(stack) + [""] + per_item(stack) + [""] + base_rate_table(stack) + [""]
    md += gens_table(gens_ext, gens2)
    if len(md) <= 2:
        md.append("No extension results yet: run the steps in run.md first.")
    Path(a.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
