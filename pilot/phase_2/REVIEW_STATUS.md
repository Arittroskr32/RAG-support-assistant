# Senior review of generation.md: what is done, what is left

Checked against the repository code and the committed results in `pilot/phase_2/results/`
(model llama3.2:3b, temperature 0.2, selection seeds 20262013–15, measurement seeds 20263013–15).
"Done" means the code exists, is tested, and has results; "left" says who has to do it.

| # | Review item | Status | Evidence |
|---|---|---|---|
| 1 | RQ2 funnel per language, three configurations | Code done; Bangla-serving still uses llama3.2:3b | `stack_check2.py`, factor table in `phase2_report.md`. **Left (you):** run `bangla_serving` and `bangla_serving_bn` with `qwen3:4b` once item 14 says it is Bangla-capable. |
| 2 | Bangla retrieval quality alongside | Done | `retrieval_eval.md`: Bangla Recall@1 MiniLM 0.08, E5 0.75; Banglish 0.75 vs 0.67 (n = 12 each, small). |
| 3 | RQ1 correlation on direct injection | Code done; **data missing** | `direct_shadow.py`. `data/direct_injection.jsonl` has 45 benign prompts but only 3 attacks (one per language), so φ is undefined in `rq1_correlation.md`. **Left (you):** write the direct attacks (CSV template + `make_direct.py`). |
| 4 | C1 positive control | Done | Selection runs, user request vs document: EN 73% vs 72%, TR 62% vs 10%, BL 18% vs 7%, NT 10% vs 7%. TR shows comprehension without compliance; for BL/NT the model mostly cannot carry out the instruction even when the user asks, so their low attack rate is partly incapacity. |
| 5 | C2 base rate for PII/phishing | Done (phish only; phase-2 items have no PII goal) | Selection runs, phish with vs without the instruction: EN 0/9 vs 5/9, BL 2/9 vs 4/9, TR 6/9 vs 5/9, NT 3/9 vs 1/9. Phish "successes" are mostly instruction-free poisoning, as the reviewer suspected. |
| 6 | 56 pilot items = dev, new seed families for test | Done | `pilot_items2.jsonl`: 80 items, 20 new families × 4 groups; `validate_items2` passes (no reuse). |
| 7 | Select on one set of runs, measure on fresh runs | Done | `run_generation.py --phase`, `select_valid.py`; different seeds per phase. 24 of 80 items valid. |
| 8 | Real L6/L7 prompt as baseline | Done | `--prompt real` default (`common2.real_prompt`). |
| 9 | Human-written Banglish | Done if the labels are right | All 80 items carry `author: human`. The 16 AI-drafted phase-1 BL items stay in dev only. |
| 10 | Log retrieved chunk IDs, check every group canary | Done | `stack2_*.csv`; `bangla_serving` BL had 2 answers carrying another item's canary. |
| 11 | Thresholds at a fixed false-quarantine rate on benign docs (EN + BN) | Done, with one fix in this PR | `calibration.md` at 2% on 102 chunks per language. **Fixed here:** its BN_native attack-detection column (87.5%) scored phase-1 attacks against a KB built from the same payloads; the score now leaves each document's own family out. **Left (you):** re-run `calibrate.py` (and add `--with-l3` on the GPU for L3 on chunks). Note L2b at the pooled 2% target flags 4.9% of English chunks. |
| 12 | Temperature and seed, per-run rates, exact paired test | Done, with one fix in this PR | Report already had settings and per-run rates. **Fixed here:** the paired test was run only on the 24 valid items (2 shared families). It now uses all 20 shared families of the selection runs: EN vs BL 15/1, McNemar p = 0.0005; EN vs TR p = 0.0007; EN vs NT p = 0.0003; TR vs BL p = 1.0. |
| 13 | D4 among refused requests, explain the 1.4 s KB-2 outlier | Analysis done; padding not applied | `d4_refused_before.md`: 94% accuracy vs 59% majority guess. The 1378 ms KB-2 refusal spent 982 ms in L1 right after a 30.9 s generation, so it is GPU contention, not KB-2. `d4_refused_after.md` is identical because `refusal_min_latency_ms` is still 0. **Left (you):** set it (above 709 ms, below 7178 ms), re-run the D4 traffic and `d4_refused --tag after`. |
| 14 | Qwen3-4B: check Bangla answers first | Generations done, **review missing** | `bangla_check_<model>.csv` have 0 rows reviewed. **Left (you or a native speaker):** fill correct / same_language / natural, then `bangla_check summarize`. |
| 15 | E5 with `query: ` on both sides for similarity, own thresholds | Done | `BNNative` embeds both KB and chunks with `embed_query`; its threshold is calibrated separately. |
