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
| L3 | 4/102 (3.9%) | 41/102 (40.2%) | 19/102 (18.6%) |

## Attack documents flagged at the chosen thresholds

BN_native scores here leave each document's own seed family out of the attack KB (the KB is built from these same phase-1 payloads).

| Detector | BL | EN | NT | TR |
|---|---|---|---|---|
| L2ext | 0/16 (0.0%) | 0/16 (0.0%) | 0/8 (0.0%) | 0/16 (0.0%) |
| L2b | 0/16 (0.0%) | 1/16 (6.2%) | 0/8 (0.0%) | 0/16 (0.0%) |
| L3 | 13/16 (81.2%) | 4/16 (25.0%) | 2/8 (25.0%) | 7/16 (43.8%) |
| BN_native | 3/16 (18.8%) | 0/16 (0.0%) | 2/8 (25.0%) | 3/16 (18.8%) |

Current `narrative_match_threshold` in config/thresholds.yaml: 0.42. Calibrated: 0.6149.
