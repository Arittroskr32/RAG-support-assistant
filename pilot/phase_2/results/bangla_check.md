# Bangla answer check (D2)

| Model | Language | Reviewed | Correct | Same language | Natural | All three | Median latency (s) |
|---|---|---|---|---|---|---|---|
| llama3.2:3b | banglish | 12 | 58% | 8% | 0% | 0% | 5.0 |
| llama3.2:3b | bn | 12 | 92% | 0% | 0% | 0% | 4.8 |
| qwen3:4b-instruct-2507-q4_K_M | banglish | 12 | 92% | 8% | 0% | 0% | 7.4 |
| qwen3:4b-instruct-2507-q4_K_M | bn | 12 | 58% | 100% | 75% | 50% | 12.2 |

Decision rule: Bangla-capable if 'All three' is at least 15 points above the deployed model and 'Correct' is not lower.
