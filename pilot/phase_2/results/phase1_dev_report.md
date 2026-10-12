# Phase 2 report

Generations: `pilot/phase_1/results/generations.jsonl`, all phases.

## Run settings

| Model | Config | Phase | Generations | Temperature | Seeds | Think |
|---|---|---|---|---|---|---|
| llama3.1:8b | fenced | dev | 168 | None | not sent | None |
| llama3.1:8b | undefended | dev | 168 | None | not sent | None |
| llama3.2:3b | fenced | dev | 168 | None | not sent | None |
| llama3.2:3b | undefended | dev | 168 | None | not sent | None |

## Success per run (main number) and per item

| Model | Config | Phase | Variant | Group | Runs succeeded (95% CI) | Items succeeded >= 1 run |
|---|---|---|---|---|---|---|
| llama3.1:8b | fenced | dev | attack | BL | 6/48 (12%, 6%–25%) | 2/16 |
| llama3.1:8b | fenced | dev | attack | EN | 21/48 (44%, 31%–58%) | 7/16 |
| llama3.1:8b | fenced | dev | attack | NT | 0/24 (0%, 0%–14%) | 0/8 |
| llama3.1:8b | fenced | dev | attack | TR | 4/48 (8%, 3%–20%) | 2/16 |
| llama3.1:8b | undefended | dev | attack | BL | 11/48 (23%, 13%–37%) | 5/16 |
| llama3.1:8b | undefended | dev | attack | EN | 30/48 (62%, 48%–75%) | 10/16 |
| llama3.1:8b | undefended | dev | attack | NT | 0/24 (0%, 0%–14%) | 0/8 |
| llama3.1:8b | undefended | dev | attack | TR | 8/48 (17%, 9%–30%) | 4/16 |
| llama3.2:3b | fenced | dev | attack | BL | 11/48 (23%, 13%–37%) | 6/16 |
| llama3.2:3b | fenced | dev | attack | EN | 32/48 (67%, 53%–78%) | 13/16 |
| llama3.2:3b | fenced | dev | attack | NT | 3/24 (12%, 4%–31%) | 2/8 |
| llama3.2:3b | fenced | dev | attack | TR | 6/48 (12%, 6%–25%) | 3/16 |
| llama3.2:3b | undefended | dev | attack | BL | 14/48 (29%, 18%–43%) | 7/16 |
| llama3.2:3b | undefended | dev | attack | EN | 35/48 (73%, 59%–83%) | 14/16 |
| llama3.2:3b | undefended | dev | attack | NT | 3/24 (12%, 4%–31%) | 2/8 |
| llama3.2:3b | undefended | dev | attack | TR | 9/48 (19%, 10%–32%) | 6/16 |

## Paired comparison on shared seed families

Family-level: succeeded in >= 1 run. Run-level: difference of per-run rates per family.

| Model | Config | Phase | Pair | Families | Only first | Only second | McNemar exact p | Mean rate diff | Sign test +/- (p) | Sign-flip p |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.1:8b | fenced | dev | EN vs TR | 16 | 5 | 0 | 0.0625 | +0.35 | 6/0 (0.0312) | 0.0312 |
| llama3.1:8b | fenced | dev | EN vs BL | 16 | 6 | 1 | 0.1250 | +0.31 | 6/1 (0.1250) | 0.1250 |
| llama3.1:8b | fenced | dev | TR vs BL | 16 | 1 | 1 | 1.0000 | -0.04 | 1/1 (1.0000) | 1.0000 |
| llama3.1:8b | undefended | dev | EN vs TR | 16 | 6 | 0 | 0.0312 | +0.46 | 8/0 (0.0078) | 0.0078 |
| llama3.1:8b | undefended | dev | EN vs BL | 16 | 6 | 1 | 0.1250 | +0.40 | 9/1 (0.0215) | 0.0273 |
| llama3.1:8b | undefended | dev | TR vs BL | 16 | 3 | 4 | 1.0000 | -0.06 | 3/4 (1.0000) | 0.7188 |
| llama3.2:3b | fenced | dev | EN vs TR | 16 | 11 | 1 | 0.0063 | +0.54 | 13/1 (0.0018) | 0.0038 |
| llama3.2:3b | fenced | dev | EN vs BL | 16 | 9 | 2 | 0.0654 | +0.44 | 12/3 (0.0352) | 0.0197 |
| llama3.2:3b | fenced | dev | TR vs BL | 16 | 2 | 5 | 0.4531 | -0.10 | 3/5 (0.7266) | 0.5000 |
| llama3.2:3b | undefended | dev | EN vs TR | 16 | 8 | 0 | 0.0078 | +0.54 | 12/0 (0.0005) | 0.0005 |
| llama3.2:3b | undefended | dev | EN vs BL | 16 | 7 | 0 | 0.0156 | +0.44 | 9/1 (0.0215) | 0.0059 |
| llama3.2:3b | undefended | dev | TR vs BL | 16 | 3 | 4 | 1.0000 | -0.10 | 3/5 (0.7266) | 0.4453 |

