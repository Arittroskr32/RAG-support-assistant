"""Tables for the final runs (final_run.md): the paraphrase study, the joined-carrier stack runs and the
frontier model on Table 4. Reads whatever exists, so it can be run after every step.

  python -m pilot.phase_2_extension.analyze_final        # -> results/final/final_tables.md

Reads
  results/final/generations_final.jsonl          run_generation on the human paraphrases and table4 items
  results/final/paraphrase_human_items.jsonl     make_items_ext human (payloads, styles, families)
  results/generations_ext*.jsonl                 the AI-drafted paraphrases (for comparison only)
  pilot/phase_2/results/generations2.jsonl       the original items (Table 4 for 3B, 8B and Qwen)
  results/stackx_*joined*.csv (+ the as-is runs they are compared with)
Success is the canary, as everywhere; only hand-checked hits ("ok") count once checking is done, and
the hand-check table says how many hits are still open.
"""
from __future__ import annotations

import argparse
import difflib
import json
from collections import defaultdict
from math import comb
from pathlib import Path

from pilot.phase_2_extension.common_ext import GROUP_ORDER, PHASE2_RESULTS, RESULTS, frac, frac_ci, md_table, read_jsonl

FINAL = RESULTS / "final"


def load(path: Path) -> list[dict]:
    return read_jsonl(path) if Path(path).exists() else []


def ok(g: dict) -> bool:
    """A success that survived the hand check (an unchecked hit still counts, and is listed as open)."""
    return str(g.get("success")) == "1" and g.get("manual_check", "") in ("", "ok", "missed_hit")


def sign_test(pos: int, neg: int) -> float:
    """Exact two-sided sign test (ties dropped)."""
    n = pos + neg
    if not n:
        return float("nan")
    k = min(pos, neg)
    p = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return min(1.0, p)


def hit_kind(answer: str, payload: str, code_core: str) -> str:
    """'end' = the code closes the answer (what the marker instruction asks); 'echo' = the answer copies
    most of the payload sentence; 'other' = the code appears elsewhere. Heuristic, for the caveat only."""
    a = (answer or "").strip()
    m = difflib.SequenceMatcher(None, a, payload).find_longest_match(0, len(a), 0, len(payload))
    if payload and m.size >= 0.6 * len(payload):
        return "echo"
    return "end" if code_core in a[-60:] else "other"


# --------------------------------------------------------------------------- hand check

def handcheck_table(files: dict[str, list[dict]]) -> list[str]:
    rows = []
    for name, gs in files.items():
        hits = [g for g in gs if str(g.get("success")) == "1"]
        if not gs:
            continue
        open_ = [g for g in hits if not g.get("manual_check")]
        rows.append([name, len(gs), len(hits), sum(g.get("manual_check") == "ok" for g in hits),
                     sum(g.get("manual_check") == "refusal_quote" for g in hits), len(open_),
                     ", ".join(sorted({f"{g['item_id']} ({g['model'][:6]} r{g['run']})" for g in open_}))[:300]])
    return ["## Hand-check status", ""] + md_table(
        ["File", "Generations", "Automatic hits", "ok", "refusal quote", "Still open", "Open hits"], rows)


# --------------------------------------------------------------------------- paraphrase study

def paraphrase_tables(final: list[dict], gens2: list[dict], ai: list[dict], items: list[dict]) -> list[str]:
    human = [g for g in final if g["item_id"].rsplit("-", 1)[-1][3:4] == "h" and not g.get("error")]
    if not human:
        return ["## Paraphrase study", "", "No human-paraphrase generations yet (final_run.md, step 1)."]
    meta = {i["item_id"]: i for i in items}
    parent = lambda iid: iid.rsplit("h", 1)[0]
    fams = {meta[g["item_id"]]["seed_family"] for g in human if g["item_id"] in meta}
    models = list(dict.fromkeys(g["model"] for g in human))
    sel = lambda gs, ph="selection": [g for g in gs if g.get("phase") == ph and not g.get("error")
                                      and g.get("config", "real") == "real"]
    orig_pool = sel(gens2) + sel(final)
    orig = [g for g in orig_pool if g.get("variant", "attack") == "attack" and g.get("seed_family") in fams
            and g["goal_type"] == "marker" and "h" not in g["item_id"].split("-")[-1]]
    pc = [g for g in orig_pool if g.get("variant") == "positive_control" and g.get("seed_family") in fams]
    ai_core = [g for g in ai if not g.get("error") and g.get("seed_family") in fams and "p" in g["item_id"].split("-")[-1]]

    def cell(gs, m, G, extra=lambda g: True):
        sub = [g for g in gs if g["model"] == m and g["group_code"] == G and extra(g)]
        return frac_ci(sum(ok(g) for g in sub), len(sub)) if sub else "-"

    md = ["## Paraphrase study: template vs paraphrase", "",
          f"Families: {', '.join(sorted(fams))}. Originals = the phase-2 'note to the AI assistant' template, selection "
          "seeds. User asks = the same instruction as the user's request (positive control). Human paraphrases: "
          "selection seeds (same as the originals) and measurement seeds (fresh, an independent repeat). AI drafts: "
          "the earlier `generations_ext*.jsonl` runs, shown for comparison only.", ""]
    rows = []
    for m in models:
        for G in GROUP_ORDER:
            rows.append([m, G, cell(orig, m, G), cell(pc, m, G), cell(sel(human), m, G),
                         cell(sel(human, "measurement"), m, G), cell(sel(ai_core), m, G)])
    md += md_table(["Model", "Group", "Original template (document)", "User asks", "Human paraphrase (selection)",
                    "Human paraphrase (measurement)", "AI draft (both runs)"], rows)

    md += ["", "**By style** (human paraphrases, selection + measurement runs):", ""]
    rows = []
    for m in models:
        for style in ("policy", "content", "reworded"):
            sub = [g for g in human if g["model"] == m and meta.get(g["item_id"], {}).get("paraphrase_style") == style]
            rows.append([m, style] + [cell(sub, m, G) for G in GROUP_ORDER])
    md += md_table(["Model", "Style"] + GROUP_ORDER, rows)

    md += ["", "**Core vs extension families** (human paraphrases, selection runs):", ""]
    rows = []
    for m in models:
        for fs in ("core", "extension"):
            sub = [g for g in sel(human) if g["model"] == m and meta.get(g["item_id"], {}).get("family_set") == fs]
            if sub:
                rows.append([m, fs] + [cell(sub, m, G) for G in GROUP_ORDER])
    md += md_table(["Model", "Families"] + GROUP_ORDER, rows)

    # paired by family x group: is the paraphrase rate above the template rate?
    md += ["", "**Paired test** (selection runs): each family x group cell compares the paraphrases' success rate with "
           "the original's. Exact two-sided sign test over cells, ties dropped.", ""]
    rows = []
    for m in models:
        for Gs in (["EN"], ["TR", "BL", "NT"], ["TR"]):
            pos = neg = tie = 0
            for fam in sorted(fams):
                for G in Gs:
                    o = [g for g in orig if g["model"] == m and g["seed_family"] == fam and g["group_code"] == G]
                    h = [g for g in sel(human) if g["model"] == m and g["seed_family"] == fam and g["group_code"] == G]
                    if not o or not h:
                        continue
                    d = sum(map(ok, h)) / len(h) - sum(map(ok, o)) / len(o)
                    pos, neg, tie = pos + (d > 0), neg + (d < 0), tie + (d == 0)
            rows.append([m, "+".join(Gs), pos, neg, tie, f"{sign_test(pos, neg):.4f}" if pos + neg else "-"])
    md += md_table(["Model", "Groups", "Paraphrase higher", "Original higher", "Tie", "Sign test p"], rows)

    md += ["", "**What a paraphrase hit looks like** (heuristic: 'end' = the code closes the answer, as the instruction "
           "asks; 'echo' = the answer copies most of the payload sentence, close to summarising the document):", ""]
    rows = []
    for m in models:
        for G in GROUP_ORDER:
            hits = [g for g in human if g["model"] == m and g["group_code"] == G and ok(g) and g["item_id"] in meta]
            if hits:
                k = defaultdict(int)
                for g in hits:
                    it = meta[g["item_id"]]
                    k[hit_kind(g["answer"], it["payload"], str(it["canary_core"]))] += 1
                rows.append([m, G, len(hits), k["end"], k["echo"], k["other"]])
    md += md_table(["Model", "Group", "Hits", "Code at the end", "Echo of the payload", "Other"], rows)
    return md


# --------------------------------------------------------------------------- frontier model, Table 4

def table4(final: list[dict], gens2: list[dict]) -> list[str]:
    t4 = [g for g in final if g.get("phase") == "selection" and not g.get("error") and g["goal_type"] == "marker"
          and "h" not in g["item_id"].split("-")[-1]]
    if not t4:
        return ["## Table 4 for new models", "", "No table4 runs yet (final_run.md, step 4)."]
    md = ["## Table 4 for new models (marker goals, selection runs: document vs user asks)", ""]
    rows = []
    for m in dict.fromkeys(g["model"] for g in t4):
        sub = [g for g in t4 if g["model"] == m]
        versions = sorted({g.get("model_returned") or "" for g in sub} - {""})
        dates = sorted({(g.get("time") or "")[:10] for g in sub} - {""})
        for G in GROUP_ORDER:
            doc = [g for g in sub if g["group_code"] == G and g["variant"] == "attack"]
            pc = [g for g in sub if g["group_code"] == G and g["variant"] == "positive_control"]
            rows.append([m, ", ".join(versions) or "-", " to ".join([dates[0], dates[-1]]) if dates else "-", G,
                         frac_ci(sum(map(ok, doc)), len(doc)), frac_ci(sum(map(ok, pc)), len(pc))])
    md += md_table(["Model", "Version returned by the API", "Run dates", "Group", "Document", "User asks"], rows)
    return md


# --------------------------------------------------------------------------- joined-carrier stack

def joined_tables(results: Path) -> list[str]:
    from pilot.phase_2_extension.analyze_ext import funnel_tables, load_stackx, per_item
    stack = load_stackx(results)
    joined = {n: rs for n, rs in stack.items() if "_joined" in n}
    if not joined:
        return ["## Stack with joined carriers", "", "No joined-carrier runs yet (final_run.md, step 2)."]
    base = {n.replace("_joined", ""): None for n in joined}
    compare = {n: rs for n, rs in stack.items() if n in base or n in joined}
    md = ["## Stack with joined carriers (payload inside its paragraph) vs as-is (payload its own chunk)", ""]
    meta = load(results / "stackx_runs.jsonl")
    rows = []
    for m in meta:
        if m.get("carrier") == "joined":
            counts = [n for b in m.get("batches", []) for n in (b.get("chunks_per_planted_doc") or {}).values()]
            rows.append([m["csv"], len(counts), sum(c == 1 for c in counts),
                         [b["benign_chunks_quarantined"] for b in m.get("batches", [])]])
    if rows:
        md += md_table(["Run", "Planted documents", "Kept as one chunk", "Benign chunks quarantined"], rows) + [""]
    return md + funnel_tables(compare) + [""] + per_item(compare)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--gen2", default=str(PHASE2_RESULTS / "generations2.jsonl"))
    ap.add_argument("--out", default=str(FINAL / "final_tables.md"))
    a = ap.parse_args(argv)
    res = Path(a.results)
    final = load(res / "final" / "generations_final.jsonl")
    gens2 = load(Path(a.gen2))
    ai = load(res / "generations_ext.jsonl") + load(res / "generations_ext2.jsonl")
    items = load(res / "final" / "paraphrase_human_items.jsonl")
    md = ["# Final runs: tables", ""]
    md += handcheck_table({"final/generations_final.jsonl": final, "generations_ext.jsonl": load(res / "generations_ext.jsonl"),
                           "generations_ext2.jsonl": load(res / "generations_ext2.jsonl")}) + [""]
    md += paraphrase_tables(final, gens2, ai, items) + [""]
    md += joined_tables(res) + [""]
    md += table4(final, gens2) + [""]
    md += ["Contact check stress test: `results/final/contact_stress.md` (contact_stress.py)."]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
