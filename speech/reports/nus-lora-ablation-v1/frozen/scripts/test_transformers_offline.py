"""Real local checkpoint inference readiness, not adaptation or a quality comparison."""

import json
import math
import time
from pathlib import Path

import soundfile as sf
import torch
import transformers
from scipy.signal import resample_poly
from transformers import WhisperForConditionalGeneration, WhisperProcessor

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import load_manifest

model_path = Path("/models/whisper-small-transformers")
manifest = json.loads((model_path/"manifest.json").read_text())
for name, expected in manifest["files"].items():
    assert file_hash(model_path/name) == expected, name
rows = load_manifest(Path("/packet/train.jsonl"))
sample = next(row for row in rows if row.sample_id == "4aee8e1b1146f7198df0b6b1593c473a")
assert sample.split == "train" and sample.reference_text is None
audio_path = Path("/audio")/sample.audio_path
assert file_hash(audio_path) == sample.audio_sha256
audio, rate = sf.read(audio_path, dtype="float32")
factor = math.gcd(rate, 16000)
audio = resample_poly(audio, 16000//factor, rate//factor)
assert torch.cuda.is_available()
assert torch.cuda.get_device_capability()[0] >= 7
started = time.perf_counter()
processor = WhisperProcessor.from_pretrained(str(model_path), local_files_only=True)
model = WhisperForConditionalGeneration.from_pretrained(str(model_path), local_files_only=True,
                                                        torch_dtype=torch.float16).cuda().eval()
features = processor(audio, sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
with torch.inference_mode():
    generated = model.generate(input_features=features.input_features.cuda().half(),
                               attention_mask=features.attention_mask.cuda(), task="transcribe",
                               num_beams=5, do_sample=False, max_new_tokens=128)
text = processor.batch_decode(generated, skip_special_tokens=True)[0]
assert text.strip()
report = {"status": "PASS", "check": "offline_local_transformers_real_audio_inference",
          "sample_id": sample.sample_id, "audio_sha256": sample.audio_sha256, "split": "train",
          "repo": manifest["repo"], "revision": manifest["revision"], "manifest_sha256": file_hash(model_path/"manifest.json"),
          "text": text, "transcript_status": "machine", "gpu": torch.cuda.get_device_name(),
          "torch": torch.__version__, "transformers": transformers.__version__, "precision": "float16",
          "elapsed_sec": time.perf_counter()-started, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
          "network_mode": "none", "local_files_only": True,
          "adaptation_executed": False, "quality_evidence": False, "test_data_accessed": False,
          "source_script_in_prompt": False, "candidate_selected": False, "release_promoted": False}
atomic_json(Path("/reports/transformers-offline-real-asr.json"), report)
print(json.dumps(report))
