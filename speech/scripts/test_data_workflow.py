"""Real lawful audio import and annotation export/import without inventing human labels."""

import json
import uuid

from north55_speech.audio import probe
from north55_speech.core import atomic_json, settings
from north55_speech.datasets import (
    Sample,
    annotation_template,
    import_annotations,
    import_local,
    load_manifest,
    prepare_splits,
    write_manifest,
)

root = settings.artifact_root / "data-workflow" / uuid.uuid4().hex
root.mkdir(parents=True)
card = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
samples = []
for item in card["samples"]:
    key = item["filename"].removesuffix(".flac")
    info = probe(settings.audio_root / "smoke" / item["filename"])
    samples.append(
        Sample(
            sample_id=key,
            audio_path="smoke/" + item["filename"],
            audio_sha256=item["sha256"],
            source_dataset="LibriSpeech engineering control",
            source_version="dev-clean",
            recording_id=key.rsplit("-", 1)[0],
            session_id=key.rsplit("-", 1)[0],
            original_utterance_id=key,
            speaker_ids=[key.split("-")[0]],
            language="en",
            input_language="en",
            scope="general_control",
            scope_verified=True,
            speech_origin="recorded_human",
            duration_sec=info.duration_sec,
            license_id="CC-BY-4.0",
            provenance=card["source_url"],
            rights_confirmed=True,
            primary=False,
        )
    )
# Explicit allowed root is task-owned audio storage. No remote URL ingestion.
manifest = settings.audio_root / ("workflow-" + root.name + ".jsonl")
write_manifest(manifest, samples)
try:
    import_local(manifest, settings.audio_root, root / "imported.jsonl")
finally:
    manifest.unlink()
annotation_template(root / "imported.jsonl", root / "annotation-template.jsonl")
import_annotations(
    root / "imported.jsonl", root / "annotation-template.jsonl", root / "annotation-revision.jsonl"
)
revised = load_manifest(root / "annotation-revision.jsonl")
assert all(s.transcript_status == "missing" and s.events_status == "missing" for s in revised)
split = prepare_splits(root / "annotation-revision.jsonl", root / "manifests")
report = {
    "status": "PASS",
    "executed": True,
    "samples": len(samples),
    "human_labels_created": False,
    "scope": "general_control",
    "quality_evidence": False,
    "split_report": split,
    "artifact_directory": str(root),
}
atomic_json(settings.report_root / "data-workflow.json", report)
print(json.dumps(report))
