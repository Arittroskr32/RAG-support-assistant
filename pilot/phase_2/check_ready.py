"""Which run.md steps can run now? Lists every input file and says what is missing.

  python -m pilot.phase_2.check_ready
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from pilot.phase_2.common2 import DATA2_DIR, PHASE2_DIR, RESULTS_DIR, ROOT

R = RESULTS_DIR


def count_lines(p: Path) -> int:
    with open(p, encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def n_docs(lang: str) -> int:
    d = DATA2_DIR / "benign_docs" / lang
    return len([p for p in d.glob("*") if p.suffix.lower() in (".md", ".txt")]) if d.exists() else 0


def ollama_up() -> bool:
    try:
        import requests
        return requests.get("http://localhost:11434/api/tags", timeout=3).ok
    except Exception:
        return False


def main() -> None:
    items = PHASE2_DIR / "pilot_items2.jsonl"
    todo = items.exists() and "TODO" in items.read_text(encoding="utf-8")
    checks = [
        ("2", "items file", items.exists() and not todo,
         f"{items.relative_to(ROOT)} still has TODO" if todo else f"{count_lines(items)} items" if items.exists()
         else "missing"),
        ("3", "benign questions (steps 6, 9)", (DATA2_DIR / "benign_questions.jsonl").exists(),
         "pilot/phase_2/data/benign_questions.jsonl"),
        ("3", "benign docs bn / banglish / en (steps 9, 10)",
         min(n_docs("bn"), n_docs("banglish")) > 0,
         f"bn {n_docs('bn')}, banglish {n_docs('banglish')}, en {n_docs('en')} files in pilot/phase_2/data/benign_docs/"),
        ("3", "direct-injection prompts (step 12)", (DATA2_DIR / "direct_injection.jsonl").exists(),
         "pilot/phase_2/data/direct_injection.jsonl"),
        ("5", "items + controls", (R / "all_items2.jsonl").exists(), "results/all_items2.jsonl"),
        ("7", "valid attacks", bool(glob.glob(str(R / "valid_*.json"))),
         ", ".join(Path(p).name for p in glob.glob(str(R / "valid_*.json"))) or "results/valid_<model>.json"),
        ("10", "calibration", (R / "calibration.json").exists(), "results/calibration.json"),
        ("-", "Ollama running", ollama_up(), "http://localhost:11434"),
    ]
    width = max(len(c[1]) for c in checks)
    for step, name, ok, note in checks:
        print(f"{'OK ' if ok else '-- '} step {step:>2}  {name:<{width}}  {note}")
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        e5 = True
    except Exception:
        e5 = False
    print(f"{'OK ' if e5 else '-- '} step  -  {'sentence-transformers (E5)':<{width}}  "
          f"{'installed' if e5 else 'pip install -r requirements.txt'}")
    gens = R / "generations2.jsonl"
    if gens.exists():
        rows = [json.loads(l) for l in open(gens, encoding="utf-8") if l.strip()]
        by = {}
        for r in rows:
            by.setdefault((r["model"], r["phase"]), 0)
            by[(r["model"], r["phase"])] += 1
        print("\ngenerations so far:", ", ".join(f"{m} {p}: {n}" for (m, p), n in sorted(by.items())))


if __name__ == "__main__":
    main()
