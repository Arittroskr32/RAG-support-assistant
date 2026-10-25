# RQ1 on chunks: failure correlation of chunk detectors

Source: `detectors_long.csv`, sets attack. Miss = the document was not flagged at the calibrated threshold. CIs resample seed families.

## All languages

| Pair | n docs (families) | miss j | miss k | both miss (expected if independent) | phi [95% CI] | excess joint miss [95% CI] | CMH OR by language | CMH OR by goal | note |
|---|---|---|---|---|---|---|---|---|---|
| L3 x E5_all | 80 (20) | 0.66 | 0.04 | 0 (2.0) | -0.28 [-0.42, -0.15] | -0.025 [-0.056, 0.000] | 0.05 (p 0.003) | - |  |
| L3 x BN_native_all | 80 (20) | 0.66 | 0.26 | 16 (13.9) | 0.13 [-0.07, 0.32] | 0.026 [-0.014, 0.066] | 0.10 (p 0.120) | 4.25 (p 0.091) |  |
| E5_all x BN_native_all | 80 (20) | 0.04 | 0.26 | 3 (0.8) | 0.33 [0.19, 0.52] | 0.028 [0.000, 0.070] | 117.00 (p 0.001) | 39.67 (p 0.014) |  |
| L2b x E5_all | 80 (20) | 0.95 | 0.04 | 3 (2.8) | 0.05 [0.02, 0.08] | 0.002 [0.000, 0.005] | 1.55 (p 0.792) | - |  |
| L2b x L3 | 80 (20) | 0.95 | 0.66 | 50 (50.3) | -0.04 [-0.21, 0.20] | -0.004 [-0.024, 0.019] | 1.65 (p 0.666) | 1.49 (p 0.695) |  |

## English documents only

| Pair | n docs (families) | miss j | miss k | both miss (expected if independent) | phi [95% CI] | excess joint miss [95% CI] | CMH OR by language | CMH OR by goal | note |
|---|---|---|---|---|---|---|---|---|---|
| L3 x E5_all | 20 (20) | 0.80 | 0.10 | 0 (1.6) | -0.67 [-1.00, -0.40] | -0.080 [-0.163, 0.000] | 0.03 (p 0.008) | - |  |
| L3 x BN_native_all | 20 (20) | 0.80 | 1.00 | 16 (16.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| E5_all x BN_native_all | 20 (20) | 0.10 | 1.00 | 2 (2.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| L2b x E5_all | 20 (20) | 0.80 | 0.10 | 2 (1.6) | 0.17 [0.08, 0.32] | 0.020 [0.000, 0.052] | 1.55 (p 0.792) | - |  |
| L2b x L3 | 20 (20) | 0.80 | 0.80 | 13 (12.8) | 0.06 [-0.30, 0.58] | 0.010 [-0.050, 0.088] | 1.65 (p 0.666) | 11.57 (p 0.108) |  |

Reading guide: phi > 0 with a CI above 0 means the two detectors tend to miss the SAME documents (less protection from stacking them than their separate miss rates suggest). Compare a same-artifact pair here with the cross-artifact pairs (a chunk detector x L8/contact check on answers) from the stack runs before claiming that different artifacts fail more independently.
