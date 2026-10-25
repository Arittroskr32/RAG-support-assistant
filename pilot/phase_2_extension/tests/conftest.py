"""Extension tests reuse the repository's fixtures (tests/conftest.py) and phase 2's fake E5:
an in-memory Chroma with a hashing embedder, a fake guardrail and a fake LLM. No model, GPU or Ollama."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.conftest import (FakeGuardrail, FakeKB, FakeLocalLLM, built_kb4, fake_guardrail,  # noqa: E402,F401
                            fake_kb, fake_local_llm)

_spec = importlib.util.spec_from_file_location("phase2_conftest", ROOT / "pilot" / "phase_2" / "tests" / "conftest.py")
_p2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_p2)
FakeE5 = _p2.FakeE5


@pytest.fixture
def fake_e5():
    from pilot.phase_2 import bn_route
    e = FakeE5()
    bn_route.set_e5(e)
    yield e
    bn_route.set_e5(None)
    bn_route.set_prefix_style("standard")
