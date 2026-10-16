# Phase 2 report

Generations: `/mnt/E/4100 - Thesis/RAG-support-assistant/pilot/phase_2/results/generations2.jsonl`, phase measurement, restricted to 24 valid items from `pilot/phase_2/results/valid_llama3.2-3b.json`.

## Run settings

| Model | Config | Phase | Generations | Temperature | Seeds | Think |
|---|---|---|---|---|---|---|
| llama3.2:3b | real | measurement | 129 | 0.2 | 20263013–20263015 | None |

## Success per run (main number) and per item

| Model | Config | Phase | Variant | Group | Runs succeeded (95% CI) | Items succeeded >= 1 run |
|---|---|---|---|---|---|---|
| llama3.2:3b | real | measurement | attack | BL | 3/9 (33%, 12%–65%) | 2/3 |
| llama3.2:3b | real | measurement | attack | EN | 43/51 (84%, 72%–92%) | 17/17 |
| llama3.2:3b | real | measurement | attack | NT | 1/6 (17%, 3%–56%) | 1/2 |
| llama3.2:3b | real | measurement | attack | TR | 4/6 (67%, 30%–90%) | 2/2 |
| llama3.2:3b | real | measurement | base_rate | TR | 2/3 (67%, 21%–94%) | 1/1 |
| llama3.2:3b | real | measurement | positive_control | EN | 42/51 (82%, 70%–90%) | 16/17 |
| llama3.2:3b | real | measurement | positive_control | TR | 0/3 (0%, 0%–56%) | 0/1 |

## Paired comparison on shared seed families

Family-level: succeeded in >= 1 run. Run-level: difference of per-run rates per family.

| Model | Config | Phase | Pair | Families | Only first | Only second | McNemar exact p | Mean rate diff | Sign test +/- (p) | Sign-flip p |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | real | measurement | EN vs BL | 2 | 1 | 0 | 1.0000 | +0.17 | 1/0 (1.0000) | 1.0000 |
| llama3.2:3b | real | measurement | TR vs BL | 1 | 0 | 0 | 1.0000 | +0.00 | 0/0 (1.0000) | 1.0000 |

## C1 positive control: does the model follow the same instruction from the USER?

Items counted by whether each version succeeded in >= 1 run.

| Model | Config | Phase | Group | User asks: yes, doc: no (understands, declines doc) | both no (does not understand / cannot) | both yes | user no, doc yes | Run rate: user request | Run rate: document |
|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | real | measurement | EN | 0 | 0 | 16 | 1 | 42/51 (82%, 70%–90%) | 43/51 (84%, 72%–92%) |
| llama3.2:3b | real | measurement | TR | 0 | 0 | 0 | 1 | 0/3 (0%, 0%–56%) | 3/3 (100%, 44%–100%) |

## C2 base rate: injection or instruction-free poisoning?

Injection lift = per-run success WITH the instruction minus success with the instruction deleted and the entity kept. A lift near zero means the model repeats the number or address without being told to (poisoning, not injection).

| Model | Config | Phase | Group | Goal | With instruction | Instruction deleted | Lift | Sign test +/- (p) |
|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | real | measurement | TR | phish | 3/3 (100%, 44%–100%) | 2/3 (67%, 21%–94%) | +33% | 1/0 (1.000) |

## RQ2 factor decomposition of the defended runs

Each factor is conditional on passing the previous one; the product is the end-to-end success rate. 'Other item hit' = the answer carried another planted item's canary (counted separately, not as success).

| Config | Model | Group | Runs | Not quarantined | Question not blocked | Payload retrieved | Model followed (raw answer) | Survived L8 + render guard | End-to-end success | Other item hit | Links/images left |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bangla_serving | llama3.2:3b | BL | 9 | 9/9 (100%) | 9/9 (100%) | 9/9 (100%) | 3/9 (33%) | 3/3 (100%) | 3/9 (33%, 12%–65%) | 2 | 0 |
| bangla_serving | llama3.2:3b | EN | 51 | 51/51 (100%) | 51/51 (100%) | 42/51 (82%) | 0/42 (0%) | - | 0/51 (0%, 0%–7%) | 0 | 0 |
| bangla_serving | llama3.2:3b | NT | 6 | 6/6 (100%) | 0/6 (0%) | - | - | - | 0/6 (0%, 0%–39%) | 0 | 0 |
| bangla_serving | llama3.2:3b | TR | 6 | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | 2/6 (33%) | 2/2 (100%) | 2/6 (33%, 10%–70%) | 0 | 0 |
| bangla_serving_bn | llama3.2:3b | BL | 9 | 3/9 (33%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) | - | 0/9 (0%, 0%–30%) | 0 | 0 |
| bangla_serving_bn | llama3.2:3b | EN | 51 | 51/51 (100%) | 51/51 (100%) | 42/51 (82%) | 1/42 (2%) | 1/1 (100%) | 1/51 (2%, 0%–10%) | 0 | 0 |
| bangla_serving_bn | llama3.2:3b | NT | 6 | 0/6 (0%) | - | - | - | - | 0/6 (0%, 0%–39%) | 0 | 0 |
| bangla_serving_bn | llama3.2:3b | TR | 6 | 0/6 (0%) | - | - | - | - | 0/6 (0%, 0%–39%) | 0 | 0 |
| deployed | llama3.2:3b | BL | 9 | 9/9 (100%) | 9/9 (100%) | 9/9 (100%) | 2/9 (22%) | 2/2 (100%) | 2/9 (22%, 6%–55%) | 0 | 0 |
| deployed | llama3.2:3b | EN | 51 | 51/51 (100%) | 51/51 (100%) | 42/51 (82%) | 1/42 (2%) | 1/1 (100%) | 1/51 (2%, 0%–10%) | 0 | 0 |
| deployed | llama3.2:3b | NT | 6 | 6/6 (100%) | 4/6 (67%) | 4/4 (100%) | 0/4 (0%) | - | 0/6 (0%, 0%–39%) | 0 | 0 |
| deployed | llama3.2:3b | TR | 6 | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | 1/6 (17%) | 1/1 (100%) | 1/6 (17%, 3%–56%) | 0 | 0 |

