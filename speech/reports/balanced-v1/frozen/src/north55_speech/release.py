from __future__ import annotations

import json

from north55_speech.asr import local_model_manifest
from north55_speech.core import SpeechError, digest, file_hash, read_yaml, settings
from north55_speech.schemas import PipelineConfig


def verify_model_files(model: str) -> dict:
    manifest = local_model_manifest(model)
    root = settings.model_root / model
    for name, sha in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != sha:
            raise SpeechError(
                "MODEL_CHECKSUM_MISMATCH", "Release model files differ from recorded hashes"
            )
    return manifest


def runtime_selection() -> tuple[PipelineConfig, dict]:
    pointer = settings.artifact_root / "release.json"
    if not pointer.exists():
        config = PipelineConfig.model_validate(read_yaml(settings.pipeline_config))
        config.device, config.compute_type = settings.device, settings.compute_type
        return config, {
            "deployment_candidate": "baseline",
            "quality_gate_status": "NOT_RUN",
            "validated_scope": [],
        }
    release = json.loads(pointer.read_text())
    from north55_speech.benchmark import code_hash, pipeline_model_hash, scorer_hash

    if release["hashes"]["code"] != code_hash() or release["hashes"]["scorer"] != scorer_hash():
        raise SpeechError("RELEASE_CODE_MISMATCH", "Release does not match current code/scorer")
    config = PipelineConfig.model_validate(release["pipeline"])
    if digest(config.model_dump()) != release["hashes"]["config"]:
        raise SpeechError("RELEASE_CONFIG_MISMATCH", "Release configuration changed")
    if config.device != settings.device or config.compute_type != settings.compute_type:
        raise SpeechError("RELEASE_DEVICE_MISMATCH", "Hardware/precision differs from accepted run")
    if pipeline_model_hash(config) != release["hashes"]["model"]:
        raise SpeechError("RELEASE_MODEL_MISMATCH", "Release model revision changed")
    return config, {
        "deployment_candidate": release["run_id"],
        "quality_gate_status": "PASS",
        "validated_scope": release["validated_scope"],
    }
