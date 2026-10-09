# Design checks D1–D4 (DECISIONS.md D-22 to D-25)

Four code-level design checks, one per gap found in the design review. D1–D3 were fixed by
PRs #1–#3; D4 is a measurement first and a fix second. All commands run from the repository root.

| Check | Question | Threat row | Fix | How it is tested | Status |
|---|---|---|---|---|---|
| **D1** Images and links in answers | Can a planted document make the answer load or link an external URL that carries user data? | 8 | PR #1 render guard (`generation/rich_output.py`) | `pilot/d1/d1_check.py`: server, browser (render) and end-to-end modes | **Done**, see `d1/d1_result.md` |
| **D2** Who sets tenant and trust | Can a file label itself with another tenant or high trust? | 3 | PR #2 (tenant and trust from `config/ingestion_sources.yaml` only) | `tests/test_provenance.py` | Unit tests pass (11) |
| **D3** Sanitise once | Do invisible characters reach the model while the scanners see a cleaned copy? | 4, 5 | PR #3 L0 sanitiser (`security/text_sanitiser.py`) | `tests/test_text_sanitiser.py`, `tests/test_pipeline.py -k l0` | Unit tests pass (19 + pipeline) |
| **D4** Timing side channel | Can an attacker tell from response time which layer blocked a request? | 9 | Padding (`refusal_min_latency_ms`), **not built yet** | `pilot/d4/`: traffic, then latency-by-`blocked_at` plot | Scripts ready; needs the GPU machine |

## D1: images and links

Result and reproduction commands: [`d1/d1_result.md`](d1/d1_result.md). Step-by-step local guide for D1, D4 and the pilot items: [`LOCAL_TEST_GUIDE.md`](LOCAL_TEST_GUIDE.md). No model or GPU is needed
for the server and render modes. `--guard off` is the same switch as `enable_render_guard: false`.

## D2 and D3

```bash
pytest -q tests/test_provenance.py                       # D2: front-matter tenant/trust ignored, clearance only raised
pytest -q tests/test_text_sanitiser.py tests/test_pipeline.py -k "sanitis or l0"   # D3
```

An attack-level check for D2 (a P4 author's file in `data/public_faq/` with `tenant_id: acme` and
`trust: high` in its front-matter, then asking as a `default`-tenant customer) and for D3 (an
instruction hidden in Unicode tag characters) fits into the shadow-mode attack suite, with the canary
deciding success like every other row.

## D4: response time by blocking layer

Needs the real stack (MiniLM embedder, KB-2 built from `data/security_datasets/`, L3 guardrail on the
GPU, Ollama with `llama3.2:3b`), because the latencies are the result.

```bash
# 0. configuration for this run (do not commit)
#    config/thresholds.yaml: fast_path_ceiling: -1.0   (D-11; main still has 0.5, which lets
#                            low-risk queries skip L3 and blurs the L3 group)
#                            rate_limit_soft: 1000, rate_limit_hard: 2000
cp pilot/d4/d4_secret_doc.md data/public_faq/              # gives L8 something to catch
./run.sh                                                    # rebuilds KBs, starts Ollama + API on :8000
python -m api.create_api_key --user-id d4 --role customer   # prints the key once
python pilot/d4/d4_fill_kb2.py --n 10                       # prompts stored in KB-2 that L2 doesn't catch

# 1. traffic: ~38 prompts x 3 repeats, shuffled, client-side wall-clock time
python pilot/d4/d4_traffic.py --api-key <key> --repeats 3

# 2. plot and the attacker test
python pilot/d4/d4_plot.py --events logs/security_events.jsonl --traffic pilot/d4/out/traffic.csv --tag before

# 3. clean up
rm data/public_faq/d4_secret_doc.md && git checkout config/thresholds.yaml
```

Output in `pilot/d4/out/`:
- `d4_latency_by_layer_before.png`: box plot of response time (log scale) per `blocked_at` group
  (`L2`, `L2b`, `KB2`, `L3`, `L8`, `L8 redacted`, `not blocked`, `rate limit (429)`).
- `d4_summary_before.md`: median and quartiles per group, plus the threat-row-9 answer: leave-one-out
  accuracy of guessing the blocking layer, and of guessing "was an answer generated", from latency
  alone, against the guess-the-majority baseline.

What to expect: requests blocked before L3 come back in tens of milliseconds, L3 blocks take a
guardrail forward pass, and anything that reached generation (`not blocked`, `L8 redacted`, `L8`)
takes seconds. If the attacker accuracy is well above the baseline, the channel is demonstrated.

Two things to know when reading it:
- L8's regex scanners **redact** and do not set `blocked_at`; only a KB-5 semantic match blocks. The
  sandbox card question therefore usually shows up as `L8 redacted`, which the plot keeps separate.
- The "after" run (`--tag after`) needs `refusal_min_latency_ms` (D-25 step 2), which is not in the
  code yet. Until then only the "before" plot exists.
