"""Populate KB-2 (attack signatures).

Built from the "kb2" split only (eval/splits.py), so the calibration holdout is never
inside KB-2. Red-team attacks appended with `append_new_attacks` are persisted to
data/security_datasets/red_team_appended.jsonl and re-inserted on every rebuild, so a
rebuild never silently drops them.
"""
import hashlib
import json

from eval.splits import RED_TEAM_PATH, get_splits, load_jsonl
from knowledge_bases.kb_manager import kb


def _attack_id(prefix: str, text: str) -> str:
    return f"{prefix}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def build():
    coll = kb.reset_collection("kb2_attacks")
    texts = list(dict.fromkeys(d["input_prompt"] for d in get_splits()["kb2"]))   # dedupe, keep order
    kb.add_batched(coll, ids=[_attack_id("attack", t) for t in texts], documents=texts,
                   embeddings=kb.embed(texts), metadatas=[{"source": "train_unsafe"}] * len(texts))

    red_team = [r["input_prompt"] for r in load_jsonl(RED_TEAM_PATH)] if RED_TEAM_PATH.exists() else []
    if red_team:
        _insert_red_team(red_team)
    print(f"KB-2 populated with {len(texts)} attack signatures (+{len(red_team)} red-team appended).")


def _insert_red_team(prompts: list[str]):
    prompts = list(dict.fromkeys(prompts))
    kb.add_batched(kb.kb2_attacks, ids=[_attack_id("attack_new", p) for p in prompts], documents=prompts,
                   embeddings=kb.embed(prompts), metadatas=[{"source": "red_team_appended"}] * len(prompts),
                   upsert=True)


def append_new_attacks(new_prompts: list[str]):
    """Add newly discovered attacks without retraining anything — the 'zero retraining
    cost' claim (thesis Section 3.9, Step 5). Idempotent: IDs are content hashes."""
    RED_TEAM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RED_TEAM_PATH, "a", encoding="utf-8") as f:
        for p in new_prompts:
            f.write(json.dumps({"input_prompt": p, "ground_truth_input": "unsafe"}) + "\n")
    _insert_red_team(new_prompts)


if __name__ == "__main__":
    build()
