# Senior's review of the full phase 2 report (25 Oct 2026)

Copied as received, so the final report can answer each point. `README.md` maps every point to the code and to its status.

---

I read the full Phase 2 report (I have treated it as replacing the first one). This is very strong work and it now contains a real thesis result. In English, an instruction in a retrieved document works as well as the user's own request. Translated Bangla instructions are carried out when the user asks (57% on 3B, 92% on 8B) but never from a document (0/102). Qwen, which answers in Bangla, still never followed a translated-Bangla injection. I haven't seen that positive-control design elsewhere.

On my question (does a generator that's better in Bangla follow Bangla injections more?): it isn't answered yet. 27 of Qwen's 31 stack successes are English, which reflects Qwen following instructions better in general. The Qwen stack also used 3B's valid items. So Qwen's own Bangla channel (its 4 valid Banglish items) was never tested. Please rerun the Qwen stack on Qwen's valid set with a per-item breakdown and add a Qwen column to Table 4 (positive control on all TR items).

Three things to fix before writing:

1. Phishing has leaked into the Bangla defence numbers. 4 of the 7 valid Bangla items on 3B are phishing (TR-211, TR-212, BL-212, BN-211). BN_native caught those documents only because they also contain an instruction. The instruction-deleted versions would pass it and still leak. Please run the ~br documents through bangla_serving_bn and report BN_native's results on marker items separately. Also check why TR-212's address survived L8 three times (if it's a phone number in Bangla digits, that's the L8 gap we discussed). A deterministic check that contact details in answers match an official list is now well motivated. It's the only control that addresses instruction-free poisoning, and your normalizer already handles Bangla digits.
2. The stack run planted 17 English items at once against 2-3 per Bangla group. So competing notes suppress English much more (0/42 in the stack vs 84% alone). Cheap fix: keep everything indexed but exclude other items' documents at query time.
3. Measure every chunk detector on all 80 phase-2 items, since detection doesn't depend on the generator. BN_native's 6/7 and its 6-25% on held-out phase-1 families are far apart. Add a small paraphrase attack against BN_native, since detectors that match against known attack examples are the easiest to rephrase around.

Design points:

- BN_native's Banglish count is 93, not 102. If the router skipped those chunks, about 9% of Banglish bypasses it. Don't let language detection decide which security check runs. Run the E5 detector on every chunk, with English attack examples and English calibration. Together with L3 on English chunks (3.9% false quarantines), that gives two working detectors on English chunks. That's your RQ1 correlation pair without new attacks. I would make it RQ1 and leave direct injection optional.
- If all 12 phishing items are HTML comments and all 68 markers plain notes, goal and technique are confounded. Please check.
- The Qwen check passes only when pooled. In Bangla, Qwen is 34 points less often correct. In Banglish, neither model ever gave a fully acceptable answer. I would call it "more fluent in Bangla" rather than "Bangla-capable".

Related work: please read MIPIAD (Muhtadi & Tazwar, BUET, arXiv 2605.07269). It covers English/Bangla indirect injection with machine-translated BIPIA templates and reports Bangla attack success close to English (0.26 vs 0.31 averaged over seven models), which contrasts with your large effect. Cite it, drop the "no Bangla indirect-injection dataset" claim and discuss the differences (human-written vs machine-translated items, canaries vs LLM judges, the two controls and Banglish). ResumeShield (arXiv 2609.20188) also compares attacks against the payload-free document, so cite it for the base-rate idea.

After these, I recommend freezing experiments and start writing. This should become a paper. So it's worth raising authorship and a target venue with Khaled Sir early.
