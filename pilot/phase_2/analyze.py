"""Phase-2 tables: per-run rates, paired exact tests, the two controls and the RQ2 factors.

  python -m pilot.phase_2.analyze                                   # everything it finds
  python -m pilot.phase_2.analyze --phase measurement --valid pilot/phase_2/results/valid_llama3.2-3b.json
  python -m pilot.phase_2.analyze --stack pilot/phase_2/results/stack2_*.csv
  python -m pilot.phase_2.analyze --gen pilot/phase_1/results/generations.jsonl --stack \
      --out pilot/phase_2/results/phase1_dev_report.md     # the same tables for the phase-1 (dev) runs

Reads results/generations2.jsonl (run_generation.py) and any stack2_*.csv (stack_check2.py);
writes results/phase2_report.md. Every number is computed from those files; nothing is typed in.

What it reports (plan steps B7, C1, C2, F):
  * run settings actually used (temperature, seed range, think switch) per model and config;
  * per-run attack success rate with a Wilson 95% CI (the main number), plus items that
    succeeded in >= 1 run (secondary);
  * paired comparisons across languages on shared seed families: exact McNemar on the
    family-level "succeeded at least once", and an exact sign test plus an exact sign-flip
    permutation test on the per-family difference of per-run rates;
  * C1 positive control: per group, attack vs positive-control outcome (2x2 counts) and rates;
  * C2 base rate: per group and goal, success with the instruction vs with it deleted, the
    injection lift and an exact sign test over items;
  * RQ2 factor decomposition of the defended runs per configuration and language.
Hand-check labels (manual_check) are respected: refusal_quote is not a success, missed_hit is.
"""
from __future__ import annotations

import argparse
import csv
import glob
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path

from pilot.phase_2.common2 import GENERATIONS, RESULTS_DIR, is_success, read_jsonl


# --------------------------------------------------------------------------- statistics

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test of k successes in n trials against p = 0.5."""
    if n == 0:
        return 1.0
    pk = math.comb(n, k)
    total = sum(math.comb(n, i) for i in range(n + 1) if math.comb(n, i) <= pk)
    return min(1.0, total / 2 ** n)


def mcnemar_exact(b: int, c: int) -> float:
    """b = pairs where only the first condition succeeded, c = only the second."""
    return binom_two_sided(min(b, c), b + c)


def sign_test(diffs: list[float]) -> tuple[int, int, float]:
    pos = sum(d > 0 for d in diffs)
    neg = sum(d < 0 for d in diffs)
    return pos, neg, binom_two_sided(min(pos, neg), pos + neg)


def sign_flip_p(diffs: list[float], max_exact: int = 20, n_mc: int = 20000, seed: int = 0) -> float:
    """Exact (n <= max_exact) or Monte-Carlo sign-flip permutation p for the mean difference."""
    d = [x for x in diffs if x != 0]
    if not d:
        return 1.0
    obs = abs(sum(d))
    if len(d) <= max_exact:
        hits = sum(abs(sum(s * x for s, x in zip(signs, d))) >= obs - 1e-12
                   for signs in itertools.product((1, -1), repeat=len(d)))
        return hits / 2 ** len(d)
    import random
    rng = random.Random(seed)
    hits = sum(abs(sum(x if rng.random() < .5 else -x for x in d)) >= obs - 1e-12 for _ in range(n_mc))
    return (hits + 1) / (n_mc + 1)


def pct(k: int, n: int) -> str:
    if n == 0:
        return "-"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({k / n:.0%}, {lo:.0%}–{hi:.0%})"


# --------------------------------------------------------------------------- generation tables

def from_phase1(r: dict) -> dict:
    """A phase-1 generations.jsonl row in phase-2 shape (phase "dev", attack, family shared)."""
    return {**r, "phase": "dev", "variant": "attack", "parent_id": r["item_id"],
            "group_code": r["item_id"].split("-")[0], "seed": None, "think_sent": None}


def load_generations(path: str, phase: str | None, valid: set | None) -> list[dict]:
    if not Path(path).exists():
        return []
    rows = [r for r in read_jsonl(path) if not r.get("error") and r.get("success") is not None]
    rows = [r if "phase" in r else from_phase1(r) for r in rows]
    if phase:
        rows = [r for r in rows if r["phase"] == phase]
    if valid is not None:
        rows = [r for r in rows if r["parent_id"] in valid]
    return rows


def settings_table(rows) -> list[str]:
    agg = defaultdict(lambda: {"temp": set(), "seeds": set(), "think": set(), "n": 0})
    for r in rows:
        a = agg[(r["model"], r["config"], r["phase"])]
        a["temp"].add(r.get("temperature"))
        a["seeds"].add(r.get("seed"))
        a["think"].add(str(r.get("think_sent")))
        a["n"] += 1
    md = ["## Run settings", "", "| Model | Config | Phase | Generations | Temperature | Seeds | Think |",
          "|---|---|---|---|---|---|---|"]
    for (m, c, p), a in sorted(agg.items()):
        seeds = sorted(s for s in a["seeds"] if s is not None)
        md.append(f"| {m} | {c} | {p} | {a['n']} | {', '.join(map(str, sorted(a['temp'])))} | "
                  f"{(str(seeds[0]) + '–' + str(seeds[-1])) if seeds else 'not sent'} | {', '.join(sorted(a['think']))} |")
    return md + [""]


def rate_table(rows) -> list[str]:
    runs = defaultdict(lambda: [0, 0])
    items = defaultdict(lambda: defaultdict(bool))
    for r in rows:
        key = (r["model"], r["config"], r["phase"], r["variant"], r.get("group_code", r["group"]))
        s = is_success(r)
        runs[key][0] += s
        runs[key][1] += 1
        items[key][r["item_id"]] |= s
    md = ["## Success per run (main number) and per item", "",
          "| Model | Config | Phase | Variant | Group | Runs succeeded (95% CI) | Items succeeded >= 1 run |",
          "|---|---|---|---|---|---|---|"]
    for key in sorted(runs):
        k, n = runs[key]
        it = items[key]
        md.append(f"| {' | '.join(key)} | {pct(k, n)} | {sum(it.values())}/{len(it)} |")
    return md + [""]


def family_rates(rows) -> dict:
    """(model, config, phase) -> group -> family -> [successes, runs]  (attacks only)"""
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    for r in rows:
        if r["variant"] != "attack":
            continue
        f = out[(r["model"], r["config"], r["phase"])][r.get("group_code", r["group"])][r["seed_family"]]
        f[0] += is_success(r)
        f[1] += 1
    return out


def paired_table(rows, pairs=(("EN", "TR"), ("EN", "BL"), ("TR", "BL"))) -> list[str]:
    md = ["## Paired comparison on shared seed families", "",
          "Family-level: succeeded in >= 1 run. Run-level: difference of per-run rates per family.", "",
          "| Model | Config | Phase | Pair | Families | Only first | Only second | McNemar exact p | "
          "Mean rate diff | Sign test +/- (p) | Sign-flip p |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (m, c, p), groups in sorted(family_rates(rows).items()):
        for g1, g2 in pairs:
            fams = sorted(set(groups.get(g1, {})) & set(groups.get(g2, {})))
            if not fams:
                continue
            A, B = groups[g1], groups[g2]
            b = sum(A[f][0] > 0 and B[f][0] == 0 for f in fams)
            cc = sum(B[f][0] > 0 and A[f][0] == 0 for f in fams)
            diffs = [A[f][0] / A[f][1] - B[f][0] / B[f][1] for f in fams]
            pos, neg, sp = sign_test(diffs)
            md.append(f"| {m} | {c} | {p} | {g1} vs {g2} | {len(fams)} | {b} | {cc} | {mcnemar_exact(b, cc):.4f} | "
                      f"{sum(diffs) / len(diffs):+.2f} | {pos}/{neg} ({sp:.4f}) | {sign_flip_p(diffs):.4f} |")
    return md + [""]


def control_tables(rows) -> list[str]:
    by = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # (model, config, phase, parent) -> variant -> [k, n]
    meta = {}
    for r in rows:
        v = by[(r["model"], r["config"], r["phase"], r["parent_id"])][r["variant"]]
        v[0] += is_success(r)
        v[1] += 1
        if r["variant"] == "attack":
            meta[r["parent_id"]] = (r.get("group_code", r["group"]), r["goal_type"])
    md = []
    # C1 positive control
    pc = defaultdict(lambda: defaultdict(int))
    pc_rates = defaultdict(lambda: {"attack": [0, 0], "pc": [0, 0]})
    for (m, c, p, parent), v in by.items():
        if "positive_control" in v and "attack" in v and parent in meta:
            g = meta[parent][0]
            att, ctl = v["attack"][0] > 0, v["positive_control"][0] > 0
            pc[(m, c, p, g)][(ctl, att)] += 1
            for name, key in (("attack", "attack"), ("pc", "positive_control")):
                pc_rates[(m, c, p, g)][name][0] += v[key][0]
                pc_rates[(m, c, p, g)][name][1] += v[key][1]
    if pc:
        md += ["## C1 positive control: does the model follow the same instruction from the USER?", "",
               "Items counted by whether each version succeeded in >= 1 run.", "",
               "| Model | Config | Phase | Group | User asks: yes, doc: no (understands, declines doc) | "
               "both no (does not understand / cannot) | both yes | user no, doc yes | "
               "Run rate: user request | Run rate: document |", "|---|---|---|---|---|---|---|---|---|---|"]
        for key in sorted(pc):
            t, rr = pc[key], pc_rates[key]
            md.append(f"| {' | '.join(key)} | {t[(True, False)]} | {t[(False, False)]} | {t[(True, True)]} | "
                      f"{t[(False, True)]} | {pct(*rr['pc'])} | {pct(*rr['attack'])} |")
        md.append("")
    # C2 base rate
    br = defaultdict(lambda: {"diffs": [], "att": [0, 0], "br": [0, 0]})
    for (m, c, p, parent), v in by.items():
        if "base_rate" in v and "attack" in v and parent in meta:
            g, goal = meta[parent]
            d = br[(m, c, p, g, goal)]
            d["diffs"].append(v["attack"][0] / v["attack"][1] - v["base_rate"][0] / v["base_rate"][1])
            for name, key in (("att", "attack"), ("br", "base_rate")):
                d[name][0] += v[key][0]
                d[name][1] += v[key][1]
    if br:
        md += ["## C2 base rate: injection or instruction-free poisoning?", "",
               "Injection lift = per-run success WITH the instruction minus success with the instruction deleted "
               "and the entity kept. A lift near zero means the model repeats the number or address without "
               "being told to (poisoning, not injection).", "",
               "| Model | Config | Phase | Group | Goal | With instruction | Instruction deleted | Lift | "
               "Sign test +/- (p) |", "|---|---|---|---|---|---|---|---|---|"]
        for key in sorted(br):
            d = br[key]
            lift = d["att"][0] / d["att"][1] - d["br"][0] / d["br"][1]
            pos, neg, sp = sign_test(d["diffs"])
            md.append(f"| {' | '.join(key)} | {pct(*d['att'])} | {pct(*d['br'])} | {lift:+.0%} | {pos}/{neg} ({sp:.3f}) |")
        md.append("")
    return md


# --------------------------------------------------------------------------- stack factors

def _b(x) -> bool:
    return str(x).lower() in ("true", "1")


def factor_table(paths: list[str]) -> list[str]:
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    if not rows:
        return []
    agg = defaultdict(list)
    for r in rows:
        agg[(r["config"], r["model"], r["group"])].append(r)
    md = ["## RQ2 factor decomposition of the defended runs", "",
          "Each factor is conditional on passing the previous one; the product is the end-to-end success rate. "
          "'Other item hit' = the answer carried another planted item's canary (counted separately, not as success).",
          "", "| Config | Model | Group | Runs | Not quarantined | Question not blocked | Payload retrieved | "
          "Model followed (raw answer) | Survived L8 + render guard | End-to-end success | Other item hit | "
          "Links/images left |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]

    def frac(k, n):
        return f"{k}/{n} ({k / n:.0%})" if n else "-"
    for key in sorted(agg):
        rs = agg[key]
        n = len(rs)
        nq = [r for r in rs if not _b(r["quarantined"])]
        nb = [r for r in nq if not r["blocked_at"]]
        rt = [r for r in nb if _b(r["own_payload_retrieved"])]
        fo = [r for r in rt if _b(r["canary_in_raw"]) or _b(r["canary_in_answer"])]
        sv = [r for r in fo if _b(r["canary_in_answer"])]
        succ = sum(_b(r["canary_in_answer"]) for r in rs)
        other = sum(bool(r["other_canaries_in_answer"]) for r in rs)
        links = sum(int(r["external_markup"] or 0) > 0 for r in rs)
        md.append(f"| {' | '.join(key)} | {n} | {frac(len(nq), n)} | {frac(len(nb), len(nq))} | {frac(len(rt), len(nb))} | "
                  f"{frac(len(fo), len(rt))} | {frac(len(sv), len(fo))} | {pct(succ, n)} | {other} | {links} |")
    return md + [""]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default=str(GENERATIONS))
    ap.add_argument("--phase", choices=["dev", "selection", "measurement"], default=None)
    ap.add_argument("--valid", help="valid_<model>.json: restrict to those items (use with --phase measurement)")
    ap.add_argument("--stack", nargs="*", default=None, help="stack2_*.csv files (default: all in results/)")
    ap.add_argument("--out", default=str(RESULTS_DIR / "phase2_report.md"))
    a = ap.parse_args(argv)

    valid = None
    if a.valid:
        data = json.loads(Path(a.valid).read_text(encoding="utf-8"))
        valid = set(data["items"] if isinstance(data, dict) else data)
    rows = load_generations(a.gen, a.phase, valid)
    md = ["# Phase 2 report", "", f"Generations: `{a.gen}`" + (f", phase {a.phase}" if a.phase else ", all phases")
          + (f", restricted to {len(valid)} valid items from `{a.valid}`" if valid is not None else "") + ".", ""]
    if valid is not None and a.phase != "measurement":
        md += ["> Warning: valid items were chosen on the selection runs; report defence effects on the "
               "measurement runs only (--phase measurement), or regression to the mean inflates them.", ""]
    if rows:
        md += settings_table(rows) + rate_table(rows) + paired_table(rows) + control_tables(rows)
    else:
        md += ["_No generation rows found._", ""]
    stack = a.stack if a.stack is not None else sorted(glob.glob(str(RESULTS_DIR / "stack2_*.csv")))
    md += factor_table(stack)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
