"""Precompute the declared dev ablations without gold, selection or test access."""

from __future__ import annotations

import json
import time
from pathlib import Path

import psutil

from north55_speech.benchmark import code_hash
from north55_speech.core import atomic_json, digest, file_hash, read_yaml, settings
from north55_speech.datasets import load_manifest, validate_groups
from north55_speech.pipeline import run_pipeline
from north55_speech.schemas import InferenceRequest, PipelineConfig


def main():
    if sorted(psutil.net_if_addrs()) != ["lo"]:
        raise RuntimeError("Run with --network none")
    manifest = Path("/dev/dev.jsonl")
    samples = load_manifest(manifest)
    if not samples or any(s.split != "dev" for s in samples):
        raise ValueError("Only a nonempty dev partition is allowed")
    groups = validate_groups(samples)
    search_path = Path("/app/configs/search.yaml")
    search = read_yaml(search_path)
    baseline = PipelineConfig.model_validate(read_yaml(Path("/app/configs/baseline.yaml")))
    acceptance_path = Path("/app/configs/acceptance.yaml")
    acceptance = read_yaml(acceptance_path)
    if len(search["trials"]) > min(search["max_configurations"], acceptance["search"]["max_configurations"]):
        raise ValueError("Development budget exceeded")
    configs = {trial["id"]: PipelineConfig.model_validate(
        baseline.model_dump() | {"name": trial["id"]} | trial.get("overrides", {})) for trial in search["trials"]}
    if len(configs) != len(search["trials"]):
        raise ValueError("Duplicate trial names")
    identity = {(c.model, c.device, c.compute_type, c.beam_size, c.temperature) for c in configs.values()}
    if len(identity) != 1:
        raise ValueError("All pipelines must share model, precision and baseline decoding settings")
    plan = {"manifest_sha256": file_hash(manifest), "search_sha256": file_hash(search_path),
            "acceptance_sha256": file_hash(acceptance_path), "code_hash": code_hash(),
            "runner_sha256": file_hash(Path(__file__)), "sample_ids": [s.sample_id for s in samples],
            "configs": {key: value.model_dump() for key, value in configs.items()}, "groups": groups,
            "input_language_policy": "same sample.input_language for every trial; auto in this packet",
            "publisher_scripts_mounted": False, "test_mounted": False,
            "purpose": "uns cored development inference pending human references".replace("uns cored", "unscored"),
            "selection_allowed": False}
    plan_path = settings.report_root/"pending-dev-ablation-plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != plan:
            raise ValueError("Frozen development inference plan differs; preserve the previous experiment")
    else:
        atomic_json(plan_path, plan)
    rows = []
    for sample in samples:
        request = InferenceRequest(sample_id=sample.sample_id, audio_locator=sample.audio_path,
                                   audio_sha256=sample.audio_sha256, language=sample.input_language,
                                   audio_channel=sample.channel, channel_mode="separate_channels")
        for trial_id, config in configs.items():
            key = digest({"plan": plan, "sample": sample.sample_id, "trial": trial_id})
            destination = settings.artifact_root/"pending-dev-ablation-v1"/key
            destination.mkdir(parents=True, exist_ok=True)
            record_path = destination/"inference-record.json"
            if record_path.exists():
                row = json.loads(record_path.read_text())
            else:
                started = time.perf_counter()
                row = {"sample_id": sample.sample_id, "trial": trial_id, "split": "dev",
                       "group_id": sample.group_id, "audio_sha256": sample.audio_sha256,
                       "condition": sample.acoustic_condition, "original": sample.annotation_provenance,
                       "hypothesis": "", "runtime_failure": None}
                try:
                    result = run_pipeline(request, config, destination, lambda stage, fraction: None)
                    row.update({"result": result, "hypothesis": " ".join(s["raw_asr_text"].strip() for s in result["segments"])})
                except Exception as exc:
                    # Retain every frozen item, including failures; no cherry-picking.
                    row["runtime_failure"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None), "message": str(exc)}
                row["elapsed_sec"] = time.perf_counter()-started
                row["duration_sec"] = sample.duration_sec
                atomic_json(record_path, row)
            rows.append(row)
            report = {"status": "IN_PROGRESS" if len(rows) < len(samples)*len(configs) else "EXECUTED_UNSCORED",
                      "plan_sha256": file_hash(plan_path), "network_mode": "none", "runs": rows,
                      "expected_runs": len(samples)*len(configs), "completed_runs": len(rows),
                      "runtime_failures": sum(r["runtime_failure"] is not None for r in rows),
                      "wer": None, "critical_entity_delta": None, "quality_gate": "NEEDS_MORE_DATA",
                      "selection_status": "NOT_RUN", "candidate_selected": False, "release_promoted": False}
            atomic_json(settings.report_root/"pending-dev-ablation.json", report)
            print(json.dumps({"trial": trial_id, "sample_id": sample.sample_id, "completed": len(rows),
                              "failure": row["runtime_failure"]}), flush=True)


if __name__ == "__main__":
    main()
