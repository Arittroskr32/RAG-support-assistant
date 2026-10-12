# Truncation check

Source: `pilot/phase_1/results-pilot-v1/generations.jsonl` (672 generations without error).

## 1. Answers cut off

`unfinished_%` is a heuristic (no sentence-final punctuation). These runs have no `finish` field, so the heuristic is all there is.

| model       | config     | group      |   n |   median_chars |   unfinished_% |   success_% |
|:------------|:-----------|:-----------|----:|---------------:|---------------:|------------:|
| llama3.1:8b | fenced     | banglish   |  48 |          103   |              0 |          12 |
| llama3.1:8b | fenced     | english    |  48 |          142.5 |              0 |          44 |
| llama3.1:8b | fenced     | native     |  24 |          120   |              0 |           0 |
| llama3.1:8b | fenced     | translated |  48 |           92.5 |              0 |           8 |
| llama3.1:8b | undefended | banglish   |  48 |          121   |              0 |          23 |
| llama3.1:8b | undefended | english    |  48 |          149   |              0 |          62 |
| llama3.1:8b | undefended | native     |  24 |          124   |              0 |           0 |
| llama3.1:8b | undefended | translated |  48 |          127   |              2 |          17 |
| llama3.2:3b | fenced     | banglish   |  48 |          219.5 |              2 |          23 |
| llama3.2:3b | fenced     | english    |  48 |          184   |              0 |          67 |
| llama3.2:3b | fenced     | native     |  24 |          186   |              8 |          12 |
| llama3.2:3b | fenced     | translated |  48 |          162.5 |              2 |          12 |
| llama3.2:3b | undefended | banglish   |  48 |          170.5 |              4 |          29 |
| llama3.2:3b | undefended | english    |  48 |          187   |              0 |          73 |
| llama3.2:3b | undefended | native     |  24 |          173   |              4 |          12 |
| llama3.2:3b | undefended | translated |  48 |          179   |              8 |          19 |

### Marker goals: successes among finished vs unfinished answers

If unfinished answers almost never succeed, truncation may be hiding the canary.

| model       | group      | unfinished=False   | unfinished=True   |
|:------------|:-----------|:-------------------|:------------------|
| llama3.1:8b | banglish   | 2/42               | –                 |
| llama3.1:8b | english    | 30/42              | –                 |
| llama3.1:8b | native     | 0/36               | –                 |
| llama3.1:8b | translated | 4/42               | –                 |
| llama3.2:3b | banglish   | 12/41              | 1/1               |
| llama3.2:3b | english    | 35/42              | –                 |
| llama3.2:3b | native     | 3/33               | 1/3               |
| llama3.2:3b | translated | 0/41               | 1/1               |

## 2. Prompt length vs context window

Counted with Ollama `llama3.2:3b` (prompt_eval_count) (system + documents + question).

| group      | fenced   |   median |   max |
|:-----------|:---------|---------:|------:|
| banglish   | False    |    213   |   234 |
| banglish   | True     |    306.5 |   342 |
| english    | False    |    198   |   223 |
| english    | True     |    291.5 |   318 |
| native     | False    |    632.5 |   714 |
| native     | True     |    718   |   797 |
| translated | False    |    525.5 |   687 |
| translated | True     |    618   |   780 |

Prompts longer than num_ctx=2048: **0**
