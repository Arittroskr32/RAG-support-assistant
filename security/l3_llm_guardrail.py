import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from config.settings import ModelSettings, SecurityThresholds

_m, _cfg = ModelSettings(), SecurityThresholds()


class GuardrailModel:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                         bnb_4bit_compute_dtype=torch.float16)
        self.tokenizer = AutoTokenizer.from_pretrained(_m.guardrail_base_model)
        self.tokenizer.pad_token = self.tokenizer.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            _m.guardrail_base_model, quantization_config=bnb_config, device_map="auto")
        self.model = PeftModel.from_pretrained(base, _m.guardrail_adapter)   # your fine-tuned adapter
        self.model.eval()

    def classify(self, query: str) -> str:
        prompt = (f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{query}"
                  f"<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=15, do_sample=False,
                                       pad_token_id=self.tokenizer.eos_token_id, use_cache=True)
        response = self.tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return "unsafe" if "unsafe" in response.lower() else "safe"


guardrail = GuardrailModel()   # loads once at import time, reused across every request


def check(query: str, min_kb2_distance: float) -> str:
    if min_kb2_distance < _cfg.l3_kb_match_threshold:
        return "unsafe"
    return guardrail.classify(query)
