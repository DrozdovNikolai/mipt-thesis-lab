"""Actual no-network CPU inference of the saved LoRA/CT2 model; no quality claim."""

import json
from pathlib import Path

import psutil
import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.core import atomic_json, file_hash, settings
from north55_speech.schemas import PipelineConfig

assert sorted(psutil.net_if_addrs()) == ["lo"]
provenance = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
sample = provenance["samples"][0]
path = settings.audio_root / "smoke" / sample["filename"]
assert file_hash(path) == sample["sha256"]
audio, rate = sf.read(path, dtype="float32")
assert rate == 16000 and audio.ndim == 1
provider = AsrProvider(PipelineConfig(model="whisper-small-publisher-lora-v2-ct2", device="cpu", compute_type="int8"))
segments = provider.transcribe(audio, 0, "en", "cpu-adapted", lambda: None)
assert segments and any(s.raw_asr_text.strip() for s in segments)
report = {"status": "PASS", "device": "cpu", "compute_type": "int8", "network": "none",
          "audio_sha256": sample["sha256"], "model_manifest": provider.manifest,
          "segments": [s.model_dump() for s in segments], "quality_evidence": False}
atomic_json(Path("/reports/publisher-weak-v1/adapted-cpu-smoke.json"), report)
print(json.dumps({"status": "PASS", "device": "cpu", "quality_evidence": False}))
