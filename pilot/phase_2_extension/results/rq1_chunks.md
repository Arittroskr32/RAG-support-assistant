# RQ1 on chunks: failure correlation of chunk detectors

Source: `detectors_long.csv`, sets attack. Miss = the document was not flagged at the calibrated threshold. CIs resample seed families.

## All languages

| Pair | n docs (families) | miss j | miss k | both miss (expected if independent) | phi [95% CI] | excess joint miss [95% CI] | CMH OR by language | CMH OR by goal | note |
|---|---|---|---|---|---|---|---|---|---|
| L3 x E5_all | 80 (20) | 0.85 | 0.96 | 66 (65.5) | 0.10 [-0.11, 0.42] | 0.007 [-0.010, 0.030] | - (ModuleNotFoundError) | - (ModuleNotFoundError) |  |
| L3 x BN_native_all | 80 (20) | 0.85 | 0.97 | 66 (66.3) | -0.07 [-0.14, -0.05] | -0.004 [-0.014, 0.000] | - (ModuleNotFoundError) | - (ModuleNotFoundError) |  |
| E5_all x BN_native_all | 80 (20) | 0.96 | 0.97 | 77 (75.1) | 0.81 [0.62, 1.00] | 0.024 [0.000, 0.069] | - (ModuleNotFoundError) | - (ModuleNotFoundError) |  |
| L2b x E5_all | 80 (20) | 1.00 | 0.96 | 77 (77.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| L2b x L3 | 80 (20) | 1.00 | 0.85 | 68 (68.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |

## English documents only

| Pair | n docs (families) | miss j | miss k | both miss (expected if independent) | phi [95% CI] | excess joint miss [95% CI] | CMH OR by language | CMH OR by goal | note |
|---|---|---|---|---|---|---|---|---|---|
| L3 x E5_all | 20 (20) | 0.95 | 1.00 | 19 (19.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| L3 x BN_native_all | 20 (20) | 0.95 | 1.00 | 19 (19.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| E5_all x BN_native_all | 20 (20) | 1.00 | 1.00 | 20 (20.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| L2b x E5_all | 20 (20) | 1.00 | 1.00 | 20 (20.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |
| L2b x L3 | 20 (20) | 1.00 | 0.95 | 19 (19.0) | nan [nan, nan] | 0.000 [0.000, 0.000] | - | - | phi undefined: a detector never or always misses here |

Reading guide: phi > 0 with a CI above 0 means the two detectors tend to miss the SAME documents (less protection from stacking them than their separate miss rates suggest). Compare a same-artifact pair here with the cross-artifact pairs (a chunk detector x L8/contact check on answers) from the stack runs before claiming that different artifacts fail more independently.
