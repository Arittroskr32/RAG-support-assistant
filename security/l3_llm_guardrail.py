"""L3: fine-tuned Llama-Guard-3-1B LoRA adapter (SAFE / UNSAFE), plus the separate KB-2
nearest-attack short-circuit.

- The model loads lazily on first use (importing this module is cheap, and nothing loads
  if enable_l3=False).
- 4-bit NF4 on CUDA, full-precision fallback on CPU (bitsandbytes needs a GPU).
- Prompts that fit in `guardrail_max_input_tokens` are tokenized exactly as in
  prompt-injection-test.ipynb, so the measured results still hold. Longer prompts truncate
  the *user text* (keeping its head and tail) instead of cutting off the trailing
  assistant header, which would otherwise make the model continue the prompt instead of
  classifying it.
- generate() is serialized with a lock: FastAPI runs sync endpoints in a thread pool.
"""
import threading

from config.settings import MODEL_SETTINGS, get_thresholds

_PREFIX = "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
_SUFFIX = "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"


class GuardrailModel:
    def __init__(self, settings=MODEL_SETTINGS):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.settings = settings
        self.tokenizer = AutoTokenizer.from_pretrained(settings.guardrail_base_model)
        self.tokenizer.pad_token = self.tokenizer.eos_token

        if torch.cuda.is_available():
            from transformers import BitsAndBytesConfig
            bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                     bnb_4bit_compute_dtype=torch.float16)
            base = AutoModelForCausalLM.from_pretrained(
                settings.guardrail_base_model, quantization_config=bnb, device_map="auto")
        else:
            base = AutoModelForCausalLM.from_pretrained(settings.guardrail_base_model, torch_dtype=torch.float32)
        self.model = PeftModel.from_pretrained(base, settings.guardrail_adapter)
        self.model.eval()
        self._lock = threading.Lock()

    def build_input_ids(self, query: str) -> list[int]:
        tok, max_len = self.tokenizer, self.settings.guardrail_max_input_tokens
        add_special = self.settings.guardrail_add_special_tokens
        full = tok(_PREFIX + query + _SUFFIX, add_special_tokens=add_special)["input_ids"]
        if len(full) <= max_len:
            return full

        bos = [tok.bos_token_id] if add_special and tok.bos_token_id is not None else []
        prefix = tok(_PREFIX, add_special_tokens=False)["input_ids"]
        suffix = tok(_SUFFIX, add_special_tokens=False)["input_ids"]
        body = tok(query, add_special_tokens=False)["input_ids"]
        budget = max(max_len - len(bos) - len(prefix) - len(suffix), 16)
        head = budget // 2
        body = body[:head] + body[len(body) - (budget - head):]
        return bos + prefix + body + suffix

    def classify(self, query: str) -> str:
        torch = self.torch
        ids = self.build_input_ids(query)
        input_ids = torch.tensor([ids], device=self.model.device)
        with self._lock, torch.no_grad():
            out = self.model.generate(input_ids=input_ids, attention_mask=torch.ones_like(input_ids),
                                      max_new_tokens=15, do_sample=False,
                                      pad_token_id=self.tokenizer.eos_token_id, use_cache=True)
        response = self.tokenizer.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True)
        return "unsafe" if "unsafe" in response.lower() else "safe"


_guardrail = None
_guardrail_lock = threading.Lock()


def get_guardrail() -> GuardrailModel:
    global _guardrail
    if _guardrail is None:
        with _guardrail_lock:
            if _guardrail is None:
                _guardrail = GuardrailModel()
    return _guardrail


def set_guardrail(instance) -> None:
    """Swap in a fake classifier (tests) or a pre-loaded one."""
    global _guardrail
    _guardrail = instance


def kb2_match(min_kb2_distance: float, cfg=None) -> bool:
    """Embedding-only short-circuit: the query is (nearly) a known attack from KB-2."""
    cfg = cfg or get_thresholds()
    return min_kb2_distance < cfg.l3_kb_match_threshold


def classify(query: str) -> str:
    return get_guardrail().classify(query)


def check(query: str, min_kb2_distance: float, cfg=None) -> str:
    """Backward-compatible combined check (KB-2 short-circuit, then the LLM). The
    orchestrator calls kb2_match / classify separately so each can be ablated."""
    cfg = cfg or get_thresholds()
    if cfg.enable_kb2_match and kb2_match(min_kb2_distance, cfg):
        return "unsafe"
    return classify(query)
