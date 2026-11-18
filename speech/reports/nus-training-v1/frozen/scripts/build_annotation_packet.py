"""Build an initial train/dev-only, blinded review packet from documented checklists."""

import json
from pathlib import Path

import soundfile as sf

from north55_speech.core import atomic_json, digest, file_hash, read_yaml, settings
from north55_speech.datasets import load_manifest, validate_groups, write_manifest
from north55_speech.pipeline import run_pipeline
from north55_speech.schemas import InferenceRequest, PipelineConfig

output = Path("/packet")
if (output/"packet.json").exists():
    raise ValueError("Preserve the existing annotation packet")
output.mkdir(parents=True, exist_ok=True)
sources = []
for split in ("train", "dev"):
    rows = load_manifest(Path(f"/train-dev/{split}.jsonl"))
    if any(sample.split != split for sample in rows):
        raise ValueError("Only train/dev sources are allowed")
    sources.extend(rows)
source_ids = [
    "bleriot-a:BEA_checklists_sp001", "bleriot-a:DGA_checklist-Beech_sp101",
    "bleriot-a:DGA_checklist-Puma-1_sp105", "bleriot-a:BEA_checklists_sp002",
    "bleriot-a:BEA_checklists_sp012", "bleriot-a:DGA_checklist-PC7_sp104 ",
]
parents = {sample.sample_id: sample for sample in sources}
variants = {sample.variant_of: sample for sample in sources if sample.variant_of}
plan = {"source_ids": source_ids, "windows": [[30, 50], [90, 110]],
        "policy": "Documented checklists only; no CVR/ATC family, no test, no performance selection",
        "scope_screening_sha256": file_hash(Path('/reports/bleriot-scope-screening.json')),
        "input_language": "auto", "model": "small", "precision": "int8", "device": "cpu",
        "draft_hidden_by_default": True, "reference_text_in_prompt": False}
atomic_json(output/"plan.json", plan)
config = PipelineConfig.model_validate(read_yaml(Path("/app/configs/baseline.yaml")))
items, samples, mapping = [], [], {}
for parent_id in source_ids:
    original = parents[parent_id]
    for begin, end in plan["windows"]:
        for source in [original]+([variants[parent_id]] if parent_id in variants else []):
            clip_id = digest({"source": source.sample_id, "window": [begin, end]})[:32]
            clip = settings.audio_root/"annotation-clips-v1"/f"{clip_id}.wav"
            clip.parent.mkdir(parents=True, exist_ok=True)
            with sf.SoundFile(settings.audio_root/source.audio_path) as stream:
                stream.seek(round(begin*stream.samplerate))
                audio = stream.read(round((end-begin)*stream.samplerate), dtype="float32", always_2d=True)
                rate = stream.samplerate
            if len(audio) != round((end-begin)*rate):
                raise ValueError("Requested annotation window exceeds recording")
            sf.write(clip, audio[:, source.channel], rate, subtype="FLOAT")
            original_clip_id = digest({"source": original.sample_id, "window": [begin, end]})[:32]
            sample = source.model_copy(update={
                "sample_id": clip_id, "audio_path": str(clip.relative_to(settings.audio_root)),
                "audio_sha256": file_hash(clip), "decoded_audio_sha256": None,
                "duration_sec": end-begin, "channel": 0, "group_id": None,
                "original_utterance_id": f"{original.original_utterance_id}@{begin}:{end}",
                "variant_of": original_clip_id if source.variant_of else None,
                "continuous_recording": False, "scope": "unknown", "scope_verified": False,
                "reference_text": None, "transcript_status": "missing", "primary": False,
                "annotation_provenance": {
                    "guide": "annotation_guide_v1", "annotator": None, "reviewed_audio": False,
                    "parent_group_id": source.group_id, "source_sample_id": source.sample_id,
                    "source_audio_locator": source.audio_path, "source_audio_sha256": source.audio_sha256,
                    "original_start_sec": begin, "original_end_sec": end,
                    "timeline_mapping": "source seconds = clip seconds + original_start_sec",
                },
            })
            samples.append(sample)
            request = InferenceRequest(sample_id=clip_id, audio_locator=sample.audio_path,
                                       audio_sha256=sample.audio_sha256, language="auto", audio_channel=0)
            work = settings.artifact_root/"annotation-drafts-v1"/clip_id
            work.mkdir(parents=True, exist_ok=True)
            result = run_pipeline(request, config, work, lambda stage, progress: None)
            draft = {"text": " ".join(segment["raw_asr_text"].strip() for segment in result["segments"]),
                     "segments": result["segments"], "status": "machine", "model": result["model_manifest"],
                     "effective_config": result["effective_config"], "cache_hit": result["cache_hit"]}
            atomic_json(output/"drafts"/f"{clip_id}.json", draft)
            item = {"id": clip_id, "source_sample_id": source.sample_id, "split": sample.split,
                    "start_sec": begin, "end_sec": end, "duration_sec": end-begin,
                    "condition": source.acoustic_condition, "draft_path": f"drafts/{clip_id}.json"}
            items.append(item)
            mapping[clip_id] = original.sample_id
            print(json.dumps({"id": clip_id, "split": sample.split, "segments": len(result["segments"])}), flush=True)
groups = validate_groups(samples)
for split in ("train", "dev"):
    write_manifest(output/f"{split}.jsonl", [sample for sample in samples if sample.split == split])
atomic_json(output/"packet.json", {"items": items, "plan": plan, "groups": groups,
                                   "human_verified": 0, "quality_evidence": False})
atomic_json(Path("/reports/annotation-packet-v1.json"), {"items": len(items), "audio_minutes": sum(i["duration_sec"] for i in items)/60,
                                                      "groups": groups, "human_verified": 0, "status": "READY_FOR_HUMAN_REVIEW"})
