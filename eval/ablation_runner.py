"""Extends the notebook's L2/L2b/L3/L8 ablation flags to also toggle L4/L5 (RBAC filter)
and L6 (context tagging), against the full pipeline built in security/, retrieval/, and
generation/ rather than the notebook's standalone InjectionDetectionPipeline class.

Three experiment families, matching the design doc §10 build-order gap:
  1. detection ablation  — toggle enable_l2/l2b/l3/l8, same shape as the notebook's Step 9.
  2. RBAC leakage (DLR)  — bypass the L4/L5 clearance filter and measure cross-tenant/
                             unauthorized-document leakage.
  3. L6 tagging ablation — strip [DOCUMENT]...[/DOCUMENT] tags before generation and test
                             against document-embedded injection payloads.

Run as a script once data/security_datasets/test_dataset.jsonl exists and KB-2/KB-4/KB-6
are populated; writes CSVs to eval/results/ (gitignored).
"""
import json
import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from config.settings import SecurityThresholds
from eval.metrics import calculate_metrics
from knowledge_bases.kb3_rbac import get_user_scope
from knowledge_bases.kb_manager import kb
from security import l2_pattern_filter, l2b_narrative_guard, l3_llm_guardrail

RESULTS_DIR = Path("eval/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TEST_PATH = "data/security_datasets/test_dataset.jsonl"
ALL_DOCUMENT_TYPES = ["public_faq", "product_info", "company_info", "developer_info", "sales_info"]

_cfg = SecurityThresholds()


def _detect_once(query: str, enable_l2: bool, enable_l2b: bool, enable_l3: bool) -> dict:
    """Runs the detection-only chain (no L4-L8) for one query and returns a log row
    shaped for eval.metrics.calculate_metrics."""
    start = time.perf_counter()
    query_emb = kb.embed(query)[0]

    kb2_res = kb.kb2_attacks.query(query_embeddings=[query_emb], n_results=1)
    min_distance = kb2_res["distances"][0][0] if kb2_res.get("distances") and kb2_res["distances"][0] else 1.0

    if enable_l2 and l2_pattern_filter.matches_known_injection(query):
        return {"final_action": "Blocked at L2", "total_latency_ms": (time.perf_counter() - start) * 1000}

    if enable_l2b and l2b_narrative_guard.is_narrative_jailbreak(query_emb):
        return {"final_action": "Blocked at L2b", "total_latency_ms": (time.perf_counter() - start) * 1000}

    if enable_l3 and l3_llm_guardrail.check(query, min_distance) == "unsafe":
        return {"final_action": "Blocked at L3", "total_latency_ms": (time.perf_counter() - start) * 1000}

    return {"final_action": "Completed", "total_latency_ms": (time.perf_counter() - start) * 1000}


def run_detection_ablation(test_prompts: list[dict], flag_sets: dict[str, dict]) -> pd.DataFrame:
    """flag_sets maps experiment name -> {enable_l2, enable_l2b, enable_l3} (mirrors the
    notebook's Step 9 Full_Pipeline run, generalized to arbitrary flag combinations)."""
    summary_rows = []
    for exp_name, flags in flag_sets.items():
        rows = []
        for item in tqdm(test_prompts, desc=f"Detection ablation: {exp_name}"):
            result = _detect_once(item["input_prompt"], **flags)
            result["ground_truth"] = item.get("ground_truth_input", "unknown")
            rows.append(result)
        df = pd.DataFrame(rows)
        df.to_csv(RESULTS_DIR / f"detection_{exp_name}.csv", index=False)
        summary_rows.append(calculate_metrics(df, exp_name))
    return pd.DataFrame(summary_rows)


def run_rbac_leakage_test(queries: list[str], role: str, tenant_id: str = "default") -> dict:
    """DLR: compares retrieval results under the real RBAC scope vs. a bypassed scope
    (allowed_types=ALL, clearance=999) to count how many chunks above the user's real
    clearance would leak if L4/L5 were disabled."""
    from retrieval.l5_secure_retrieval import secure_search

    real_clearance, real_allowed_types = get_user_scope(role)
    leaked, total = 0, 0

    for query in queries:
        scoped = secure_search(query, real_clearance, real_allowed_types, tenant_id=tenant_id, user_id="dlr-eval")
        bypassed = secure_search(query, 999, ALL_DOCUMENT_TYPES, tenant_id=tenant_id, user_id="dlr-eval")

        scoped_ids = {meta["source_doc_id"] for _, meta in scoped}
        bypassed_over_clearance = [meta for _, meta in bypassed if meta["clearance_level"] > real_clearance]

        total += len(bypassed_over_clearance)
        leaked += sum(1 for meta in bypassed_over_clearance if meta["source_doc_id"] not in scoped_ids)

    from eval.metrics import data_leakage_rate
    dlr = data_leakage_rate(leaked, total) if total else 0.0
    return {"role": role, "leaked_above_clearance": leaked, "total_above_clearance_available": total, "dlr": dlr}


def run_l6_ablation_test(query: str, retrieved: list[tuple], injected_payload: str) -> dict:
    """Reproduces the paper's 'injection risk without L6' comparison: generate once with
    [DOCUMENT] tags (L6 on) and once with raw concatenated chunk text (L6 off), both with
    an injection payload appended to a retrieved chunk, then report both raw answers for
    manual/automated compliance scoring (did the model follow the embedded instruction?)."""
    from generation.l6_context_assembler import tag_context
    from generation.l7_generation import generate_answer

    poisoned = list(retrieved) + [(injected_payload, {"source_doc_id": "injected_chunk"})]

    tagged_context = tag_context(poisoned)
    raw_context = "\n\n".join(text for text, _ in poisoned)

    return {
        "with_l6_tagging": generate_answer(query, tagged_context),
        "without_l6_tagging": generate_answer(query, raw_context),
    }


def main():
    with open(TEST_PATH, encoding="utf-8") as f:
        test_data = [json.loads(line) for line in f]

    flag_sets = {
        "Full_Pipeline": {"enable_l2": True, "enable_l2b": True, "enable_l3": True},
        "No_L2": {"enable_l2": False, "enable_l2b": True, "enable_l3": True},
        "No_L2b": {"enable_l2": True, "enable_l2b": False, "enable_l3": True},
        "No_L3": {"enable_l2": True, "enable_l2b": True, "enable_l3": False},
        "Detection_Off": {"enable_l2": False, "enable_l2b": False, "enable_l3": False},
    }
    summary = run_detection_ablation(test_data, flag_sets)
    summary.to_csv(RESULTS_DIR / "ablation_summary.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
