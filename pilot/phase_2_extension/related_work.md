# Related work notes for the final report

Checked against the arXiv pages on 25 Oct 2026. Re-check the exact wording and table numbers in the PDFs before quoting them.

## MIPIAD (arXiv 2605.07269)

Al Muhit Muhtadi and Mostafa Rifat Tazwar (Bangladesh University of Engineering and Technology). *MIPIAD: Multilingual Indirect Prompt Injection Attack Defense with Qwen–TF-IDF Hybrid and Meta-Ensemble Learning.*

**What it is.** Mainly a **detector** paper. XLPID, a Qwen2.5-1.5B LoRA sequence classifier, is combined with TF-IDF features through late fusion, stacking and gradient boosting. Best F1 is 0.9205 (hybrid) and best AUROC 0.9378 (boosting).

**Data.** A synthetic benchmark built from BIPIA templates over five task families (email, table, QA, abstract, code), with over 1.43 M samples. The **Bangla data is machine-translated**: "Translate attack templates from English to Bangla with Meta's NLLB-200", and the task contexts are translated too. There is **no Banglish or code-mixed data**.

**Attack success.** With no defence, the macro average over **seven victim models** is **0.311 for English and 0.260 for Bangla** (their Table 2). With MIPIAD it is 0.212 and 0.202. Success is decided by an **LLM-judge ensemble** with a majority vote (YES/NO/UNKNOWN; ties and minority-YES count as 0). The judge models are not named.

**Their novelty claim.** "Prior work has not united the multilingual and indirect axes into a generalized detection framework." They do not claim to be the first Bangla indirect-injection dataset, but their benchmark is one, so **our "no Bangla indirect-injection dataset exists" claim must go.**

### How our result differs, and why the effect sizes can differ

| | MIPIAD | This thesis |
|---|---|---|
| Bangla items | NLLB-200 machine translation of BIPIA templates | Human-written in four forms: English, translated Bangla, native Bangla, Banglish |
| Code-mixed (Banglish) | none | 20 human-written items |
| Success criterion | LLM-judge ensemble | Planted canary (deterministic), every hit hand-checked |
| Setting | Task contexts (email, table, QA, ...) | Customer-support RAG with the real L6 fence and L7 system prompt |
| Controls | none reported | Positive control (same instruction as the user's request) and base rate (instruction deleted, entity kept) |
| Paired design | — | Same seed family across languages, exact McNemar and sign-flip tests |
| EN vs BN success | 0.31 vs 0.26 (close) | e.g. 3B 72% vs 10% (translated) per run; 0/102 from a document on Llama for translated Bangla |

Candidate explanations to discuss (state them as hypotheses unless tested):

1. **Judge vs canary.** An LLM judge can score a partial or paraphrased compliance as success. A canary needs the exact code. A judge may also be more lenient in Bangla.
2. **Translation artefacts.** NLLB output can keep English structure and imperative patterns that models already recognise. Our translated items were written by people.
3. **Base rates.** Without a base-rate control, a goal the model would partly produce anyway (like repeating an entity) inflates success in every language equally, and that pushes the two rates together. Our phishing result shows how large that effect can be.
4. **Comprehension vs compliance.** Our positive control shows the models do understand the Bangla instruction (Qwen follows it 51/51 times when the user asks) and still decline it from a document. MIPIAD cannot separate the two.
5. **Models and prompts.** Different victim models, and our real system prompt with nonce fencing versus their task prompts.

Suggested sentence: *MIPIAD (Muhtadi & Tazwar, 2026) built an English–Bangla indirect-injection benchmark from NLLB-translated BIPIA templates and found Bangla attack success close to English (0.26 vs 0.31 over seven models, LLM-judged). With human-written items, canary-based success and a positive control, we find a much larger gap: models that carry out a translated-Bangla instruction when the user asks never do so when it arrives in a retrieved document.*

## ResumeShield (arXiv 2609.20188)

Jay Barach. *ResumeShield: Channel Separation and an Open Benchmark for Indirect Prompt Injection in AI Resume Screening.*

- Indirect injection hidden in résumés (invisible text, markup comments, metadata, zero-width characters), with nine concealment techniques and two payload families. One family is known phrasings; the other is an **adaptive attacker who paraphrases to evade filters**.
- **Success means the screening outcome changed** compared with the same résumé without the payload. That is a comparison against the payload-free document, which is the idea behind our base-rate control. Cite it for that, and check the paper body for the exact baseline wording before quoting.
- Channel separation (a fenced, inert data channel) alone removed all measured attack success, while the filters alone left 16.7% effective. Compare this with our L6 fence: in English it gave no protection against marker injections.
- Their adaptive paraphrasing attacker also motivates our small paraphrase attack against BN_native.

## Wording changes the senior asked for

- Drop "no Bangla indirect-injection dataset exists". Say instead that the existing benchmark is machine-translated, judge-scored and has no code-mixed text.
- Call Qwen3-4B **more fluent in Bangla**, not "Bangla-capable" (offline_checks.md §I).
- Report phishing results as instruction-free poisoning, separately from injection, everywhere (offline_checks.md §D).
