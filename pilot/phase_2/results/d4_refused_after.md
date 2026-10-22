# D4: which layer refused, from latency alone (after)

Traffic `pilot/phase_1/d4/out/traffic.csv`, security log `logs/security_events.jsonl`. 114 requests, 51 refused before generation.

| Question | Attacker accuracy | Guess the most common layer |
|---|---|---|
| Which pre-generation layer refused (refused requests only) | 51% | 59% |

Confusion (rows = true layer, columns = guessed):

| true \ guessed | KB2 | L2 | L3 |
|---|---|---|---|
| KB2 | 19 | 5 | 6 |
| L2 | 6 | 0 | 0 |
| L3 | 8 | 0 | 7 |

## Slowest refusals per layer

| Layer | Request n | Client ms | Server total ms | Slowest server step | Previous request took (ms) | Position in traffic |
|---|---|---|---|---|---|---|
| KB2 (outlier) | 104 | 6014 | 5616.048 | L1 5514 ms | 186559 | 104 of 114 |
| KB2 (outlier) | 111 | 5845 | 5428.074 | L1 5318 ms | 188910 | 111 of 114 |
| KB2 (outlier) | 93 | 5769 | 5494.006 | L1 5384 ms | 187963 | 93 of 114 |
| L2 (outlier) | 95 | 1823 | 1500.291 | L2 0 ms | 99112 | 95 of 114 |
| L2 | 75 | 1550 | 1500.112 | L2 0 ms | 15109 | 75 of 114 |
| L2 | 59 | 1510 | 1500.189 | L2 0 ms | 1513 | 59 of 114 |
| L3 (outlier) | 105 | 2716 | 2674.296 | L3 2564 ms | 6014 | 105 of 114 |
| L3 (outlier) | 84 | 2579 | 2539.635 | L3 2473 ms | 1506 | 84 of 114 |
| L3 | 47 | 1519 | 1500.153 | L3 257 ms | 1506 | 47 of 114 |

Outlier rule: above Q3 + 3 x IQR of its own layer. Read the 'slowest server step' column: a slow L0/L1/embedding step on an early request points to a cold start; a slow step right after a long generation points to GPU contention; a slow step inside KB2 itself would be a real KB-2 cost.

Largest refusal latency: 6014 ms; without the flagged outliers: 5060 ms. `refusal_min_latency_ms` must be above the largest latency you cannot explain away; generated answers in this run started at 7939 ms.
