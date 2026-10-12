"""Plan step E2: retrieval quality for Bangla and Banglish users, MiniLM vs multilingual-E5.

  python -m pilot.phase_2.retrieval_eval
  python -m pilot.phase_2.retrieval_eval --questions pilot/phase_2/data/benign_questions.jsonl --k 6

No attacks here: this measures how well the system SERVES each language. The senior's point
is that today's "protection" of Bangla users comes partly from poor retrieval, so the same
number shows how much of that protection disappears with E5.

Questions file (JSONL), one benign question per line:
  {"qid": "bn-001", "language": "bn", "question": "...", "gold_source": "public_faq/general_faq.md"}
gold_source is the document that answers the question: a path under data/ (as ingestion
names it), or a file under pilot/phase_2/data/benign_docs/<lang>/ written as
"benign_docs/<lang>/<file>". Benign docs are planted into data/public_faq/ for the run (and
removed afterwards), so Bangla questions can be answered from Bangla documents.

For each question and embedder: the rank of the first retrieved chunk from the gold document
among the top-k (RBAC filter of the given role applied, as in L5). Reports Recall@1,
Recall@k and MRR per language, and how often the router sends each language to E5.
"""
from __future__ import annotations

import argparse
import csv
import shutil
from collections import defaultdict
from pathlib import Path

from pilot.phase_2.common2 import DATA2_DIR, RESULTS_DIR, read_jsonl

PLANT_PREFIX = "zz_p2b_"


def planted_name(gold: str) -> str:
    """benign_docs/bn/returns.md -> public_faq/zz_p2b_bn_returns.md"""
    p = Path(gold)
    return f"public_faq/{PLANT_PREFIX}{p.parent.name}_{p.name}"


def gold_id(gold: str) -> str:
    return planted_name(gold) if gold.startswith("benign_docs/") else gold


def plant_benign(benign_dir: Path, data_dir: Path) -> int:
    n = 0
    for lang_dir in sorted(p for p in benign_dir.glob("*") if p.is_dir()):
        for f in sorted(lang_dir.glob("*")):
            if f.suffix.lower() in (".md", ".txt"):
                shutil.copy(f, data_dir / planted_name(f"benign_docs/{lang_dir.name}/{f.name}"))
                n += 1
    return n


def unplant_benign(data_dir: Path) -> None:
    for p in (data_dir / "public_faq").glob(f"{PLANT_PREFIX}*"):
        p.unlink()


def rank_of(sources: list[str], gold: str) -> int | None:
    for i, s in enumerate(sources, 1):
        if s == gold:
            return i
    return None


def summarise(rows: list[dict], k: int) -> list[dict]:
    agg = defaultdict(list)
    for r in rows:
        agg[(r["language"], r["embedder"])].append(r)
    out = []
    for (lang, emb), rs in sorted(agg.items()):
        ranks = [r["rank"] for r in rs]
        out.append({"language": lang, "embedder": emb, "n": len(rs),
                    "recall@1": sum(1 for x in ranks if x == 1) / len(rs),
                    f"recall@{k}": sum(1 for x in ranks if x) / len(rs),
                    "mrr": sum(1 / x for x in ranks if x) / len(rs),
                    "routed_to_e5": sum(r["routed"] for r in rs) / len(rs)})
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(DATA2_DIR / "benign_questions.jsonl"))
    ap.add_argument("--benign-dir", default=str(DATA2_DIR / "benign_docs"))
    ap.add_argument("--k", type=int, default=None, help="top-k (default: retrieval_top_k)")
    ap.add_argument("--role", default="customer")
    ap.add_argument("--embedders", nargs="+", default=["minilm", "e5"], choices=["minilm", "e5"])
    ap.add_argument("--keep-kb", action="store_true", help="do not rebuild KB-4 at the end")
    ap.add_argument("--out-dir", default=str(RESULTS_DIR))
    a = ap.parse_args(argv)

    from config.settings import DATA_DIR, get_thresholds
    from ingestion import build_kb4
    from knowledge_bases.kb_manager import kb
    from pilot.phase_2 import bn_route
    from retrieval.l4_query_rewriter import resolve_scope
    from retrieval.l5_secure_retrieval import build_where

    cfg = get_thresholds()
    k = a.k or cfg.retrieval_top_k
    qs = read_jsonl(a.questions)
    if not qs:
        raise SystemExit(f"no questions in {a.questions}")
    rows = []
    unplant_benign(DATA_DIR)
    try:
        n = plant_benign(Path(a.benign_dir), DATA_DIR) if Path(a.benign_dir).exists() else 0
        print(f"planted {n} benign documents; rebuilding KB-4 (scan on)")
        build_kb4.build(data_dir=DATA_DIR, scan=True)
        if "e5" in a.embedders:
            bn_route.build_e5_collection()
        known = set(m["source_doc_id"] for m in kb.kb4_documents.get(include=["metadatas"])["metadatas"])
        for q in qs:
            gold = gold_id(q["gold_source"])
            if gold not in known:
                print(f"WARNING {q['qid']}: gold_source {q['gold_source']} is not in KB-4 (as {gold})")
            scope = resolve_scope(q["question"], a.role, cfg)
            where = build_where(scope, "default")
            for emb in a.embedders:
                if emb == "minilm":
                    coll, qe = kb.kb4_documents, kb.embed(q["question"])
                else:
                    coll, qe = bn_route.e5_collection(), bn_route.embed_query([q["question"]])
                res = coll.query(query_embeddings=qe, n_results=k, where=where, include=["metadatas", "distances"])
                sources = [m.get("source_doc_id", "") for m in res["metadatas"][0]]
                rows.append({"qid": q["qid"], "language": q["language"], "embedder": emb,
                             "routed": bn_route.is_bangla(q["question"]), "gold": gold,
                             "rank": rank_of(sources, gold), "top_sources": ";".join(sources),
                             "top_distance": round(res["distances"][0][0], 4) if res["distances"][0] else None})
    finally:
        unplant_benign(DATA_DIR)
        if not a.keep_kb:
            print("restoring KB-4 without the benign documents ...")
            build_kb4.build(data_dir=DATA_DIR, scan=True)

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "retrieval_eval.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summ = summarise(rows, k)
    md = [f"# Retrieval quality per language (top-{k}, role {a.role})", "",
          f"| Language | Embedder | n | Recall@1 | Recall@{k} | MRR | Routed to E5 |", "|---|---|---|---|---|---|---|"]
    for s in summ:
        md.append(f"| {s['language']} | {s['embedder']} | {s['n']} | {s['recall@1']:.2f} | {s[f'recall@{k}']:.2f} | "
                  f"{s['mrr']:.2f} | {s['routed_to_e5']:.0%} |")
    md += ["", "Routed to E5 = share of questions the Bangla router sends to the E5 route; for English it "
               "should be ~0%, for Bangla and Banglish ~100%."]
    (out / "retrieval_eval.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
