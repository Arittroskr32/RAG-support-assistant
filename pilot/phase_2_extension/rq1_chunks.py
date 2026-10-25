"""RQ1 on chunks: do two working detectors on the same artifact fail together? (senior's design point)

The senior's proposal: with E5_all running on every chunk (English examples, English calibration)
and L3 on English chunks (3.9% false quarantines), there are two detectors that both work on
English documents. Their joint misses on the 80 phase-2 attack documents give the RQ1 correlation
without writing new direct-injection attacks. Direct injection becomes optional.

  python -m pilot.phase_2_extension.rq1_chunks          # reads results/detectors_long.csv

For every pair of detectors (on the documents where both ran): miss rates, phi and excess joint
miss with 95% CIs that resample SEED FAMILIES (items of one family are not independent), and
Mantel-Haenszel odds ratios stratified by language and by goal. Reported for all languages and for
English only. A detector that misses everything (or nothing) on a subset has phi undefined; that
is reported as such, not as zero correlation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pilot.phase_2_extension.common_ext import RESULTS

DEFAULT_PAIRS = [("L3", "E5_all"), ("L3", "BN_native_all"), ("E5_all", "BN_native_all"), ("L2b", "E5_all"),
                 ("L2b", "L3")]


def wide_table(long_path: Path, sets=("attack",)):
    import pandas as pd
    df = pd.read_csv(long_path)
    df = df[df["set"].isin(sets) & (df["applicable"] == 1)].copy()
    df["miss"] = pd.to_numeric(df["miss"]).astype(int)
    wide = df.pivot_table(index=["doc_id", "seed_family", "language", "goal_type", "technique"],
                          columns="detector", values="miss", aggfunc="first").reset_index()
    wide.columns.name = None
    return wide


def pair_rows(wide, pairs, n_boot: int) -> list[dict]:
    import numpy as np

    from eval.eval_stats import cmh, pairwise_table
    rows = []
    for j, k in pairs:
        if j not in wide or k not in wide:
            rows.append({"pair": f"{j} x {k}", "n": 0, "note": "detector not in the run"})
            continue
        sub = wide.dropna(subset=[j, k]).copy()
        if len(sub) < 3:
            rows.append({"pair": f"{j} x {k}", "n": len(sub), "note": "too few documents"})
            continue
        sub[j], sub[k] = sub[j].astype(int), sub[k].astype(int)
        pt = pairwise_table(sub, [j, k], n_boot=n_boot).iloc[0]
        both = int(((sub[j] == 1) & (sub[k] == 1)).sum())
        r = {"pair": f"{j} x {k}", "n": len(sub), "families": sub.seed_family.nunique(),
             "miss_j": pt.miss_j, "miss_k": pt.miss_k, "both_miss": both,
             "expected_both": pt.miss_j * pt.miss_k * len(sub),
             "phi": pt.phi, "phi_lo": pt.phi_lo, "phi_hi": pt.phi_hi,
             "excess": pt.excess, "excess_lo": pt.excess_lo, "excess_hi": pt.excess_hi, "note": ""}
        for strat in ("language", "goal_type"):
            try:
                c = cmh(sub, j, k, strat)
                r[f"cmh_{strat}"] = "-" if not np.isfinite(c["or_mh"]) else f"{c['or_mh']:.2f} (p {c['p']:.3f})"
            except Exception as e:          # statsmodels missing, or a degenerate stratum
                r[f"cmh_{strat}"] = f"- ({type(e).__name__})"
        if not np.isfinite(pt.phi):
            r["note"] = "phi undefined: a detector never or always misses here"
        rows.append(r)
    return rows


def fmt(rows) -> list[str]:
    md = ["| Pair | n docs (families) | miss j | miss k | both miss (expected if independent) | phi [95% CI] | "
          "excess joint miss [95% CI] | CMH OR by language | CMH OR by goal | note |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "phi" not in r:
            md.append(f"| {r['pair']} | {r['n']} | | | | | | | | {r['note']} |")
            continue
        md.append(f"| {r['pair']} | {r['n']} ({r['families']}) | {r['miss_j']:.2f} | {r['miss_k']:.2f} | "
                  f"{r['both_miss']} ({r['expected_both']:.1f}) | {r['phi']:.2f} [{r['phi_lo']:.2f}, {r['phi_hi']:.2f}] | "
                  f"{r['excess']:.3f} [{r['excess_lo']:.3f}, {r['excess_hi']:.3f}] | {r.get('cmh_language', '-')} | "
                  f"{r.get('cmh_goal_type', '-')} | {r['note']} |")
    return md


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--long", default=str(RESULTS / "detectors_long.csv"))
    ap.add_argument("--sets", nargs="+", default=["attack"],
                    help="document sets to pair (default: the 80 attack docs; add crossed for more power, "
                         "but crossed docs share families with the originals)")
    ap.add_argument("--pairs", nargs="*", default=None, help="e.g. L3:E5_all L2b:E5_all")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--out", default=str(RESULTS / "rq1_chunks.md"))
    a = ap.parse_args(argv)
    p = Path(a.long)
    if not p.exists():
        raise SystemExit(f"missing {p}: run `python -m pilot.phase_2_extension.detectors_all --with-l3` first")
    pairs = [tuple(x.split(":")) for x in a.pairs] if a.pairs else DEFAULT_PAIRS
    wide = wide_table(p, tuple(a.sets))
    md = ["# RQ1 on chunks: failure correlation of chunk detectors", "",
          f"Source: `{p.name}`, sets {', '.join(a.sets)}. Miss = the document was not flagged at the calibrated "
          "threshold. CIs resample seed families.", ""]
    for title, sub in (("All languages", wide), ("English documents only", wide[wide.language == "en"])):
        md += [f"## {title}", ""] + fmt(pair_rows(sub, pairs, a.n_boot)) + [""]
    md += ["Reading guide: phi > 0 with a CI above 0 means the two detectors tend to miss the SAME documents "
           "(less protection from stacking them than their separate miss rates suggest). Compare a same-artifact "
           "pair here with the cross-artifact pairs (a chunk detector x L8/contact check on answers) from the "
           "stack runs before claiming that different artifacts fail more independently."]
    Path(a.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
