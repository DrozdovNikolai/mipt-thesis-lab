"""Offline CPU ASR on preselected dev recordings; output is an annotation draft.

No test manifest or publisher transcript is opened. This cannot establish WER
improvement, entity preservation, or human event detection quality.
"""

from __future__ import annotations

import json
from pathlib import Path

import psutil
import soundfile as sf

from north55_speech.benchmark import code_hash
from north55_speech.core import atomic_json, digest, file_hash, read_yaml, settings
from north55_speech.datasets import load_manifest
from north55_speech.pipeline import run_pipeline
from north55_speech.schemas import InferenceRequest, PipelineConfig


def main() -> None:
    if sorted(psutil.net_if_addrs()) != ["lo"]:
        raise RuntimeError("Run this development smoke with --network none")
    manifest = Path("/data/train-dev/dev.jsonl")
    samples = load_manifest(manifest)
    if any(sample.split != "dev" for sample in samples):
        raise RuntimeError("Only the development partition is allowed")
    candidates = sorted(
        (sample for sample in samples if sample.source_dataset == "BLeRIOT-A"
         and "checklist" in sample.sample_id.casefold()), key=lambda sample: sample.sample_id,
    )
    if not candidates:
        raise RuntimeError("No dev checklist recording available")
    variants = {sample.variant_of: sample for sample in samples if sample.variant_of}
    # Fixed, reference-free selection: prefer a checklist with its admitted noisy
    # parent linkage; otherwise use the first checklist by sample ID.
    original = next((sample for sample in candidates if sample.sample_id in variants), candidates[0])
    selected = [original]
    if original.sample_id in variants:
        selected.append(variants[original.sample_id])
    baseline = PipelineConfig.model_validate(read_yaml(Path("/app/configs/baseline.yaml")))
    configs = {
        "baseline": baseline,
        "vad": baseline.model_copy(update={"vad": baseline.vad.model_copy(update={"enabled": True})}),
    }
    plan = {
        "purpose": "dev smoke and machine annotation drafts", "test_opened": False,
        "manifest_sha256": file_hash(manifest), "code_hash": code_hash(),
        "selection_rule": "first dev raw checklist with a linked C variant, else first dev checklist",
        "source_ids": [sample.sample_id for sample in selected],
        "clip_start_sec": 30.0, "clip_max_duration_sec": 30.0,
        "configs": {name: config.model_dump() for name, config in configs.items()},
    }
    report_path = settings.report_root / "bleriot-asr-smoke.json"
    if report_path.exists():
        raise ValueError("Smoke report already exists; preserve the previous execution")
    atomic_json(settings.report_root / "bleriot-asr-smoke-plan.json", plan)
    rows = []
    for sample in selected:
        source = settings.audio_root / sample.audio_path
        if file_hash(source) != sample.audio_sha256:
            raise RuntimeError("Imported source checksum changed")
        start = 30.0 if sample.duration_sec > 31 else 0.0
        with sf.SoundFile(source) as stream:
            stream.seek(round(start * stream.samplerate))
            audio = stream.read(round(min(30, sample.duration_sec-start) * stream.samplerate),
                                dtype="float32", always_2d=True)
            rate = stream.samplerate
        clip = settings.audio_root / "development-clips" / f"{digest(sample.sample_id)}.wav"
        clip.parent.mkdir(parents=True, exist_ok=True)
        sf.write(clip, audio[:, sample.channel], rate, subtype="FLOAT")
        request = InferenceRequest(
            sample_id=digest(sample.sample_id), audio_locator=clip.relative_to(settings.audio_root).as_posix(),
            audio_sha256=file_hash(clip), language="auto", channel_mode="separate_channels", audio_channel=0,
        )
        for name, config in configs.items():
            destination = settings.artifact_root / "bleriot-dev-smoke" / digest(sample.sample_id) / name
            destination.mkdir(parents=True, exist_ok=True)
            result = run_pipeline(request, config, destination, lambda stage, fraction: None)
            row = {
                "sample_id": sample.sample_id, "split": "dev", "pipeline": name,
                "source_audio_sha256": sample.audio_sha256, "clip_sha256": request.audio_sha256,
                "original_start_sec": start, "original_end_sec": start + len(audio)/rate,
                "timestamp_mapping": "original seconds = clip seconds + original_start_sec",
                "transcript_status": "machine", "human_verified": False,
                "result": result,
            }
            rows.append(row)
            print(json.dumps({"sample_id": sample.sample_id, "pipeline": name,
                              "segments": len(result.get("segments", []))}), flush=True)
    atomic_json(report_path, {
        "status": "EXECUTED", "network_mode": "none", "cpu": True,
        "plan": plan, "runs": rows, "human_verified_annotations": 0,
        "wer": None, "relative_wer_improvement": None, "quality_gate": "NEEDS_MORE_DATA",
        "candidate_selected": False, "release_promoted": False,
    })


if __name__ == "__main__":
    main()
