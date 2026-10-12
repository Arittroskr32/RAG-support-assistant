"""Were Bangla answers cut off, or Bangla prompts truncated? (review point 1)

  python -m pilot.phase_1.check_truncation                                 # pilot/phase_1/results/generations.jsonl
  python -m pilot.phase_1.check_truncation --gen pilot/phase_1/results-pilot-v1/generations.jsonl
  python -m pilot.phase_1.check_truncation --ollama-model llama3.2:3b      # exact prompt sizes, no HF login
  python -m pilot.phase_1.check_truncation --tokenizer meta-llama/Llama-3.2-3B-Instruct

Two checks:

1. Answer cut off. New runs record `finish` ("length" = cut at max_tokens). Old runs
   (the 5 Oct pilot) do not, so a heuristic is used instead: the answer does not end
   with sentence-final punctuation (। . ? ! ) ] `) or a canary-like code. A high
   "unfinished" share in the Bangla groups, but not in English, means the language
   comparison is confounded and the affected items should be re-run with
   --max-tokens 1024.

2. Prompt truncated. Ollama's context window (num_ctx) cuts the START of an over-long
   prompt, which is where the system prompt sits. New ollama-backend runs record
   prompt_tokens. For old runs, --ollama-model asks Ollama itself to count every pilot
   prompt (one 1-token generation per prompt, with a large num_ctx so nothing is cut),
   or --tokenizer counts with a Hugging Face tokenizer (needs `transformers` and access
   to that tokenizer; any Llama-3 tokenizer gives the right count). Compare with the num_ctx your Ollama used (default 2048
   in older versions, 4096 in newer ones; check `ollama show <model>`), or search
   the Ollama server log for "truncating input prompt".

Writes pilot/phase_1/results/truncation_report.md.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from pilot.phase_1.common import RESULTS_DIR, build_messages, load_items

FINAL = re.compile(r"[।.?!)\]`*\"'”’>]\s*$|[A-Za-z]{1,6}-?\d{3,}\s*$|\d\s*$")


def unfinished(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and not FINAL.search(t)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default=str(RESULTS_DIR / "generations.jsonl"))
    ap.add_argument("--items", default="pilot/phase_1/pilot_items.jsonl")
    ap.add_argument("--tokenizer", default="", help="HF tokenizer to count prompt tokens of old runs")
    ap.add_argument("--ollama-model", default="", help="count prompt tokens with this Ollama model")
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--num-ctx", type=int, default=2048,
                    help="context window to compare prompt length with (old runs)")
    ap.add_argument("--out", default=str(RESULTS_DIR / "truncation_report.md"))
    a = ap.parse_args(argv)

    g = pd.DataFrame([json.loads(l) for l in open(a.gen, encoding="utf-8") if l.strip()])
    if "error" not in g:
        g["error"] = ""
    g = g[g.error.fillna("") == ""].copy()
    if g.empty:
        raise SystemExit("no generations without error")
    g["answer"] = g.answer.fillna("")
    g["unfinished"] = g.answer.map(unfinished)
    g["chars"] = g.answer.str.len()
    if "finish" not in g:
        g["finish"] = ""
    g["finish"] = g.finish.fillna("")
    g["cut"] = g.finish.eq("length")
    has_finish = g.finish.ne("").any()

    md = ["# Truncation check", "",
          f"Source: `{a.gen}` ({len(g)} generations without error).", ""]

    agg = {"n": ("answer", "size"), "median_chars": ("chars", "median"),
           "unfinished_%": ("unfinished", lambda s: round(100 * s.mean())),
           "success_%": ("success", lambda s: round(100 * pd.to_numeric(s, errors="coerce").mean()))}
    if has_finish:
        agg["cut_at_max_tokens_%"] = ("cut", lambda s: round(100 * s.mean()))
    if "completion_tokens" in g:
        g["completion_tokens"] = pd.to_numeric(g.completion_tokens, errors="coerce")
        agg["max_completion_tokens"] = ("completion_tokens", "max")
    t1 = g.groupby(["model", "config", "group"]).agg(**agg).reset_index()
    md += ["## 1. Answers cut off", "",
           "`unfinished_%` is a heuristic (no sentence-final punctuation)."
           + (" `cut_at_max_tokens_%` is exact." if has_finish else
              " These runs have no `finish` field, so the heuristic is all there is."), "",
           t1.to_markdown(index=False), ""]

    # marker goals are the ones whose canary sits at the END of the answer
    mk = g[g.goal_type == "marker"]
    if not mk.empty:
        t2 = (mk.groupby(["model", "group", "unfinished"])
                .success.agg(lambda s: f"{int(pd.to_numeric(s).sum())}/{len(s)}").unstack(fill_value="–"))
        t2.columns = [f"unfinished={c}" for c in t2.columns]
        md += ["### Marker goals: successes among finished vs unfinished answers", "",
               "If unfinished answers almost never succeed, truncation may be hiding the canary.", "",
               t2.reset_index().to_markdown(index=False), ""]

    # prompt length
    md += ["## 2. Prompt length vs context window", ""]
    if "prompt_tokens" in g and pd.to_numeric(g.prompt_tokens, errors="coerce").notna().any():
        g["prompt_tokens"] = pd.to_numeric(g.prompt_tokens, errors="coerce")
        t3 = g.groupby(["model", "group"]).prompt_tokens.agg(["median", "max"]).reset_index()
        md += ["Recorded by the backend (ollama: prompt_eval_count).", "", t3.to_markdown(index=False), ""]
        if "num_ctx" in g:
            ctx = pd.to_numeric(g.num_ctx, errors="coerce")
            over = g[ctx.notna() & (g.prompt_tokens >= ctx * 0.98)]
            md += [f"Prompts at or near num_ctx (likely truncated): **{len(over)}**", ""]
    if a.tokenizer or a.ollama_model:
        if a.ollama_model:
            import requests
            def count(system, user):
                r = requests.post(f"{a.base_url.rstrip('/').removesuffix('/v1')}/api/chat", timeout=600,
                                  json={"model": a.ollama_model, "stream": False,
                                        "options": {"num_predict": 1, "num_ctx": 32768},
                                        "messages": [{"role": "system", "content": system},
                                                     {"role": "user", "content": user}]})
                r.raise_for_status()
                return r.json()["prompt_eval_count"]
            source = f"Ollama `{a.ollama_model}` (prompt_eval_count)"
        else:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained(a.tokenizer)
            def count(system, user):
                return len(tok.apply_chat_template(
                    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    tokenize=True, add_generation_prompt=True))
            source = f"`{a.tokenizer}`"
        items = {i["item_id"]: i for i in load_items(a.items)}
        rows = []
        for iid, it in items.items():
            for fenced in (False, True):
                system, user = build_messages(it, fenced=fenced)
                rows.append({"item_id": iid, "group": it["group"], "fenced": fenced,
                             "tokens": count(system, user)})
        t4 = pd.DataFrame(rows)
        over = t4[t4.tokens > a.num_ctx]
        md += [f"Counted with {source} (system + documents + question).", "",
               t4.groupby(["group", "fenced"]).tokens.agg(["median", "max"]).reset_index()
                 .to_markdown(index=False), "",
               f"Prompts longer than num_ctx={a.num_ctx}: **{len(over)}**"
               + (f" ({', '.join(sorted(set(over.item_id)))})" if len(over) else ""), ""]
    elif not ("prompt_tokens" in g and g.prompt_tokens.notna().any()):
        md += ["No token counts recorded. Re-run with `--tokenizer` or check the Ollama log "
               "for `truncating input prompt`.", ""]

    Path(a.out).write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
