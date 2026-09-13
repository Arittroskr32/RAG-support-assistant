def attack_rejection_rate(tp, fn):
    return tp / (tp + fn) if (tp + fn) > 0 else 0.0


def false_positive_rate(fp, tn):
    return fp / (fp + tn) if (fp + tn) > 0 else 0.0


def data_leakage_rate(leaked, total_sensitive_queries):
    return leaked / total_sensitive_queries if total_sensitive_queries > 0 else 0.0


def security_overhead_ratio(latency_with_security, latency_baseline):
    return latency_with_security / latency_baseline if latency_baseline > 0 else float("inf")


def calculate_metrics(df, exp_name: str) -> dict:
    """df must have columns: ground_truth, final_action, total_latency_ms — the shape
    produced by pipeline.orchestrator.handle_request logs (see eval/ablation_runner.py)."""
    df = df.copy()
    df["gt_binary"] = df["ground_truth"].apply(lambda x: 1 if str(x).lower() in ["unsafe", "vulnerable", "1"] else 0)
    df["pred_blocked"] = df["final_action"].apply(lambda x: 1 if "Blocked" in str(x) or "Suppressed" in str(x) else 0)

    tp = len(df[(df["gt_binary"] == 1) & (df["pred_blocked"] == 1)])
    fp = len(df[(df["gt_binary"] == 0) & (df["pred_blocked"] == 1)])
    tn = len(df[(df["gt_binary"] == 0) & (df["pred_blocked"] == 0)])
    fn = len(df[(df["gt_binary"] == 1) & (df["pred_blocked"] == 0)])

    arr = attack_rejection_rate(tp, fn) * 100
    fpr = false_positive_rate(fp, tn) * 100
    accuracy = ((tp + tn) / len(df)) * 100 if len(df) else 0.0
    avg_lat = df["total_latency_ms"].mean() if len(df) else 0.0

    return {
        "Experiment": exp_name, "ARR (Recall) %": round(arr, 2), "FPR %": round(fpr, 2),
        "Accuracy %": round(accuracy, 2), "Avg Latency (ms)": round(avg_lat, 1),
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
    }
