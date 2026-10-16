# D4: which layer refused, from latency alone (after)

Traffic `pilot/phase_1/d4/out/traffic.csv`, security log `logs/security_events.jsonl`. 114 requests, 51 refused before generation.

| Question | Attacker accuracy | Guess the most common layer |
|---|---|---|
| Which pre-generation layer refused (refused requests only) | 94% | 59% |

Confusion (rows = true layer, columns = guessed):

| true \ guessed | KB2 | L2 | L3 |
|---|---|---|---|
| KB2 | 28 | 0 | 2 |
| L2 | 0 | 6 | 0 |
| L3 | 1 | 0 | 14 |

## Slowest refusals per layer

| Layer | Request n | Client ms | Server total ms | Slowest server step | Previous request took (ms) | Position in traffic |
|---|---|---|---|---|---|---|
| KB2 (outlier) | 111 | 1378 | 1019.294 | L1 982 ms | 30935 | 111 of 114 |
| KB2 (outlier) | 72 | 787 | 780.875 | L1 775 ms | 127 | 72 of 114 |
| KB2 (outlier) | 107 | 343 | 336.619 | L1 332 ms | 10128 | 107 of 114 |
| L2 | 95 | 13 | 0.27 | L2 0 ms | 10368 | 95 of 114 |
| L2 | 25 | 10 | 0.424 | L2 0 ms | 8383 | 25 of 114 |
| L2 | 34 | 8 | 0.321 | L2 0 ms | 8195 | 34 of 114 |
| L3 | 29 | 709 | 700.846 | L3 570 ms | 658 | 29 of 114 |
| L3 | 28 | 658 | 650.667 | L3 625 ms | 29966 | 28 of 114 |
| L3 | 105 | 638 | 632.426 | L3 611 ms | 102 | 105 of 114 |

Outlier rule: above Q3 + 3 x IQR of its own layer. Read the 'slowest server step' column: a slow L0/L1/embedding step on an early request points to a cold start; a slow step right after a long generation points to GPU contention; a slow step inside KB2 itself would be a real KB-2 cost.

Largest refusal latency: 1378 ms; without the flagged outliers: 709 ms. `refusal_min_latency_ms` must be above the largest latency you cannot explain away; generated answers in this run started at 7178 ms.
