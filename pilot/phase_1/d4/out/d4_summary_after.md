# D4 latency by blocking layer (after)

Source: client wall-clock. Plot: `d4_latency_by_layer_after.png`

| group       |   n |   median |    p25 |    p75 |    min |    max |
|:------------|----:|---------:|-------:|-------:|-------:|-------:|
| L3          |  15 |     1508 |   1507 |   1515 |   1506 |   2716 |
| L2          |   6 |     1509 |   1507 |   1540 |   1506 |   1823 |
| KB2         |  30 |     1510 |   1507 |   1817 |   1506 |   6014 |
| L8 redacted |   6 |    14966 |  12806 |  30919 |  12022 |  66905 |
| not blocked |  49 |    17422 |  11278 |  46882 |   7939 | 331081 |
| L7-error    |   8 |   192024 | 188673 | 195818 | 186559 | 243335 |

## Can an attacker tell the layer from latency? (threat row 9)

| Question | Attacker accuracy | Guess-the-majority baseline |
|---|---|---|
| Which layer fired | 68% | 43% |
| Was an answer generated before the decision | 98% | 52% |

Accuracy well above the baseline = side channel demonstrated.

WARNING: requests failed inside the pipeline (L7-error); these are not blocks. An L5-error usually means KB-4 was rebuilt while the API was running: restart the API and re-run d4_traffic.py.