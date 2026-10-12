"""Phase-2 tests reuse the repository's fixtures (tests/conftest.py): an in-memory Chroma with a
hashing embedder, a fake guardrail and fake LLM backends. No model, GPU or Ollama is needed."""
import hashlib
import math
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.conftest import (FakeGuardrail, FakeKB, FakeLocalLLM, built_kb4, fake_guardrail,  # noqa: E402,F401
                            fake_kb, fake_local_llm)


class FakeE5:
    """Deterministic stand-in for multilingual-E5-small: hashed bag of words over any script.
    Records the prefixes it was called with."""

    def __init__(self, dim: int = 128):
        self.dim, self.prefixes = dim, []

    def encode(self, texts, prefix):
        self.prefixes.append(prefix)
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in re.findall(r"\w+", t.lower()):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


@pytest.fixture
def fake_e5():
    from pilot.phase_2 import bn_route
    e = FakeE5()
    bn_route.set_e5(e)
    yield e
    bn_route.set_e5(None)
