# Ingestion detector calibration (target false-quarantine rate 2%)

Benign chunks: {'en': 102, 'bn': 102, 'banglish': 102}. Attack documents: 56 from `/mnt/E/4100 - Thesis/RAG-support-assistant/pilot/phase_1/pilot_items.jsonl`.


## Thresholds chosen on benign chunks

| Detector | Target | Threshold | Benign flagged: en | bn | banglish |
|---|---|---|---|---|---|
| L2b | 2% | 0.6149 | 5/102 (4.9%) | 0/102 (0.0%) | 1/102 (1.0%) |
| BN_native | 2% | 0.8922 | - | 2/102 (2.0%) | 1/93 (1.1%) |
| L2b | 5% | 0.6422 | 12/102 (11.8%) | 0/102 (0.0%) | 3/102 (2.9%) |
| BN_native | 5% | 0.8860 | - | 4/102 (3.9%) | 5/93 (5.4%) |

## Detectors without a threshold (false-quarantine rate on benign chunks)

| Detector | en | bn | banglish |
|---|---|---|---|
| L2ext | 0/102 (0.0%) | 0/102 (0.0%) | 0/102 (0.0%) |

## Attack documents flagged at the chosen thresholds

| Detector | BL | EN | NT | TR |
|---|---|---|---|---|
| L2ext | 0/16 (0.0%) | 0/16 (0.0%) | 0/8 (0.0%) | 0/16 (0.0%) |
| L2b | 0/16 (0.0%) | 1/16 (6.2%) | 0/8 (0.0%) | 0/16 (0.0%) |
| BN_native | 14/16 (87.5%) | 0/16 (0.0%) | 6/8 (75.0%) | 14/16 (87.5%) |

Current `narrative_match_threshold` in config/thresholds.yaml: 0.42. Calibrated: 0.6149.
