# Retrieval quality per language (top-6, role customer)

| Language | Embedder | n | Recall@1 | Recall@6 | MRR | Routed to E5 |
|---|---|---|---|---|---|---|
| banglish | e5 | 12 | 0.67 | 0.83 | 0.72 | 75% |
| banglish | e5-tagged | 12 | 0.58 | 1.00 | 0.75 | 75% |
| banglish | minilm | 12 | 0.75 | 0.83 | 0.77 | 75% |
| bn | e5 | 12 | 0.75 | 1.00 | 0.84 | 100% |
| bn | e5-tagged | 12 | 0.58 | 1.00 | 0.72 | 100% |
| bn | minilm | 12 | 0.08 | 0.08 | 0.08 | 100% |
| en | e5 | 6 | 1.00 | 1.00 | 1.00 | 0% |
| en | e5-tagged | 6 | 1.00 | 1.00 | 1.00 | 0% |
| en | minilm | 6 | 1.00 | 1.00 | 1.00 | 0% |

Routed to E5 = share of questions the Bangla router sends to the E5 route; for English it should be ~0%, for Bangla and Banglish ~100%.
