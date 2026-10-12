# Phase-2 input data

Files you write. The scripts read them from here by default.

| Path | Used by | Format |
|---|---|---|
| `benign_docs/en/`, `benign_docs/bn/`, `benign_docs/banglish/` | `calibrate.py`, `retrieval_eval.py`, `bangla_check.py` | Markdown support documents, one topic per file, written or checked by a person. No attack text. They set the false-quarantine thresholds, so do not use AI-written text you have not edited. |
| `benign_questions.jsonl` | `retrieval_eval.py`, `bangla_check.py` | `{"qid", "language": "en"/"bn"/"banglish", "question", "gold_source"}`; `gold_source` is `benign_docs/<lang>/<file>.md` or a repository path under `data/` such as `public_faq/general_faq.md`. |
| `direct_injection.jsonl` | `direct_shadow.py` | attacks `{"sample_id", "label": "attack", "text", "seed_family", "language", "threat_class", "technique"}` and benign prompts `{"sample_id", "label": "benign", "text", "language"}`. Seed families must not be in KB-2. |
| `bn_attack_extra.jsonl` (optional) | `--bn-extra` | `{"text": ...}` extra Bangla attack examples for BN_native; never test items. |

`examples/` holds a few rows of each format. They are only examples and are not read by default.
Calibration needs enough benign chunks per language: at a 2% target rate, at least 100.
