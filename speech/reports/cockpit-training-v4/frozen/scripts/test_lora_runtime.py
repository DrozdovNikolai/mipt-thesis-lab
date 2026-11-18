"""Tiny random model/tensors check PEFT autograd only; no product quality measurements."""

import json
import subprocess
import sys
import tempfile

import peft
import torch
import transformers
from peft import LoraConfig, get_peft_model
from transformers import Seq2SeqTrainer, WhisperConfig, WhisperForConditionalGeneration

from north55_speech.core import atomic_json, settings

assert torch.cuda.is_available(), "CUDA device required"
torch.manual_seed(55)
config = WhisperConfig(
    vocab_size=32,
    num_mel_bins=8,
    d_model=16,
    encoder_layers=1,
    decoder_layers=1,
    encoder_attention_heads=2,
    decoder_attention_heads=2,
    encoder_ffn_dim=32,
    decoder_ffn_dim=32,
    max_source_positions=16,
    max_target_positions=16,
    pad_token_id=0,
    bos_token_id=1,
    eos_token_id=2,
    decoder_start_token_id=1,
    suppress_tokens=[],
    begin_suppress_tokens=[],
)
model = get_peft_model(
    WhisperForConditionalGeneration(config),
    LoraConfig(r=2, lora_alpha=4, target_modules=["q_proj", "v_proj"], bias="none"),
).cuda()
parameters = [p for p in model.parameters() if p.requires_grad]
before = [p.detach().clone() for p in parameters]
optimizer = torch.optim.AdamW(parameters, lr=0.001)
loss = model(
    input_features=torch.randn(1, 8, 32, device="cuda"),
    labels=torch.tensor([[3, 4, 2]], device="cuda"),
).loss
assert torch.isfinite(loss)
loss.backward()
optimizer.step()
assert any(not torch.equal(a, b) for a, b in zip(before, parameters, strict=True))
with tempfile.TemporaryDirectory() as path:
    model.save_pretrained(path)
    merged = model.merge_and_unload()
    assert not any("lora_" in name for name, _ in merged.named_parameters())
report = {
    "status": "PASS",
    "executed": True,
    "gpu": torch.cuda.get_device_name(),
    "torch": torch.__version__,
    "transformers": transformers.__version__,
    "peft": peft.__version__,
    "trainer_import": Seq2SeqTrainer.__name__,
    "finite_loss": True,
    "gradient_update": True,
    "adapter_save_merge": True,
    "fixture": "random_tiny_model_and_tensors",
    "real_asr_adaptation_executed": False,
    "quality_evidence": False,
}
atomic_json(settings.report_root / "lora-runtime.json", report)
print(json.dumps(report))
process = subprocess.run(
    [sys.executable, "-c", "from north55_speech.cli import main; main()", "train", "asr"],
    text=True,
    capture_output=True,
)
print(process.stdout)
assert process.returncode == 5 and "MISSING_TRAIN_DEV_DATA" in process.stdout
