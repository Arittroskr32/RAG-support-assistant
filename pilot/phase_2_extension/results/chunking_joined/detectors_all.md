# Chunk detectors on every phase-2 document

Chunking of attack documents: `joined` (see `chunks_of`).

Thresholds: L2b 0.6149 and BN_native 0.8922 from `calibration.json` (phase 2); E5_all 0.8915 (strictest per-language threshold at 2%: {'en': 0.878, 'bn': 0.8914, 'banglish': 0.8915}; attack KB 56 phase-1 payloads, all languages).

## False quarantines on benign chunks

| Detector | en | bn | banglish |
|---|---|---|---|
| L2ext | 0/102 (0%) | 0/102 (0%) | 0/102 (0%) |
| L2b | 5/102 (5%) | 0/102 (0%) | 1/102 (1%) |
| BN_native | - (of 102; 102 not scanned) | 2/102 (2%) | 1/93 (1%) (of 102; 9 not scanned) |
| BN_native_all | 0/102 (0%) | 2/102 (2%) | 1/102 (1%) |
| E5_all | 0/102 (0%) | 2/102 (2%) | 2/102 (2%) |

Router: 9 Banglish and 0 Bangla benign chunks are routed as English, so router-gated BN_native never sees them.

## Attack documents flagged (all 80 phase-2 items; not-scanned counts as missed)

| Detector | EN | TR | BL | NT |
|---|---|---|---|---|
| L2ext | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) |
| L2b | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) |
| BN_native | 0/20 (0%) | 1/20 (5%) | 6/20 (30%) | 1/20 (5%) |
| BN_native_all | 0/20 (0%) | 1/20 (5%) | 6/20 (30%) | 1/20 (5%) |
| E5_all | 4/20 (20%) | 2/20 (10%) | 6/20 (30%) | 1/20 (5%) |

By goal:

| Detector | marker | phish |
|---|---|---|
| L2ext | 0/68 (0%) | 0/12 (0%) |
| L2b | 0/68 (0%) | 0/12 (0%) |
| BN_native | 5/68 (7%) | 3/12 (25%) |
| BN_native_all | 5/68 (7%) | 3/12 (25%) |
| E5_all | 10/68 (15%) | 3/12 (25%) |

## Instruction-deleted documents (~br): would an instruction detector stop poisoning?

| Detector | EN | TR | BL | NT |
|---|---|---|---|---|
| L2ext | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| L2b | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| BN_native | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 1/3 (33%) |
| BN_native_all | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 1/3 (33%) |
| E5_all | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 1/3 (33%) |

## Paraphrase attack against the example-matching detectors

| Detector | Style | Originals flagged | Paraphrases flagged | Evaded (of flagged originals) | Mean score drop |
|---|---|---|---|---|---|
| BN_native | policy | 1/9 (11%) | 1/9 (11%) | 0/1 | -0.001 |
| BN_native | content | 1/9 (11%) | 0/9 (0%) | 1/1 | +0.013 |
| BN_native | reworded | 1/9 (11%) | 1/9 (11%) | 0/1 | +0.004 |
| BN_native_all | policy | 1/9 (11%) | 1/9 (11%) | 0/1 | -0.001 |
| BN_native_all | content | 1/9 (11%) | 0/9 (0%) | 1/1 | +0.013 |
| BN_native_all | reworded | 1/9 (11%) | 1/9 (11%) | 0/1 | +0.004 |
| E5_all | policy | 1/9 (11%) | 1/9 (11%) | 0/1 | -0.001 |
| E5_all | content | 1/9 (11%) | 0/9 (0%) | 1/1 | +0.013 |
| E5_all | reworded | 1/9 (11%) | 1/9 (11%) | 0/1 | +0.004 |

## Crossed technique (marker as HTML comment, phishing as plain note)

| Detector | marker | phish |
|---|---|---|
| L2ext | 0/68 (0%) | 0/12 (0%) |
| L2b | 0/68 (0%) | 0/12 (0%) |
| BN_native | 4/68 (6%) | 3/12 (25%) |
| BN_native_all | 5/68 (7%) | 3/12 (25%) |
| E5_all | 9/68 (13%) | 4/12 (33%) |

RQ1 on chunks: `python -m pilot.phase_2_extension.rq1_chunks` pairs these detectors (needs --with-l3 for the L3 x E5_all pair).
