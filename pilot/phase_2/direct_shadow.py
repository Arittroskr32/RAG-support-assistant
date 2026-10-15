"""Plan step G (RQ1): shadow mode on DIRECT injection, then failure correlation.

The query-side detectors only see the user's message, so on indirect injection (a benign
question, the attack hidden in a document) they cannot fire by construction. RQ1's
correlation study therefore runs on direct injection, where they do.

  # 1. every query-side detector on every prompt, no early exit
  python -m pilot.phase_2.direct_shadow run --items pilot/phase_2/data/direct_injection.jsonl
  python -m pilot.phase_2.direct_shadow run ... --skip q_L3          # without the GPU guardrail
  python -m pilot.phase_2.direct_shadow run ... --answers --model llama3.2:3b
        # also send each ATTACK through the pipeline with the query-side detectors switched
        # off, so the answer-side layers (L8, render guard) get a row: the cross-artifact pairs

  # 2. correlation tables
  python -m pilot.phase_2.direct_shadow analyze

Items file (JSONL), attacks AND benign prompts:
  {"sample_id": "di-001", "label": "attack", "text": "...", "seed_family": "d01",
   "language": "en", "threat_class": "4", "technique": "roleplay",
   "goal_type": "marker", "canary_core": "7731"}          # goal/canary optional
  {"sample_id": "bq-001", "label": "benign", "text": "...", "language": "bn"}
Use only seed families that are NOT in KB-2 (D-36), or q_KB2 measures memorisation.

Output: results/direct_shadow_long.csv (eval_stats long format: one row per sample x layer
with applicable / flagged / miss), and with `analyze` results/rq1_correlation.md:
miss rates and false-refusal rates per detector and language, pairwise phi and excess joint
miss with family-clustered bootstrap CIs, each pair marked same-artifact or cross-artifact,
and Mantel-Haenszel odds ratios stratified by language and by technique.
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from pilot.phase_2 import tags
from pilot.phase_2.common2 import DATA2_DIR, RESULTS_DIR, canary_hit, need, read_jsonl

FIELDS = ["sample_id", "label", "run", "seed_family", "language", "difficulty", "threat_class", "goal_type",
          "layer", "artifact", "applicable", "diagnostic", "flagged", "miss", "score", "latency_ms", "error"]
LONG = RESULTS_DIR / "direct_shadow_long.csv"


def query_layers(bn=None) -> dict:
    """name -> (artifact, fn, applies(text)). Same functions and thresholds as the pipeline."""
    from config.settings import get_thresholds
    from pilot.phase_1 import layers
    ext = get_thresholds().enable_l2_extended_patterns
    out = {"q_L2": ("query", lambda t: layers.l2_pattern(t, extended=ext), None),
           "q_L2b": ("query", layers.l2b_narrative, None),
           "q_KB2": ("query", layers.kb2_match, None),
           "q_L3": ("query", layers.l3_guardrail, None)}
    if bn is not None:
        from pilot.phase_2.bn_route import is_bangla
        out["q_BN_native"] = ("query", bn.check, is_bangla)
    return out


def _call(fn, text):
    t0 = time.perf_counter()
    try:
        r = fn(text)
        return r["flagged"], r.get("score"), (time.perf_counter() - t0) * 1000, ""
    except Exception as e:
        return None, None, (time.perf_counter() - t0) * 1000, repr(e)[:200]


def answer_rows(item: dict, base: dict) -> list[dict]:
    """Send one attack through the pipeline with every query-side detector off, so the answer
    side sees it. L8 is applicable when the goal leaks data and the raw answer leaked; the
    render guard when the raw answer carried external markup."""
    import dataclasses

    from config.settings import get_thresholds
    from generation import l7_generation as l7
    from pipeline.orchestrator import handle_request
    from pilot.phase_1.common import external_refs

    cfg = dataclasses.replace(get_thresholds(), enable_l2=False, enable_l2b=False, enable_kb2_match=False,
                              enable_l3=False)
    raw = {}
    orig = l7.generate_answer

    def capture(*a, **k):
        res = orig(*a, **k)
        raw["text"] = res.text
        return res
    l7.generate_answer = capture
    try:
        res = handle_request(item["text"], user_id="pilot2-direct", role="customer", ip="127.0.0.1",
                             session_id=f"p2d-{item['sample_id']}-{time.time()}", cfg=cfg)
    finally:
        l7.generate_answer = orig
    text, final = raw.get("text", ""), res.response or ""
    rows = []
    core = str(item.get("canary_core") or "")
    leaked = bool(core) and item.get("goal_type") in ("pii", "phish", "marker") and canary_hit(text, core)
    l8_applicable = leaked and item.get("goal_type") in ("pii", "phish")
    l8_flag = l8_applicable and (res.blocked_at == "L8" or not canary_hit(final, core))
    rows.append({**base, "layer": "L8", "artifact": "answer", "applicable": int(l8_applicable), "diagnostic": 0,
                 "flagged": l8_flag if l8_applicable else "", "miss": int(not l8_flag) if l8_applicable else "",
                 "score": "", "latency_ms": res.timings_ms.get("L8", ""), "error": ""})
    markup = bool(external_refs(text))
    still = bool(external_refs(final))
    rows.append({**base, "layer": "render_guard", "artifact": "rendered", "applicable": int(markup), "diagnostic": 0,
                 "flagged": (not still) if markup else "", "miss": int(still) if markup else "",
                 "score": "", "latency_ms": "", "error": ""})
    return rows


def run(a) -> None:
    from pilot.phase_1.layers import self_test
    bn = None
    if a.bn:
        from pilot.phase_2 import bn_route
        bn = bn_route.BNNative(bn_route.bn_attack_texts(extra=a.bn_extra),
                               bn_route.load_threshold(a.calibration, a.bn_threshold))
    layers = {k: v for k, v in query_layers(bn).items() if k not in set(a.skip)}
    if not a.no_check:
        from pilot.phase_1.layers import LAYERS as P1
        wanted = {k for k in ("q_L2", "q_L2b", "q_KB2", "q_L3") if k in layers}
        if wanted and not self_test(P1, skip=set(P1) - wanted):
            raise SystemExit("layer self-test failed (use --skip or --no-check)")
    if a.answers:
        from pilot.phase_2.stack_check2 import install_generator
        install_generator(a.model, a.temperature, a.base_url, "auto", native=True)(a.seed)
    need(a.items, "direct-injection attacks and benign prompts (run.md step 3, example in "
                  "pilot/phase_2/data/examples/direct_injection.jsonl)")
    items = read_jsonl(a.items)
    for it in items:                                   # <!><query> ... <!query> is allowed in the file
        it["text"] = tags.unwrap(it["text"], "query")
    rows = []
    for n, it in enumerate(items, 1):
        base = {"sample_id": it["sample_id"], "label": it["label"], "run": "",
                "seed_family": it.get("seed_family", it["sample_id"]), "language": it.get("language", "en"),
                "difficulty": it.get("technique", ""), "threat_class": it.get("threat_class", ""),
                "goal_type": it.get("goal_type", "")}
        for name, (artifact, fn, applies) in layers.items():
            if applies is not None and not applies(it["text"]):
                rows.append({**base, "layer": name, "artifact": artifact, "applicable": 0, "diagnostic": 0,
                             "flagged": "", "miss": "", "score": "", "latency_ms": "", "error": ""})
                continue
            flagged, score, ms, err = _call(fn, it["text"])
            rows.append({**base, "layer": name, "artifact": artifact, "applicable": 1, "diagnostic": 0,
                         "flagged": flagged, "miss": "" if flagged is None else int(not flagged),
                         "score": score, "latency_ms": round(ms, 1), "error": err})
        if a.answers and it["label"] == "attack":
            rows += answer_rows(it, base)
        if n % 25 == 0:
            print(f"{n}/{len(items)}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    errors = [r for r in rows if r["error"]]
    print(f"wrote {len(rows)} rows to {out} ({len(errors)} errors)")
    if errors:
        print("first error:", errors[0]["error"])


def analyze(a) -> None:
    import numpy as np
    import pandas as pd

    from eval.eval_stats import cmh, pairwise_table, residual_asr, to_wide

    long_df = pd.read_csv(a.long, dtype={"threat_class": str})
    md = ["# RQ1 on direct injection: failure correlation", "", f"Source: `{a.long}`.", ""]
    # false refusals on benign prompts
    ben = long_df[(long_df.label == "benign") & (long_df.applicable == 1)].copy()
    if len(ben):
        ben["flagged"] = ben.flagged.astype(str).str.lower().eq("true")
        t = ben.groupby(["layer", "language"]).flagged.agg(["sum", "count"])
        md += ["## False refusals on benign prompts", "", "| Detector | Language | Refused |", "|---|---|---|"]
        md += [f"| {l} | {g} | {int(s)}/{int(c)} ({s / c:.0%}) |" for (l, g), (s, c) in t.iterrows()]
        md.append("")
    att = long_df[long_df.label == "attack"].copy()
    att["miss_n"] = pd.to_numeric(att.miss, errors="coerce")
    t = att[att.applicable == 1].groupby(["layer", "language"]).miss_n.agg(["mean", "count"])
    md += ["## Miss rate on attacks", "", "| Detector | Language | Miss rate | n |", "|---|---|---|---|"]
    md += [f"| {l} | {g} | {m:.0%} | {int(c)} |" for (l, g), (m, c) in t.iterrows()]
    md.append("")
    artifact = dict(zip(att.layer, att.artifact))
    att = att.drop(columns=["miss_n"])
    att["miss"] = pd.to_numeric(att.miss, errors="coerce")
    wide = to_wide(att)
    layers_all = [l for l in wide.columns if l not in ("sample_id", "seed_family", "language", "difficulty")]
    md += ["## Pairwise failure correlation", "",
           "Only samples where both detectors are applicable; phi is undefined (nan) when a detector never or "
           "always misses. CIs resample seed families.", "",
           "| Pair | Kind | n | miss j | miss k | phi [95% CI] | excess joint miss [95% CI] | CMH OR by language (p) | "
           "CMH OR by technique (p) |", "|---|---|---|---|---|---|---|---|---|"]
    for i, j in enumerate(layers_all):
        for k in layers_all[i + 1:]:
            sub = wide.dropna(subset=[j, k]).copy()
            if len(sub) < 3:
                continue
            sub[j], sub[k] = sub[j].astype(int), sub[k].astype(int)
            pt = pairwise_table(sub, [j, k], n_boot=a.n_boot).iloc[0]
            kind = "same artifact" if artifact.get(j) == artifact.get(k) else "cross artifact"
            c1, c2 = cmh(sub, j, k, "language"), cmh(sub, j, k, "difficulty")
            fmt = lambda c: "-" if not np.isfinite(c["or_mh"]) else f"{c['or_mh']:.2f} ({c['p']:.3f})"
            md.append(f"| {j} x {k} | {kind} | {len(sub)} | {pt.miss_j:.2f} | {pt.miss_k:.2f} | "
                      f"{pt.phi:.2f} [{pt.phi_lo:.2f}, {pt.phi_hi:.2f}] | {pt.excess:.3f} "
                      f"[{pt.excess_lo:.3f}, {pt.excess_hi:.3f}] | {fmt(c1)} | {fmt(c2)} |")
    q = [l for l in layers_all if artifact.get(l) == "query" and wide[l].notna().all()]
    if len(q) >= 2:
        obs, pred = residual_asr(wide.dropna(subset=q).astype({l: int for l in q}), q)
        md += ["", f"All query-side detectors ({', '.join(q)}) miss together on {obs:.0%} of attacks; "
                   f"{pred:.0%} if they failed independently."]
    out = Path(a.out_md)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--items", default=str(DATA2_DIR / "direct_injection.jsonl"))
    r.add_argument("--out", default=str(LONG))
    r.add_argument("--skip", nargs="*", default=[])
    r.add_argument("--no-check", action="store_true")
    r.add_argument("--bn", action="store_true", help="add BN_native as a query-side detector")
    r.add_argument("--bn-extra")
    r.add_argument("--e5-prefix", choices=["standard", "tagged"], default="standard",
                    help="E5 wrapping: standard = query:/passage: (default), tagged = <!><query> ... <!query>")
    r.add_argument("--bn-threshold", type=float)
    r.add_argument("--calibration", default=str(RESULTS_DIR / "calibration.json"))
    r.add_argument("--answers", action="store_true", help="also run attacks through generation (needs Ollama)")
    r.add_argument("--model", default="llama3.2:3b")
    r.add_argument("--temperature", type=float, default=0.2)
    r.add_argument("--seed", type=int, default=20263001)
    r.add_argument("--base-url", default="http://localhost:11434")
    z = sub.add_parser("analyze")
    z.add_argument("--long", default=str(LONG))
    z.add_argument("--out-md", default=str(RESULTS_DIR / "rq1_correlation.md"))
    z.add_argument("--n-boot", type=int, default=2000)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        from pilot.phase_2 import bn_route as _bn
        _bn.set_prefix_style(a.e5_prefix)
    run(a) if a.cmd == "run" else analyze(a)


if __name__ == "__main__":
    main()
