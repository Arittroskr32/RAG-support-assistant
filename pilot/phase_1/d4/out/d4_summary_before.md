# D4 latency by blocking layer (before)

Source: client wall-clock. Plot: `d4_latency_by_layer_before.png`

| group       |   n |   median |   p25 |   p75 |   min |   max |
|:------------|----:|---------:|------:|------:|------:|------:|
| L2          |   6 |        7 |     7 |     9 |     5 |    13 |
| KB2         |  30 |       38 |    31 |    91 |    26 |  1378 |
| L3          |  15 |      458 |   442 |   586 |   282 |   709 |
| not blocked |  56 |    11865 |  8489 | 20249 |  7178 | 53242 |
| L8 redacted |   7 |    12536 | 10882 | 13082 | 10178 | 37202 |

## Can an attacker tell the layer from latency? (threat row 9)

| Question | Attacker accuracy | Guess-the-majority baseline |
|---|---|---|
| Which layer fired | 86% | 49% |
| Was an answer generated before the decision | 100% | 55% |

Accuracy well above the baseline = side channel demonstrated.