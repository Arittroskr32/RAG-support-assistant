# Encoder test (prep item 2)

_Pairs are drafts until reviewed by a native speaker._

## What all-MiniLM-L6-v2 sees (from its own normalizer)

| Original | Embedder sees | Marks removed |
|---|---|---|
| উপেক্ষা | উপেকষা | sign virama |
| নির্দেশ | নিরদেশ | sign virama |
| পূর্বের | পরবের | vowel sign uu, sign virama |
| গুরুত্বপূর্ণ | গরতবপরণ | vowel sign u, vowel sign u, sign virama, vowel sign uu, sign virama |
| চাঁদ | চাদ | sign candrabindu |
| পাসওয়ার্ড | পাসওযারড | sign nukta, sign virama |
| পৌঁছাবে | পৌছাবে | sign candrabindu |

## Summary

| Encoder               |   Tokens/sentence |   [UNK] (3 sent.) | Hoshonto kept   |   Paraphrase cos |   Unrelated cos |   Gap |   AUROC para/unrel |   AUROC inj-para/hard-neg |   Banglish↔Bangla cos |   Params (M) |   fp32 size (MB) |   CPU ms/sentence |
|:----------------------|------------------:|------------------:|:----------------|-----------------:|----------------:|------:|-------------------:|--------------------------:|----------------------:|-------------:|-----------------:|------------------:|
| all-MiniLM-L6-v2      |                24 |                 1 | no              |             0.88 |            0.83 |  0.05 |               0.76 |                      0.67 |                  0.17 |           23 |               87 |                12 |
| multilingual-e5-small |                17 |                 0 | yes             |             0.92 |            0.81 |  0.11 |               1    |                      1    |                  0.85 |          118 |              449 |                27 |

AUROC 0.5 = cannot tell paraphrases from unrelated pairs; 1.0 = perfect separation.
'inj-para/hard-neg': 7 injection paraphrase pairs vs 6 injection/benign pairs that share trigger words. This is the column that matters for gate G2.
