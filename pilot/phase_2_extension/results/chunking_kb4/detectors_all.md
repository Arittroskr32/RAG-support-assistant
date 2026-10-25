# Chunk detectors on every phase-2 document

Chunking of attack documents: `kb4` (see `chunks_of`).

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
| L2b | 4/20 (20%) | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) |
| L3 | 4/20 (20%) | 10/20 (50%) | 5/20 (25%) | 8/20 (40%) |
| BN_native | 0/20 (0%) | 20/20 (100%) | 18/20 (90%) | 20/20 (100%) |
| BN_native_all | 0/20 (0%) | 20/20 (100%) | 19/20 (95%) | 20/20 (100%) |
| E5_all | 18/20 (90%) | 20/20 (100%) | 19/20 (95%) | 20/20 (100%) |

By goal:

| Detector | marker | phish |
|---|---|---|
| L2ext | 0/68 (0%) | 0/12 (0%) |
| L2b | 4/68 (6%) | 0/12 (0%) |
| L3 | 15/68 (22%) | 12/12 (100%) |
| BN_native | 51/68 (75%) | 7/12 (58%) |
| BN_native_all | 51/68 (75%) | 8/12 (67%) |
| E5_all | 68/68 (100%) | 9/12 (75%) |

## Instruction-deleted documents (~br): would an instruction detector stop poisoning?

| Detector | EN | TR | BL | NT |
|---|---|---|---|---|
| L2ext | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| L2b | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| L3 | 2/3 (67%) | 3/3 (100%) | 2/3 (67%) | 3/3 (100%) |
| BN_native | 0/3 (0%) | 1/3 (33%) | 0/3 (0%) | 0/3 (0%) |
| BN_native_all | 0/3 (0%) | 1/3 (33%) | 0/3 (0%) | 0/3 (0%) |
| E5_all | 0/3 (0%) | 1/3 (33%) | 0/3 (0%) | 0/3 (0%) |

## Paraphrase attack against the example-matching detectors

| Detector | Style | Originals flagged | Paraphrases flagged | Evaded (of flagged originals) | Mean score drop |
|---|---|---|---|---|---|
| L3 | policy | 6/9 (67%) | 6/9 (67%) | 0/6 | +0.000 |
| L3 | content | 6/9 (67%) | 6/9 (67%) | 0/6 | +0.000 |
| L3 | reworded | 6/9 (67%) | 6/9 (67%) | 0/6 | +0.000 |
| BN_native | policy | 9/9 (100%) | 7/9 (78%) | 2/9 | +0.005 |
| BN_native | content | 9/9 (100%) | 3/9 (33%) | 6/9 | +0.024 |
| BN_native | reworded | 9/9 (100%) | 7/9 (78%) | 2/9 | +0.014 |
| BN_native_all | policy | 9/9 (100%) | 7/9 (78%) | 2/9 | +0.005 |
| BN_native_all | content | 9/9 (100%) | 3/9 (33%) | 6/9 | +0.023 |
| BN_native_all | reworded | 9/9 (100%) | 7/9 (78%) | 2/9 | +0.011 |
| E5_all | policy | 9/9 (100%) | 7/9 (78%) | 2/9 | +0.005 |
| E5_all | content | 9/9 (100%) | 3/9 (33%) | 6/9 | +0.023 |
| E5_all | reworded | 9/9 (100%) | 7/9 (78%) | 2/9 | +0.011 |

## Crossed technique (marker as HTML comment, phishing as plain note)

| Detector | marker | phish |
|---|---|---|
| L2ext | 0/68 (0%) | 0/12 (0%) |
| L2b | 10/68 (15%) | 0/12 (0%) |
| L3 | 24/68 (35%) | 12/12 (100%) |
| BN_native | 51/68 (75%) | 7/12 (58%) |
| BN_native_all | 51/68 (75%) | 8/12 (67%) |
| E5_all | 68/68 (100%) | 9/12 (75%) |

RQ1 on chunks: `python -m pilot.phase_2_extension.rq1_chunks` pairs these detectors (needs --with-l3 for the L3 x E5_all pair).
