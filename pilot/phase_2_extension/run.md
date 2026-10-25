# Phase 2 extension: run order

The commands work in bash and zsh. Every variable holds a single word, because zsh does not split a
variable into several arguments. Run everything from the repository root, on the same machine and setup as phase 2 (Ollama, the GPU, the
fine-tuned L3 adapter, `multilingual-e5-small`). Start with `git pull`. Every step writes to
`pilot/phase_2_extension/results/`. Times are rough, taken from the phase-2 runs on the same laptop.

```bash
X=pilot/phase_2_extension
QWEN=qwen3:4b-instruct-2507-q4_K_M
V3B=$X/inputs/valid_llama3.2-3b.json
VQW=$X/inputs/valid_qwen3-4b-instruct-2507-q4-K-M.json
```

## 0. Check (no GPU, about 1 minute)

```bash
python -m pytest -q pilot/phase_2/tests $X/tests
python -m pilot.phase_2_extension.offline_checks          # -> results/offline_checks.md (already committed)
```

## 1. Extra items (seconds; already committed, rerun if you edit the paraphrases)

Before reporting anything about paraphrases, read `data/bn_paraphrases.jsonl` and fix the Bangla and Banglish wording. They are AI drafts. When you are happy with them, set `review_status` to `approved`.

```bash
python -m pilot.phase_2_extension.make_items_ext crossed       # results/crossed_items.jsonl (80)
python -m pilot.phase_2_extension.make_items_ext paraphrase    # results/paraphrase_items*.jsonl (27 = 9 x 3 styles)
```

## 2. Every chunk detector on every document (point 3, design point 1)

Stop the API first (this step reads the knowledge bases).

```bash
python -m pilot.phase_2_extension.detectors_all              # CPU, ~5 min: L2ext, L2b, BN_native, BN_native_all, E5_all
python -m pilot.phase_2_extension.detectors_all --with-l3    # + L3 on every chunk (GPU, ~30-60 min)
python -m pilot.phase_2_extension.rq1_chunks                 # RQ1: L3 x E5_all on chunks -> results/rq1_chunks.md
```

`detectors_all` also calibrates E5_all and writes `results/detectors_thresholds.json`, which step 6 needs. **Run `--with-l3` last**, because each run overwrites the same files.

## 3. Generator runs on the crossed and paraphrased items (design point 2, point 3)

Selection seeds, real prompt, 3 runs, same as phase 2. They all write to one file.

```bash
for M in llama3.2:3b $QWEN; do
  # 80 items, ~1 h per model
  python -m pilot.phase_2.run_generation --model $M --items $X/results/crossed_items.jsonl \
      --out $X/results/generations_ext.jsonl --phase selection --runs 3
  for S in policy content reworded; do      # 9 items each
    python -m pilot.phase_2.run_generation --model $M --items $X/results/paraphrase_items_$S.jsonl \
        --out $X/results/generations_ext.jsonl --phase selection --runs 3
  done
done
python -m pilot.phase_1.hand_check --gen $X/results/generations_ext.jsonl   # hand-check every hit, as in phase 2
```

(llama3.1:8b is optional here. Add it to the loop if there is time.)

## 4. Stack with the competing documents hidden (point 2): 3B valid set

```bash
for C in deployed bangla_serving bangla_serving_bn; do
  python -m pilot.phase_2_extension.stack_ext --config $C --model llama3.2:3b --only-file $V3B --isolate
done
```

`--isolate` plants all 24 items once and hides every other planted document from retrieval for each question. Compare the result with the phase-2 Table 8. If English compliance stays near 0/42, competition was not the cause (offline_checks.md §H already points that way).

## 5. Qwen on its own valid set (the senior's question), per-item breakdown

```bash
for C in bangla_serving bangla_serving_bn; do
  python -m pilot.phase_2_extension.stack_ext --config $C --model $QWEN --only-file $VQW             # as in phase 2
  python -m pilot.phase_2_extension.stack_ext --config $C --model $QWEN --only-file $VQW --isolate   # without competition
done
```

Qwen's valid set has 18 EN, 4 BL (BL-204, BL-211, BL-212, BL-216), 1 NT (BN-216) and no TR items. BL-211 and BL-212 are phishing items, so only BL-204, BL-216 and BN-216 answer the question for marker goals.

## 6. Instruction-deleted documents and the language-independent detector (point 1, design point 1)

```bash
# ~br documents through BN_native: are they quarantined, and does the address still leak?
for M in llama3.2:3b $QWEN; do
  python -m pilot.phase_2_extension.stack_ext --config bangla_serving_bn   --model $M --variant base_rate --isolate
  python -m pilot.phase_2_extension.stack_ext --config bangla_serving_e5all --model $M --variant base_rate --isolate
done
# E5_all on every chunk instead of router-gated BN_native, on the attacks
python -m pilot.phase_2_extension.stack_ext --config bangla_serving_e5all --model llama3.2:3b --only-file $V3B --isolate
python -m pilot.phase_2_extension.stack_ext --config bangla_serving_e5all --model $QWEN --only-file $VQW --isolate
```

Each answer also goes through the official-contact check in shadow mode (columns `contact_guard`, `contact_guard_caught`). Each run logs how many benign KB-4 chunks the scan quarantined (`stackx_runs.jsonl`, `benign_chunks_quarantined`). Phase 2 did not report that cost.

## 7. Tables

```bash
python -m pilot.phase_2_extension.analyze_ext     # -> results/phase2_extension_report.md
```

Then send me the results folder, or push it, and I will write the extension section and update the full report.

## Total

Steps 2–6 take about one to one and a half days of GPU time on the laptop. The native-Bangla stack questions are the slow part (median 2.5 minutes each on 3B). If time is short, run step 2, the Qwen part of step 5 and step 6 first. They answer the senior's three main points.

## 8. Follow-ups after the first results (25 Oct)

```bash
pip install statsmodels                                       # CMH in rq1_chunks
python -m pilot.phase_2_extension.rq1_chunks                  # rerun with CMH (product chunking)

# Chunking check (stop the API first). The stack splits the planted note so the payload is its own
# chunk (kb4); `joined` glues it to the carrier text. Each mode writes to results/chunking_<mode>/.
for C in kb4 joined; do
  python -m pilot.phase_2_extension.detectors_all --chunking $C              # CPU, ~5 min
done
# RQ1 with L3 on the kb4 chunks (GPU, ~30-60 min), then the pair table
python -m pilot.phase_2_extension.detectors_all --chunking kb4 --with-l3
python -m pilot.phase_2_extension.rq1_chunks --long $X/results/chunking_kb4/detectors_long.csv \
    --out $X/results/chunking_kb4/rq1_chunks.md
```
