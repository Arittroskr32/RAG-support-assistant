"""Prep item 2: what all-MiniLM-L6-v2 does to Bangla, compared with multilingual encoders.

  pip install sentence-transformers matplotlib pandas tabulate
  python pilot/encoder/encoder_test.py                    # all three encoders
  python pilot/encoder/encoder_test.py --models sentence-transformers/all-MiniLM-L6-v2

Writes to pilot/encoder/out/: encoder_results.md, tokens.txt, cosine.csv, hist_<model>.png
Runs on CPU in a few minutes; no GPU needed.
"""
from __future__ import annotations

import argparse
import json
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEFAULT_MODELS = ["sentence-transformers/all-MiniLM-L6-v2",
                  "sentence-transformers/LaBSE",
                  "intfloat/multilingual-e5-small"]
HOSHONTO = "\u09cd"
MARK_WORDS = ["উপেক্ষা", "নির্দেশ", "পূর্বের", "গুরুত্বপূর্ণ", "চাঁদ", "পাসওয়ার্ড", "পৌঁছাবে"]


def prefix(model: str) -> str:
    return "query: " if "e5" in model.lower() else ""


def auroc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(random positive pair scores higher than random negative pair); ties count 0.5."""
    pos, neg = np.asarray(pos)[:, None], np.asarray(neg)[None, :]
    return float(((pos > neg).sum() + 0.5 * (pos == neg).sum()) / (pos.size * neg.size))


def bert_strip(text: str) -> str:
    """Reference replica of BERT uncased pre-processing: lowercase, NFD, drop category Mn."""
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def mark_table(tok) -> list[str]:
    """Show what the real MiniLM normalizer does to words with combining marks."""
    norm = getattr(getattr(tok, "backend_tokenizer", None), "normalizer", None)
    rows = ["| Original | Embedder sees | Marks removed |", "|---|---|---|"]
    for w in MARK_WORDS:
        seen = norm.normalize_str(w) if norm else bert_strip(w)
        lost = [unicodedata.name(c).replace("BENGALI ", "").lower()
                for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) == "Mn"]
        rows.append(f"| {w} | {seen} | {', '.join(lost) or '–'} |")
    return rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--pairs", default=str(HERE / "encoder_pairs.json"))
    a = ap.parse_args(argv)

    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(exist_ok=True)
    data = json.load(open(a.pairs, encoding="utf-8"))
    sets = {k: data[k] for k in ["paraphrase", "unrelated", "hard_negative", "banglish_bangla"]}
    # The hard-negative question is "can the encoder tell an injection paraphrase from a
    # benign sentence that shares its trigger words?", so only INJECTION paraphrases are
    # the positives there (support paraphrases would answer a different question).
    inj = np.array([p.get("kind") == "injection" for p in sets["paraphrase"]])
    if not inj.any():
        raise SystemExit("no paraphrase pair has kind == 'injection'")

    md = ["# Encoder test (prep item 2)", "", "_Pairs are drafts until reviewed by a native speaker._", ""]
    tok_lines, cos_rows, summary = [], [], []

    for name in a.models:
        short = name.split("/")[-1]
        tok = AutoTokenizer.from_pretrained(name)
        if "MiniLM" in name:
            md += ["## What all-MiniLM-L6-v2 sees (from its own normalizer)", "", *mark_table(tok), ""]

        # ---- tokenizer output
        tok_lines.append(f"===== {name}")
        n_tok, n_unk, hos = [], 0, True
        for s in data["tokenizer_sentences"]:
            ids = tok(prefix(name) + s)["input_ids"]
            toks = tok.convert_ids_to_tokens(ids)
            n_tok.append(len(ids))
            n_unk += sum(1 for t in toks if t == tok.unk_token)
            if HOSHONTO in s and not any(HOSHONTO in t for t in toks):
                hos = False
            tok_lines.append(f"{len(ids):>3} tokens | {s}\n      {toks}")

        # ---- similarity
        model = SentenceTransformer(name, device="cpu")
        params = sum(p.numel() for p in model.parameters())
        t0, n_sent = time.perf_counter(), 0
        cos = {}
        for kind, pairs in sets.items():
            A = model.encode([prefix(name) + p["a"] for p in pairs], normalize_embeddings=True)
            B = model.encode([prefix(name) + p["b"] for p in pairs], normalize_embeddings=True)
            n_sent += 2 * len(pairs)
            cos[kind] = (A * B).sum(1)
            for p, c in zip(pairs, cos[kind]):
                cos_rows.append({"model": short, "set": kind, "a": p["a"], "b": p["b"], "cos": float(c)})
        ms = 1000 * (time.perf_counter() - t0) / n_sent

        summary.append({
            "Encoder": short,
            "Tokens/sentence": f"{np.mean(n_tok):.0f}",
            "[UNK] (3 sent.)": n_unk,
            "Hoshonto kept": "yes" if hos else "no",
            "Paraphrase cos": f"{cos['paraphrase'].mean():.2f}",
            "Unrelated cos": f"{cos['unrelated'].mean():.2f}",
            "Gap": f"{cos['paraphrase'].mean() - cos['unrelated'].mean():.2f}",
            "AUROC para/unrel": f"{auroc(cos['paraphrase'], cos['unrelated']):.2f}",
            "AUROC inj-para/hard-neg": f"{auroc(cos['paraphrase'][inj], cos['hard_negative']):.2f}",
            "Banglish↔Bangla cos": f"{cos['banglish_bangla'].mean():.2f}",
            "Params (M)": f"{params / 1e6:.0f}",
            "fp32 size (MB)": f"{params * 4 / 2**20:.0f}",
            "CPU ms/sentence": f"{ms:.0f}",
        })

        plt.figure(figsize=(6, 3.5))
        bins = np.linspace(-0.2, 1.0, 25)
        for kind, label in [("paraphrase", "paraphrase"), ("unrelated", "unrelated"),
                            ("hard_negative", "hard negative")]:
            plt.hist(cos[kind], bins=bins, alpha=0.55, label=label)
        plt.xlabel("cosine similarity")
        plt.ylabel("pairs")
        plt.title(short)
        plt.legend()
        plt.tight_layout()
        plt.savefig(OUT / f"hist_{short}.png", dpi=150)
        plt.close()

    md += ["## Summary", "", pd.DataFrame(summary).to_markdown(index=False), "",
           "AUROC 0.5 = cannot tell paraphrases from unrelated pairs; 1.0 = perfect separation.",
           f"'inj-para/hard-neg': {int(inj.sum())} injection paraphrase pairs vs "
           f"{len(sets['hard_negative'])} injection/benign pairs that share trigger words. "
           "This is the column that matters for gate G2.", ""]
    (OUT / "encoder_results.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "tokens.txt").write_text("\n".join(tok_lines), encoding="utf-8")
    pd.DataFrame(cos_rows).to_csv(OUT / "cosine.csv", index=False)
    print("\n".join(md))


if __name__ == "__main__":
    main()
