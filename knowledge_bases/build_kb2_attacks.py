"""Populate KB-2 from your train_dataset.jsonl unsafe records. Run once, and again
whenever you add red-team / new-CVE attack patterns (append-only, no retraining needed)."""
import json
import random

from knowledge_bases.kb_manager import kb

TRAIN_PATH = "data/security_datasets/train_dataset.jsonl"   # keep raw benchmark data out of data/ (see ingestion note)
CAP_SIZE = 5000


def build():
    with open(TRAIN_PATH, encoding="utf-8") as f:
        train_data = [json.loads(line) for line in f]
    unsafe = [d for d in train_data if d.get("ground_truth_input") == "unsafe"]
    random.seed(42)
    sample = random.sample(unsafe, min(CAP_SIZE, len(unsafe)))
    texts = [d["input_prompt"] for d in sample]
    embeddings = kb.embed(texts)
    ids = [f"attack_{i}" for i in range(len(texts))]
    for i in range(0, len(texts), 4000):   # Chroma add() cap ~5461/call
        kb.kb2_attacks.add(
            documents=texts[i:i + 4000], embeddings=embeddings[i:i + 4000],
            ids=ids[i:i + 4000], metadatas=[{"source": "train_unsafe"}] * len(texts[i:i + 4000]),
        )
    print(f"KB-2 populated with {len(texts)} attack signatures.")


def append_new_attacks(new_prompts: list[str]):
    """Add newly discovered attacks without touching the base pipeline — this is the
    'zero retraining cost' novelty claim (thesis Section 3.9, Step 5)."""
    embeddings = kb.embed(new_prompts)
    start = kb.kb2_attacks.count()
    ids = [f"attack_new_{start + i}" for i in range(len(new_prompts))]
    kb.kb2_attacks.add(documents=new_prompts, embeddings=embeddings, ids=ids,
                        metadatas=[{"source": "red_team_appended"}] * len(new_prompts))


if __name__ == "__main__":
    build()
