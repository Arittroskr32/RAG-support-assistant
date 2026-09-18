"""Test fixtures: a real in-memory ChromaDB with a deterministic bag-of-words hashing
embedder (no model download, no GPU), plus fakes for the guardrail LLM and the Claude client."""
import hashlib
import math
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge_bases.kb_manager import COLLECTIONS, KBManager, set_kb  # noqa: E402

DIM = 256


def hash_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeKB(KBManager):
    """KBManager with the real Chroma logic but an ephemeral client and a hashing embedder."""

    def __init__(self):
        chromadb = pytest.importorskip("chromadb")
        self.settings = None
        self.client = chromadb.EphemeralClient()
        self._lock = threading.Lock()
        for name in COLLECTIONS:
            setattr(self, name, self.reset_collection(name))

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [hash_embed(t) for t in texts]


@pytest.fixture
def fake_kb(tmp_path, monkeypatch):
    kb = FakeKB()
    set_kb(kb)
    # keep logs out of the repo
    import security.event_log as ev
    monkeypatch.setattr(ev, "SECURITY_EVENTS_PATH", tmp_path / "security_events.jsonl")
    monkeypatch.setattr(ev, "RETRIEVAL_AUDIT_PATH", tmp_path / "retrieval_audit.jsonl")
    yield kb
    set_kb(None)


class FakeGuardrail:
    def __init__(self, unsafe_words=("bomb",)):
        self.unsafe_words = unsafe_words
        self.calls = 0

    def classify(self, query):
        self.calls += 1
        return "unsafe" if any(w in query.lower() for w in self.unsafe_words) else "safe"


@pytest.fixture
def fake_guardrail():
    from security import l3_llm_guardrail
    g = FakeGuardrail()
    l3_llm_guardrail.set_guardrail(g)
    yield g
    l3_llm_guardrail.set_guardrail(None)


class FakeClaude:
    """Mimics client.messages.create / client.beta.messages.create."""

    def __init__(self, reply="Reset it under Settings [c1].", stop_reason="end_turn", raise_exc=None):
        self.reply, self.stop_reason, self.raise_exc = reply, stop_reason, raise_exc
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        reply = self.reply(kwargs) if callable(self.reply) else self.reply
        return SimpleNamespace(stop_reason=self.stop_reason, model=kwargs["model"],
                               content=[SimpleNamespace(type="text", text=reply)])


@pytest.fixture
def fake_claude(monkeypatch):
    import dataclasses

    from generation import l7_generation
    monkeypatch.setattr(l7_generation, "MODEL_SETTINGS",
                        dataclasses.replace(l7_generation.MODEL_SETTINGS, generation_backend="anthropic"))
    c = FakeClaude()
    l7_generation.set_client(c)
    yield c
    l7_generation.set_client(None)


class FakeLocalLLM:
    """Stands in for an OpenAI-compatible local server (Ollama / LM Studio / llama.cpp)."""

    def __init__(self, reply="Reset it under Settings [c1].", status=200):
        self.reply, self.status, self.calls = reply, status, []

    def post(self, url, headers=None, timeout=None, json=None):
        import httpx
        self.calls.append({"url": url, "headers": headers, "json": json})
        reply = self.reply(json) if callable(self.reply) else self.reply
        body = {"model": json["model"], "choices": [{"message": {"role": "assistant", "content": reply},
                                                       "finish_reason": "stop"}]}
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def fake_local_llm(monkeypatch):
    import dataclasses

    import httpx

    from generation import l7_generation
    monkeypatch.setattr(l7_generation, "MODEL_SETTINGS",
                        dataclasses.replace(l7_generation.MODEL_SETTINGS, generation_backend="local"))
    fake = FakeLocalLLM()
    monkeypatch.setattr(httpx, "post", fake.post)
    return fake


@pytest.fixture
def built_kb4(fake_kb, tmp_path, monkeypatch):
    """KB-4 built from the repo's data/ folder (includes the DLR canaries)."""
    from ingestion import build_kb4
    monkeypatch.setattr(build_kb4, "QUARANTINE_REPORT", tmp_path / "quarantine_report.jsonl")
    build_kb4.build()
    return fake_kb
