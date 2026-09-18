"""API auth, dataset splits, calibration sweep, rate limiting, windowing, L3 truncation."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

# ------------------------------------------------------------------ API


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import api.auth as auth
    import api.main as main
    from config.settings import APISettings

    keys = tmp_path / "api_keys.yaml"
    keys.write_text(json.dumps({"users": [{"user_id": "alice", "role": "employee", "tenant_id": "acme",
                                           "key_sha256": auth.hash_key("secret-key")}]}))
    settings = APISettings(api_keys_file=keys, allow_anonymous=True)
    monkeypatch.setattr(auth, "API_SETTINGS", settings)
    monkeypatch.setattr(main, "API_SETTINGS", settings)
    calls = []

    def fake_handle(**kw):
        calls.append(kw)
        return SimpleNamespace(status_code=200, public=lambda expose=False: {"response": "ok"})
    monkeypatch.setattr(main, "handle_request", fake_handle)
    return TestClient(main.app), calls   # not used as a context manager -> lifespan (model warm-up) skipped


def test_role_in_body_is_rejected(api_client):
    client, _ = api_client
    assert client.post("/chat", json={"query": "hi", "role": "admin"}).status_code == 422


def test_identity_comes_from_api_key(api_client):
    client, calls = api_client
    assert client.post("/chat", json={"query": "hi"}, headers={"X-API-Key": "secret-key"}).status_code == 200
    assert (calls[-1]["role"], calls[-1]["tenant_id"], calls[-1]["session_id"]) == ("employee", "acme", "user:alice")
    assert client.post("/chat", json={"query": "hi"}, headers={"X-API-Key": "wrong"}).status_code == 401
    client.post("/chat", json={"query": "hi"})
    assert calls[-1]["role"] == "public" and calls[-1]["session_id"].startswith("ip:")


def test_query_length_limit(api_client):
    client, _ = api_client
    assert client.post("/chat", json={"query": "x" * 5000}).status_code == 422

# ------------------------------------------------------------------ splits


def test_splits_are_disjoint(tmp_path, monkeypatch):
    import eval.splits as splits
    train = [{"input_prompt": f"u{i}", "ground_truth_input": "unsafe"} for i in range(100)] + \
            [{"input_prompt": f"s{i}", "ground_truth_input": "safe"} for i in range(50)]
    test = [{"input_prompt": f"t{i}", "ground_truth_input": "safe"} for i in range(40)]
    for name, rows in (("train.jsonl", train), ("test.jsonl", test)):
        (tmp_path / name).write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(splits, "TRAIN_PATH", tmp_path / "train.jsonl")
    monkeypatch.setattr(splits, "TEST_PATH", tmp_path / "test.jsonl")
    monkeypatch.setattr(splits, "SPLITS_PATH", tmp_path / "splits.json")
    splits.get_splits.cache_clear()
    s = splits.get_splits()
    splits.get_splits.cache_clear()
    kb2 = {d["_idx"] for d in s["kb2"]}
    holdout = {d["_idx"] for d in s["calib_unsafe_holdout"]}
    assert kb2 and holdout and not kb2 & holdout and len(kb2) == 85
    calib, ev = {d["_idx"] for d in s["calib_test"]}, {d["_idx"] for d in s["eval_test"]}
    assert not calib & ev and len(calib) + len(ev) == 40

# ------------------------------------------------------------------ calibration


def test_joint_sweep_respects_combined_fpr():
    from eval.calibrate_thresholds import _rates, joint_sweep
    rng = np.random.default_rng(0)
    labels = np.array([True] * 200 + [False] * 800)
    kb2 = np.where(labels, rng.uniform(0.05, 0.5, 1000), rng.uniform(0.2, 0.9, 1000))
    kb6 = np.where(labels, rng.uniform(0.1, 0.6, 1000), rng.uniform(0.3, 0.9, 1000))
    base = np.zeros(1000, dtype=bool)
    t2, t6, recall, fpr = joint_sweep(kb2, kb6, base, labels, target_fpr=0.05)
    assert fpr <= 0.05
    assert _rates((kb2 < t2) | (kb6 < t6), labels) == (recall, fpr)

# ------------------------------------------------------------------ KB-1 / windowing


def test_rate_counter_counts_bursts_within_one_second(monkeypatch):
    from knowledge_bases import kb1_session_log as k
    monkeypatch.setattr(k, "REDIS_AVAILABLE", False)
    counts = [k.record_request("burst-session") for _ in range(100)]
    assert counts[-1] == 100


def test_split_windows_covers_long_text():
    from knowledge_bases.kb_manager import split_windows
    assert split_windows("short text", 150, 100) == ["short text"]
    words = [f"w{i}" for i in range(400)]
    windows = split_windows(" ".join(words), 150, 100)
    assert windows[-1].split()[-1] == "w399" and all(len(w.split()) <= 150 for w in windows)

# ------------------------------------------------------------------ L3 prompt construction


class _Tok:
    """Whitespace 'tokenizer' with a BOS token, enough to test truncation logic."""
    bos_token_id = 0

    def __call__(self, text, add_special_tokens=True):
        ids = [hash(w) % 1000 + 1 for w in text.split(" ")]
        return {"input_ids": ([0] if add_special_tokens else []) + ids}


def test_l3_long_prompt_keeps_assistant_header():
    from config.settings import ModelSettings
    from security.l3_llm_guardrail import _SUFFIX, GuardrailModel
    g = GuardrailModel.__new__(GuardrailModel)
    g.tokenizer, g.settings = _Tok(), ModelSettings(guardrail_max_input_tokens=64)
    suffix_ids = _Tok()(_SUFFIX, add_special_tokens=False)["input_ids"]

    short = g.build_input_ids("hello there")
    assert short == _Tok()(_PREFIX_FOR_TEST() + "hello there" + _SUFFIX)["input_ids"]  # identical to notebook path

    ids = g.build_input_ids(" ".join(["filler"] * 500) + " FINAL_PAYLOAD")
    assert len(ids) <= 64 and ids[-len(suffix_ids):] == suffix_ids
    assert _Tok()("FINAL_PAYLOAD", add_special_tokens=False)["input_ids"][0] in ids   # tail kept


def _PREFIX_FOR_TEST():
    from security.l3_llm_guardrail import _PREFIX
    return _PREFIX
