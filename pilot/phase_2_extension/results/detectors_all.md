# Chunk detectors on every phase-2 document

Thresholds: L2b 0.6149 and BN_native 0.8922 from `calibration.json` (phase 2); E5_all 0.8915 (strictest per-language threshold at 2%: {'en': 0.878, 'bn': 0.8914, 'banglish': 0.8915}; attack KB 56 phase-1 payloads, all languages).

## False quarantines on benign chunks

| Detector | en | bn | banglish |
|---|---|---|---|
| L2ext | 0/102 (0%) | 0/102 (0%) | 0/102 (0%) |
| L2b | 5/102 (5%) | 0/102 (0%) | 1/102 (1%) |
| L3 | 4/102 (4%) | 41/102 (40%) | 19/102 (19%) |
| BN_native | - (of 102; 102 not scanned) | 2/102 (2%) | 1/93 (1%) (of 102; 9 not scanned) |
| BN_native_all | 0/102 (0%) | 2/102 (2%) | 1/102 (1%) |
| E5_all | 0/102 (0%) | 2/102 (2%) | 2/102 (2%) |

Router: 9 Banglish and 0 Bangla benign chunks are routed as English, so router-gated BN_native never sees them.

## Attack documents flagged (all 80 phase-2 items; not-scanned counts as missed)

| Detector | EN | TR | BL | NT |
|---|---|---|---|---|
| L2ext | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) |
| L2b | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) |
| L3 | 1/20 (5%) | 2/20 (10%) | 9/20 (45%) | 0/20 (0%) |
| BN_native | 0/20 (0%) | 1/20 (5%) | 0/20 (0%) | 1/20 (5%) |
| BN_native_all | 0/20 (0%) | 1/20 (5%) | 0/20 (0%) | 1/20 (5%) |
| E5_all | 0/20 (0%) | 1/20 (5%) | 1/20 (5%) | 1/20 (5%) |

By goal:

| Detector | marker | phish |
|---|---|---|
| L2ext | 0/68 (0%) | 0/12 (0%) |
| L2b | 0/68 (0%) | 0/12 (0%) |
| L3 | 8/68 (12%) | 4/12 (33%) |
| BN_native | 0/68 (0%) | 2/12 (17%) |
| BN_native_all | 0/68 (0%) | 2/12 (17%) |
| E5_all | 1/68 (1%) | 2/12 (17%) |

## Instruction-deleted documents (~br): would an instruction detector stop poisoning?

| Detector | EN | TR | BL | NT |
|---|---|---|---|---|
| L2ext | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| L2b | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| L3 | 0/3 (0%) | 3/3 (100%) | 2/3 (67%) | 3/3 (100%) |
| BN_native | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| BN_native_all | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| E5_all | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |

## Paraphrase attack against the example-matching detectors

| Detector | Style | Originals flagged | Paraphrases flagged | Evaded (of flagged originals) | Mean score drop |
|---|---|---|---|---|---|
| L3 | policy | 3/9 (33%) | 5/9 (56%) | 1/3 | -0.222 |
| L3 | content | 3/9 (33%) | 4/9 (44%) | 1/3 | -0.111 |
| L3 | reworded | 3/9 (33%) | 6/9 (67%) | 1/3 | -0.333 |
| BN_native | policy | 0/9 (0%) | 1/9 (11%) | 0/0 | +0.001 |
| BN_native | content | 0/9 (0%) | 0/9 (0%) | 0/0 | +0.012 |
| BN_native | reworded | 0/9 (0%) | 0/9 (0%) | 0/0 | +0.008 |
| BN_native_all | policy | 0/9 (0%) | 1/9 (11%) | 0/0 | +0.001 |
| BN_native_all | content | 0/9 (0%) | 0/9 (0%) | 0/0 | +0.012 |
| BN_native_all | reworded | 0/9 (0%) | 0/9 (0%) | 0/0 | +0.008 |
| E5_all | policy | 1/9 (11%) | 1/9 (11%) | 0/1 | +0.001 |
| E5_all | content | 1/9 (11%) | 0/9 (0%) | 1/1 | +0.012 |
| E5_all | reworded | 1/9 (11%) | 0/9 (0%) | 1/1 | +0.008 |

## Crossed technique (marker as HTML comment, phishing as plain note)

| Detector | marker | phish |
|---|---|---|
| L2ext | 0/68 (0%) | 0/12 (0%) |
| L2b | 0/68 (0%) | 0/12 (0%) |
| L3 | 22/68 (32%) | 6/12 (50%) |
| BN_native | 1/68 (1%) | 1/12 (8%) |
| BN_native_all | 1/68 (1%) | 1/12 (8%) |
| E5_all | 1/68 (1%) | 1/12 (8%) |

RQ1 on chunks: `python -m pilot.phase_2_extension.rq1_chunks` pairs these detectors (needs --with-l3 for the L3 x E5_all pair).
