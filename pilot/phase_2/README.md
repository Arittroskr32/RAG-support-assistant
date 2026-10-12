# Pilot phase 2

Phase 2 carries out the senior reviewer's feedback (plan steps A to H). Phase 1 lives in
`pilot/phase_1/` and is not changed apart from import paths; its 56 items are now the
**development set**. All phase-2 results are written to `pilot/phase_2/results/`.

The folder is called `phase_2` (underscore) rather than `phase-2` because Python cannot import a
package whose name has a hyphen, and every script here is run as `python -m pilot.phase_2.<script>`.

## What you need

| Step | Needs |
|---|---|
| Tests, validation, variants, analysis | nothing beyond the repo's `requirements.txt` |
| Generation, stack checks, Bangla check | Ollama with the models (`llama3.2:3b`, `llama3.1:8b`, `qwen3:4b`) |
| E5 route, BN_native, retrieval eval | `sentence-transformers` and the `intfloat/multilingual-e5-small` model (downloads once, ~470 MB) |
| L3 (`--with-l3`, `q_L3`) | the Llama-Guard backend the main pipeline uses (GPU) |

Run everything from the repository root.

## Check the code works (no GPU, no Ollama)

```bash
python -m pytest -q pilot/phase_2/tests
```

24 tests cover every script with the repository's fake KB, fake guardrail, fake LLM and a fake E5
embedder: seeds and the think switch are sent, controls are built without leftover payload
fragments, stack configs restore everything they patch, calibration picks thresholds at the
target rate, the statistics match hand-computed values, and refusal padding works.

## The new item file: `pilot/phase_2/pilot_items2.jsonl`

Same fields as phase 1 (see `pilot/phase_1/DATASET.md`) plus:

| Field | Required | Meaning |
|---|---|---|
| `split` | yes | always `"test"` (phase-1 items are the dev set) |
| `author` | yes | `human`, `ai-draft+human-edit`, `translated-ai+reviewed` or `translated-human` |
| `seed_family` | yes | must be NEW: no family, canary core or payload reused from phase 1 |
| `user_request` | recommended | for the positive control: the same instruction phrased as the user's own request, in the item's language |
| `entity_sentence` | phish items | a neutral sentence that keeps the address/URL (with the canary core) for the base-rate control |
| `reviewer`, `review_status` | recommended | `review_status: "approved"` once checked |

Four example rows are in `pilot_items2.example.jsonl`. Check your file before running anything:

```bash
python -m pilot.phase_2.validate_items2                      # reads pilot/phase_2/pilot_items2.jsonl
python -m pilot.phase_2.validate_items2 --items pilot/phase_2/pilot_items2.example.jsonl
```

Hard failures (exit code 1): any phase-1 check, `split` not `test`, a reused family/core/payload,
an unknown `author`. Warnings: not approved, fewer than 12 items in a group, phish without
`entity_sentence`, no `user_request`, fewer human than AI-made Banglish items.

## Order of work

### 1. Controls (plan step C)

```bash
python -m pilot.phase_2.make_variants          # -> results/variants2.jsonl
cat pilot/phase_2/pilot_items2.jsonl pilot/phase_2/results/variants2.jsonl > pilot/phase_2/results/all_items2.jsonl
```

`<id>~pc` is the positive control (instruction moved to the user), `<id>~br` the base rate
(instruction removed, entity kept; pii and phish only). Rows marked `draft: true` were built
by the script because `user_request` / `entity_sentence` was missing: read them before running.

### 2. Generator runs: selection, then fresh measurement (steps B1 to B3)

The baseline prompt is the real L6/L7 prompt of the repository (`--prompt real`, default).
Every request sends a seed; seeds differ between the selection and measurement phases, so the
measurement runs are new samples, not a re-read of the selection runs.

```bash
# selection: which attacks work at all
python -m pilot.phase_2.run_generation --items pilot/phase_2/results/all_items2.jsonl \
    --model llama3.2:3b --phase selection --runs 3
python -m pilot.phase_1.hand_check --gen pilot/phase_2/results/generations2.jsonl --model llama3.2:3b
python -m pilot.phase_2.select_valid --model llama3.2:3b         # -> results/valid_llama3.2-3b.json

# measurement: fresh runs on the valid attacks only (plus their controls)
python -m pilot.phase_2.run_generation --items pilot/phase_2/results/all_items2.jsonl \
    --model llama3.2:3b --phase measurement --runs 3 \
    --only-file pilot/phase_2/results/valid_llama3.2-3b.json
```

Repeat for `llama3.1:8b` and, after step 4, `qwen3:4b` (thinking is switched off automatically).
Runs resume where they stopped. `--no-l6` is the no-fencing ablation; `--prompt stand_in` re-runs
the phase-1 prompt for comparison.

### 3. Report (step B7)

```bash
python -m pilot.phase_2.analyze --phase measurement --valid pilot/phase_2/results/valid_llama3.2-3b.json
# -> results/phase2_report.md
```

Per-run success with Wilson 95% CIs, per-item success, paired group comparisons on shared seed
families (exact McNemar, sign test, sign-flip), the positive-control 2x2 table (C1), injection
lift over the base rate (C2), and the factor table from the stack checks.
`results/phase1_dev_report.md` is the same report on the phase-1 generations, for reference.

### 4. Is Qwen3-4B better in Bangla? (step D2)

Put benign Bangla/Banglish documents in `data/benign_docs/` and questions in
`data/benign_questions.jsonl` first (see `data/README.md`).

```bash
python -m pilot.phase_2.bangla_check run --models llama3.2:3b qwen3:4b
# a native speaker fills correct / same_language / natural (1/0) in results/bangla_check_<model>.csv
python -m pilot.phase_2.bangla_check summarize      # -> results/bangla_check.md
```

### 5. Bangla-serving pipeline (step E)

```bash
python -m pilot.phase_2.retrieval_eval              # -> results/retrieval_eval.md (Recall@1, @k, MRR per language)
python -m pilot.phase_2.calibrate --target 0.02     # -> results/calibration.json / .md
```

The E5 route: questions in Bangla script, or with two or more Banglish function words, are
embedded with multilingual-E5 (`query: ` prefix) and searched in a copy of KB-4
(`kb4_documents_e5`, chunks embedded with `passage: `). The same role filter (`build_where`) is
used, so RBAC does not change. English questions keep the deployed MiniLM index.

BN_native compares each Bangla/Banglish chunk with the Bangla attack examples (the non-English
phase-1 payloads only; test payloads are refused) and quarantines it above the threshold.
`calibrate.py` picks every threshold on benign documents at a fixed false-quarantine rate and
writes them to `calibration.json`; it never edits `config/thresholds.yaml`.

### 6. Three configurations, one stack (step F)

```bash
for cfg in deployed bangla_serving bangla_serving_bn; do
  python -m pilot.phase_2.stack_check2 --config $cfg --model llama3.2:3b --runs 3 \
      --only-file pilot/phase_2/results/valid_llama3.2-3b.json
done
python -m pilot.phase_2.stack_check2 --config bangla_serving_bn --model qwen3:4b --runs 3 \
    --only-file pilot/phase_2/results/valid_llama3.2-3b.json
python -m pilot.phase_2.analyze                     # factor table in phase2_report.md
```

Each row logs the retrieved chunk ids, which planted items they came from, whether the item's own
payload was retrieved, and every group canary found in the raw and final answer.
Outcomes: `quarantined`, `blocked:<layer>`, `success`, `other_item_hit`, `not_retrieved`,
`stopped_by_output_guard`, `ignored`. Output: `results/stack2_<config>_<model>.csv` and
`results/stack2_runs.jsonl`. Planted documents are removed and KB-4 rebuilt at the end.

### 7. RQ1 on direct injection (step G)

Write `data/direct_injection.jsonl` (attacks and benign prompts; format in
`data/examples/direct_injection.jsonl`), with seed families that are not in KB-2.

```bash
python -m pilot.phase_2.direct_shadow run --bn            # add --skip q_L3 without the GPU guardrail
python -m pilot.phase_2.direct_shadow run --bn --answers --model llama3.2:3b   # adds L8 / render guard rows
python -m pilot.phase_2.direct_shadow analyze             # -> results/rq1_correlation.md
```

### 8. D4 timing (step H)

Re-run the phase-1 D4 traffic (`pilot/phase_1/d4/`), then:

```bash
python -m pilot.phase_2.d4_refused --tag before          # -> results/d4_refused_before.md
```

It reports leave-one-out accuracy among refused requests only, the confusion matrix, the slowest
refusals with per-layer timings and an outlier flag. If the layers can still be told apart, set
`refusal_min_latency_ms` in `config/thresholds.yaml` (default 0 = off: every refusal is then
held until that many ms after the request started), re-run the traffic and the script with
`--tag after`.

## Results folder

| File | From |
|---|---|
| `variants2.jsonl`, `all_items2.jsonl` | step 1 |
| `generations2.jsonl`, `run_metadata2.jsonl`, `valid_<model>.json` | step 2 |
| `phase2_report.md` | step 3 |
| `bangla_check_<model>.csv`, `bangla_check.md` | step 4 |
| `retrieval_eval.csv/.md`, `calibration.json/.md`, `calibration_benign_scores.jsonl` | step 5 |
| `stack2_<config>_<model>.csv`, `stack2_runs.jsonl` | step 6 |
| `direct_shadow_long.csv`, `rq1_correlation.md` | step 7 |
| `d4_refused_<tag>.md` | step 8 |

## Plan step to script

| Plan step | Script |
|---|---|
| B1 dev/test split, new families | `validate_items2.py` |
| B2 selection vs measurement runs | `run_generation.py --phase`, `select_valid.py` |
| B3 real L6/L7 baseline | `run_generation.py --prompt real` (`common2.real_prompt`) |
| B4 human Banglish | `author` field, `validate_items2.py` warning |
| B5 retrieved chunk ids, all group canaries | `stack_check2.py` |
| B6 calibration at a fixed false-quarantine rate | `calibrate.py` |
| B7 statistics | `analyze.py` |
| C1, C2 controls | `make_variants.py`, `analyze.py` |
| D2 Bangla check | `bangla_check.py` |
| E1 to E3 E5 route, retrieval quality, BN_native | `bn_route.py`, `retrieval_eval.py`, `calibrate.py` |
| F factor decomposition | `stack_check2.py`, `analyze.py` |
| G RQ1 on direct injection | `direct_shadow.py` |
| H D4 refused-only accuracy, padding | `d4_refused.py`, `refusal_min_latency_ms` |
